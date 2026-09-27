-- Живое видео через интернет: сессии ретрансляции.
-- Применять ПОСЛЕ 0012_stream_autoregister.sql.
--
-- Поток по локальной сети работает и остаётся: в сети фермы видео идёт
-- прямо с мини-ПК, тридцать кадров, без облака. Но снаружи до фермы не
-- достучаться — у неё нет белого адреса, — и MJPEG туда всё равно не
-- влез бы: пятнадцать кадров это больше восьми мегабит в секунду.
--
-- Поэтому наружу отдаём иначе: ферма сама подключается к нашему серверу
-- ретрансляции и отдаёт готовый H.264 прямо с камеры, без перекодирования.
-- Это около 400 кбит/с — в двадцать раз меньше.
--
-- Здесь только учёт сессий. Кто смотрит, какую камеру, до какого времени
-- и по какому пути лежит поток.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- 1. Сессии
-- ---------------------------------------------------------------------------

create table if not exists stream_sessions (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  -- Путь на сервере ретрансляции. Случайный, а НЕ идентификатор камеры:
  -- иначе ссылка на поток была бы вечной и угадываемой, и однажды
  -- открытая вкладка осталась бы пропуском навсегда.
  path text not null unique,
  viewer_user_id uuid references auth.users(id) on delete set null,
  started_at timestamptz not null default now(),
  expires_at timestamptz not null,
  stopped_at timestamptz
);

create index if not exists stream_sessions_farm_live_idx
  on stream_sessions(farm_id, expires_at desc)
  where stopped_at is null;

create index if not exists stream_sessions_camera_idx
  on stream_sessions(camera_id, expires_at desc);

alter table stream_sessions enable row level security;

drop policy if exists "stream_sessions_read" on stream_sessions;
create policy "stream_sessions_read" on stream_sessions
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

-- Записи создаются только через функцию ниже: она сама придумывает путь
-- и следит за ограничениями. Прямой insert не нужен никому.

-- ---------------------------------------------------------------------------
-- 2. Открыть сессию
-- ---------------------------------------------------------------------------
-- Одна ферма — одна живая сессия. Два потока это 800 кбит/с, и на канале
-- фермы поедут плохо оба. Лучше честно переключать камеру, чем показывать
-- две рвущиеся картинки.

create or replace function start_remote_stream(
  target_camera_id uuid,
  seconds integer default 600
)
returns stream_sessions
language plpgsql
security definer
set search_path = public
as $$
declare
  v_farm uuid;
  v_session stream_sessions;
  v_seconds integer;
begin
  -- Потолок на длительность: вкладку забывают открытой, и без него
  -- ферма отдавала бы поток сутками ради картинки, на которую не смотрят
  v_seconds := least(greatest(coalesce(seconds, 600), 30), 1800);

  select farm_id into v_farm from cameras where id = target_camera_id;
  if v_farm is null then
    raise exception 'Камера не найдена';
  end if;

  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = v_farm and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой камере';
  end if;

  -- Закрываем всё остальное живое по этой ферме, включая другие камеры
  update stream_sessions
  set stopped_at = now()
  where farm_id = v_farm
    and stopped_at is null
    and expires_at > now();

  insert into stream_sessions (farm_id, camera_id, path, viewer_user_id, expires_at)
  values (
    v_farm,
    target_camera_id,
    -- 32 шестнадцатеричных знака: угадывать нечего
    encode(gen_random_bytes(16), 'hex'),
    auth.uid(),
    now() + make_interval(secs => v_seconds)
  )
  returning * into v_session;

  -- Та же отметка, что и у локального просмотра: устройство по ней
  -- понимает, что на камеру смотрят
  update cameras
  set live_until = greatest(coalesce(live_until, now()), v_session.expires_at)
  where id = target_camera_id;

  return v_session;
end;
$$;

grant execute on function start_remote_stream(uuid, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Закрыть досрочно
-- ---------------------------------------------------------------------------
-- Зритель закрыл вкладку — незачем держать поток до конца срока.

create or replace function stop_remote_stream(target_session_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_farm uuid;
begin
  select farm_id into v_farm from stream_sessions where id = target_session_id;
  if v_farm is null then
    return;   -- нечего закрывать, это не ошибка
  end if;

  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = v_farm and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой сессии';
  end if;

  update stream_sessions set stopped_at = now() where id = target_session_id;
end;
$$;

grant execute on function stop_remote_stream(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Что сейчас надо отдавать — для устройства
-- ---------------------------------------------------------------------------
-- Устройство спрашивает: по какой камере и по какому пути публиковать.
-- Читает своё через обычные политики, поэтому security invoker.

create or replace view active_stream_sessions
with (security_invoker = true) as
select
  s.id,
  s.farm_id,
  s.camera_id,
  s.path,
  s.expires_at
from stream_sessions s
where s.stopped_at is null
  and s.expires_at > now();

-- ---------------------------------------------------------------------------
-- 5. Проверка доступа для сервера ретрансляции
-- ---------------------------------------------------------------------------
-- Сервер ретрансляции на каждое подключение спрашивает у нас, можно ли.
-- Своих списков доступа он не ведёт — иначе право смотреть разъехалось бы
-- с правами в основной системе, и однажды разъехалось бы не в ту сторону.
--
-- Функция намеренно НЕ проверяет auth.uid(): её вызывает наш серверный
-- обработчик, у которого нет пользовательской сессии. Знание пути и есть
-- пропуск, а путь случайный и живёт минуты.

create or replace function stream_path_is_live(check_path text)
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select exists (
    select 1 from stream_sessions
    where path = check_path
      and stopped_at is null
      and expires_at > now()
  );
$$;

revoke execute on function stream_path_is_live(text) from public, anon, authenticated;

comment on function stream_path_is_live(text) is
  'Только для серверного обработчика проверки доступа сервера ретрансляции. '
  'Права отозваны у всех ролей: вызывается сервисным ключом из дашборда.';

-- ---------------------------------------------------------------------------
-- 6. Уборка
-- ---------------------------------------------------------------------------
-- Сессии копятся быстрее прочего: каждое нажатие кнопки — строка.

create or replace function prune_stream_sessions(keep_days integer default 7)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_removed integer;
begin
  delete from stream_sessions
  where expires_at < now() - make_interval(days => greatest(keep_days, 1));
  get diagnostics v_removed = row_count;
  return v_removed;
end;
$$;
