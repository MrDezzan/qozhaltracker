-- ---------------------------------------------------------------------------
-- Кадры для дообучения и их отбраковка
-- ---------------------------------------------------------------------------
-- Сейчас полных кадров у нас нет ни одного. Снимки в `snapshots` для этого
-- не годятся по двум причинам, и обе неочевидны:
--
--   1. на них НАРИСОВАНЫ рамки. Обучать на такой картинке нельзя: модель
--      станет искать зелёные линии, а не животных;
--   2. путь снимка постоянный — `{ферма}/{камера}.jpg`, — и файл каждые
--      пятнадцать секунд перезаписывается. В хранилище всегда ровно один
--      кадр на камеру, накопить съёмку за две недели невозможно.
--
-- Поэтому отдельное хранилище и отдельная таблица.
--
-- Зачем таблица, если файлы и так лежат в хранилище: по файлу невозможно
-- понять, ПОЧЕМУ его отобрали и что модель на нём увидела. А отбраковка
-- строится именно на этом — админ смотрит не случайные кадры, а те, где
-- система сомневалась.

-- ---------------------------------------------------------------------------
-- Хранилище
-- ---------------------------------------------------------------------------
-- Приватное. Кадр с фермы — данные клиента, и в открытый доступ они не
-- выкладываются даже без людей в кадре.

insert into storage.buckets (id, name, public)
values ('training', 'training', false)
on conflict (id) do nothing;

-- Путь: {farm_id}/{camera_id}/{ГГГГ-ММ-ДД}/{метка времени}.jpg
--
-- Дата отдельным сегментом не для красоты: делить датасет на обучение и
-- проверку надо ПО ДНЯМ, иначе кадры, снятые с разницей в секунду,
-- попадут в обе части. Модель покажет 98% точности, а на новой ферме не
-- заработает. С датой в пути такое деление делается одной командой.

drop policy if exists "training_device_write" on storage.objects;
create policy "training_device_write" on storage.objects
  for insert with check (
    bucket_id = 'training'
    and (storage.foldername(name))[1]::uuid = public.current_device_farm()
  );

drop policy if exists "training_read" on storage.objects;
create policy "training_read" on storage.objects
  for select using (
    bucket_id = 'training'
    and (
      public.is_admin()
      or (storage.foldername(name))[1]::uuid = public.current_device_farm()
      or (storage.foldername(name))[1]::uuid in (
        select id from public.farms where owner_user_id = auth.uid()
      )
    )
  );

drop policy if exists "training_admin_delete" on storage.objects;
create policy "training_admin_delete" on storage.objects
  for delete using (bucket_id = 'training' and public.is_admin());

-- Устройству удаление в своей папке тоже разрешено, и вот зачем.
--
-- Кадр кладётся в два приёма: сначала файл, потом строка в базе. Если
-- на втором шаге выяснится, что суточный потолок уже выбран, файл
-- останется в хранилище без строки — а такой файл не виден ниоткуда,
-- не попадёт ни в один датасет и не будет убран никогда.
--
-- Обратный порядок хуже: строка без файла даёт пустую картинку на
-- экране отбраковки, и админ не поймёт, что смотрит.
drop policy if exists "training_device_delete" on storage.objects;
create policy "training_device_delete" on storage.objects
  for delete using (
    bucket_id = 'training'
    and (storage.foldername(name))[1]::uuid = public.current_device_farm()
  );

-- ---------------------------------------------------------------------------
-- Таблица
-- ---------------------------------------------------------------------------

create table if not exists training_frames (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,

  -- Путь в хранилище `training`
  path text not null unique,
  captured_at timestamptz not null default now(),

  -- Почему кадр отобран. Случайные кадры размечать бессмысленно:
  -- соседние почти одинаковы, и модель полторы тысячи раз увидит одно и
  -- то же. Отбирать надо там, где модель ошибается
  --
  --   low_confidence — есть обнаружение с уверенностью 0,3–0,6
  --   count_jump     — счётчик скакнул относительно прошлого кадра
  --   crowded        — рамки животных сильно перекрываются
  --   routine        — обычный кадр для равновесия. Без таких модель
  --                    разучится работать в лёгких условиях
  reason text not null check (
    reason in ('low_confidence', 'count_jump', 'crowded', 'routine')
  ),

  -- Что модель нашла: число животных и уверенности. Лежит здесь, чтобы
  -- экран отбраковки не скачивал сам кадр ради одной цифры
  detections jsonb not null default '{}'::jsonb,

  -- Вердикт админа. null — кадр ещё не смотрели
  --
  --   ok     — модель права, кадр в разметку не нужен
  --   merged — слиплись: несколько животных обведены как одно
  --   missed — пропустила животное
  --   junk   — кадр негодный: пустой, засвет, камера сдвинулась
  verdict text check (verdict in ('ok', 'merged', 'missed', 'junk')),
  verdict_by uuid references auth.users(id) on delete set null,
  verdict_at timestamptz,

  created_at timestamptz not null default now()
);

-- Главный запрос экрана: «дай следующий непросмотренный». Частичный
-- индекс — по мере отбраковки он усыхает, а не растёт вместе с таблицей
create index if not exists training_frames_pending_idx
  on training_frames (captured_at)
  where verdict is null;

create index if not exists training_frames_farm_idx
  on training_frames (farm_id, captured_at desc);

alter table training_frames enable row level security;

drop policy if exists "training_frames_device_write" on training_frames;
create policy "training_frames_device_write" on training_frames
  for insert with check (farm_id = public.current_device_farm());

drop policy if exists "training_frames_read" on training_frames;
create policy "training_frames_read" on training_frames
  for select using (
    public.is_admin()
    or farm_id = public.current_device_farm()
    or farm_id in (select id from farms where owner_user_id = auth.uid())
  );

-- Вердикт ставит только админ. Владелец фермы свои кадры видит, но
-- решать, что идёт в обучение общей модели, не может: его ошибка
-- испортила бы модель у всех остальных клиентов
drop policy if exists "training_frames_admin_update" on training_frames;
create policy "training_frames_admin_update" on training_frames
  for update using (public.is_admin());

drop policy if exists "training_frames_admin_delete" on training_frames;
create policy "training_frames_admin_delete" on training_frames
  for delete using (public.is_admin());

-- ---------------------------------------------------------------------------
-- Суточный потолок
-- ---------------------------------------------------------------------------
-- Сбор включают руками и забывают выключить. За месяц одна камера при
-- кадре в тридцать секунд даёт под сто тысяч файлов, и обнаружится это
-- по счёту за хранилище.
--
-- Потолок стоит здесь, а не только на устройстве: устройств на ферме
-- может быть несколько, и каждое про других не знает.

create or replace function training_frames_today(
  p_farm_id uuid,
  p_camera_id uuid
)
returns integer
language sql
stable
set search_path = public
as $$
  select count(*)::integer
  from training_frames
  where farm_id = p_farm_id
    and camera_id = p_camera_id
    and captured_at >= date_trunc('day', now() at time zone farm_timezone(p_farm_id))
        at time zone farm_timezone(p_farm_id);
$$;

grant execute on function training_frames_today(uuid, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Запись кадра
-- ---------------------------------------------------------------------------
-- Возвращает id или null, если суточный потолок выбран. Null, а не
-- ошибка: для устройства это штатная ситуация, ронять из-за неё обработку
-- видео нельзя.

create or replace function add_training_frame(
  p_camera_id uuid,
  p_path text,
  p_reason text,
  p_detections jsonb default '{}'::jsonb,
  p_daily_cap integer default 200
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_farm_id uuid;
  v_today integer;
  v_id uuid;
begin
  v_farm_id := current_device_farm();
  if v_farm_id is null then
    raise exception 'Кадры для дообучения пишет только устройство фермы';
  end if;

  -- Камера обязана принадлежать этой же ферме. Без проверки устройство
  -- одной фермы могло бы записать кадр на камеру чужой
  if not exists (
    select 1 from cameras
    where id = p_camera_id and farm_id = v_farm_id
  ) then
    raise exception 'Камера не принадлежит этой ферме';
  end if;

  v_today := training_frames_today(v_farm_id, p_camera_id);
  if v_today >= p_daily_cap then
    return null;
  end if;

  insert into training_frames (farm_id, camera_id, path, reason, detections)
  values (v_farm_id, p_camera_id, p_path, p_reason, p_detections)
  on conflict (path) do nothing
  returning id into v_id;

  return v_id;
end;
$$;

grant execute on function add_training_frame(uuid, text, text, jsonb, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- Следующий кадр на отбраковку
-- ---------------------------------------------------------------------------
-- Порядок — от старых к новым, и это не безразлично: свежие кадры сняты
-- при той же погоде, что и вчерашние, а старые покрывают больше условий.

create or replace function next_training_frame(
  p_farm_id uuid default null
)
returns table (
  id uuid,
  farm_id uuid,
  farm_name text,
  camera_id uuid,
  camera_name text,
  path text,
  captured_at timestamptz,
  reason text,
  detections jsonb,
  pending integer
)
language sql
stable
set search_path = public
as $$
  with pending_frames as (
    select t.*
    from training_frames t
    where t.verdict is null
      and (p_farm_id is null or t.farm_id = p_farm_id)
  )
  select
    p.id,
    p.farm_id,
    f.name as farm_name,
    p.camera_id,
    c.name as camera_name,
    p.path,
    p.captured_at,
    p.reason,
    p.detections,
    (select count(*)::integer from pending_frames) as pending
  from pending_frames p
  join farms f on f.id = p.farm_id
  join cameras c on c.id = p.camera_id
  order by p.captured_at
  limit 1;
$$;

grant execute on function next_training_frame(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Поставить вердикт
-- ---------------------------------------------------------------------------

create or replace function review_training_frame(
  p_frame_id uuid,
  p_verdict text
)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated integer;
begin
  if not is_admin() then
    raise exception 'Отбраковку делает только администратор';
  end if;

  if p_verdict not in ('ok', 'merged', 'missed', 'junk') then
    raise exception 'Неизвестный вердикт: %', p_verdict;
  end if;

  -- Условие `verdict is null` не лишнее: без него случайный повторный
  -- клик перезаписал бы уже поставленный вердикт, и заметить это было бы
  -- невозможно — экран выглядит одинаково
  update training_frames
  set verdict = p_verdict,
      verdict_by = auth.uid(),
      verdict_at = now()
  where id = p_frame_id and verdict is null;

  get diagnostics v_updated = row_count;
  return v_updated > 0;
end;
$$;

grant execute on function review_training_frame(uuid, text) to authenticated;

-- ---------------------------------------------------------------------------
-- Сводка
-- ---------------------------------------------------------------------------
-- Отвечает на единственный вопрос, ради которого всё это: сколько кадров
-- уже годится в разметку и стоит ли продолжать сбор.

create or replace function training_summary()
returns table (
  farm_id uuid,
  farm_name text,
  total integer,
  pending integer,
  ok integer,
  merged integer,
  missed integer,
  junk integer,
  days integer,
  first_at timestamptz,
  last_at timestamptz
)
language sql
stable
set search_path = public
as $$
  select
    t.farm_id,
    f.name as farm_name,
    count(*)::integer as total,
    count(*) filter (where t.verdict is null)::integer as pending,
    count(*) filter (where t.verdict = 'ok')::integer as ok,
    count(*) filter (where t.verdict = 'merged')::integer as merged,
    count(*) filter (where t.verdict = 'missed')::integer as missed,
    count(*) filter (where t.verdict = 'junk')::integer as junk,
    -- Дней съёмки. Важнее общего числа кадров: полторы тысячи кадров за
    -- один день — это фактически один день погоды и одно освещение
    count(distinct date_trunc('day', t.captured_at))::integer as days,
    min(t.captured_at) as first_at,
    max(t.captured_at) as last_at
  from training_frames t
  join farms f on f.id = t.farm_id
  where is_admin() or t.farm_id in (
    select id from farms where owner_user_id = auth.uid()
  )
  group by t.farm_id, f.name
  order by count(*) desc;
$$;

grant execute on function training_summary() to authenticated;

-- ---------------------------------------------------------------------------
-- Уборка
-- ---------------------------------------------------------------------------
-- Удаляет только `junk` — негодные кадры. Всё остальное, включая `ok`,
-- нужно: обычные дневные кадры составляют четверть датасета, без них
-- модель разучится работать в лёгких условиях.
--
-- Файлы из хранилища эта функция НЕ удаляет: у базы нет к нему доступа.
-- Пути возвращаются, чтобы вызывающий подчистил их сам.

-- Имя выходной колонки НЕ `path`: в PL/pgSQL оно стало бы переменной и
-- любое упоминание колонки `path` внутри превратилось бы в «column
-- reference is ambiguous». Удаление при этом не выполнилось бы вовсе.
create or replace function prune_training_junk(p_older_than_days integer default 7)
returns table (deleted_path text)
language plpgsql
security definer
set search_path = public
as $$
begin
  if not is_admin() then
    raise exception 'Уборку делает только администратор';
  end if;

  -- Удаление обёрнуто в CTE: `return query` ждёт запрос, а не команду
  -- изменения данных
  return query
  with removed as (
    delete from training_frames t
    where t.verdict = 'junk'
      and t.verdict_at < now() - make_interval(days => p_older_than_days)
    returning t.path
  )
  select r.path from removed r;
end;
$$;

grant execute on function prune_training_junk(integer) to authenticated;

notify pgrst, 'reload schema';
