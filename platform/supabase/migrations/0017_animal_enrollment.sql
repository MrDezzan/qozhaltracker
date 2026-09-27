-- Животное заводится вручную, с эталонными фото со всех сторон.
-- Применять ПОСЛЕ 0016_owner_zones.sql.
--
-- Раньше животное появлялось само: система находила незнакомую особь,
-- складывала кадр в «неопознанные», человек давал кличку — и с этого
-- момента животное существовало. Порядок неудачный по двум причинам.
--
-- Первая: одно и то же животное легко заводится дважды. Утром его сняли
-- сбоку, вечером сверху, векторы вышли непохожими, и получились «Зорька»
-- и «Зорька 2». Разделить их потом почти невозможно.
--
-- Вторая, важнее: у системы нет ни одного заведомо верного эталона.
-- Она сравнивает догадку с догадкой. Ошибка на первом кадре закрепляется
-- и тянет за собой все последующие.
--
-- Правильный порядок обратный: сначала хозяйство заводит животное и даёт
-- снимки, снятые заведомо с него, — спереди, слева, справа, сзади.
-- Это и есть эталон, с которым потом сравнивается всё остальное.

-- ---------------------------------------------------------------------------
-- 1. Карточка животного
-- ---------------------------------------------------------------------------

alter table animals
  add column if not exists tag_number text,
  add column if not exists breed text,
  add column if not exists sex text,
  add column if not exists birth_date date,
  add column if not exists note text,
  -- Заведено человеком или подхвачено из кадров. Разделяем, потому что
  -- доверие к ним разное
  add column if not exists enrolled boolean not null default false;

alter table animals drop constraint if exists animals_sex_check;
alter table animals add constraint animals_sex_check
  check (sex is null or sex in ('female', 'male'));

-- Две «Зорьки» на одной ферме — это почти наверняка одно животное,
-- заведённое дважды. Такое надо ловить сразу, а не разбирать через месяц
create unique index if not exists animals_farm_label_unique
  on animals(farm_id, lower(label));

-- Бирка тоже уникальна, когда указана
create unique index if not exists animals_farm_tag_unique
  on animals(farm_id, tag_number)
  where tag_number is not null;

comment on column animals.enrolled is
  'Животное заведено человеком с эталонными снимками. Такие узнаются '
  'надёжнее: у них есть заведомо верные образцы, а не только догадки.';

-- ---------------------------------------------------------------------------
-- 2. Ракурс эталона
-- ---------------------------------------------------------------------------
-- Сравнивать снимок сбоку с эталоном спереди бессмысленно: вектор
-- признаков сильно зависит от ракурса, и такое сравнение даёт шум,
-- который выглядит как уверенное узнавание.

do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'animal_embeddings'
      and column_name = 'view'
  ) then
    alter table animal_embeddings add column "view" text not null default 'camera';
  end if;
end
$$;

alter table animal_embeddings drop constraint if exists animal_embeddings_view_check;
alter table animal_embeddings add constraint animal_embeddings_view_check
  check ("view" in ('front', 'left', 'right', 'back', 'overhead', 'camera'));

-- Откуда взялся эталон: из загруженного человеком фото или из кадра,
-- который человек подтвердил. Первым доверяем больше
alter table animal_embeddings
  add column if not exists source text not null default 'sighting';

alter table animal_embeddings drop constraint if exists animal_embeddings_source_check;
alter table animal_embeddings add constraint animal_embeddings_source_check
  check (source in ('enrollment', 'sighting'));

create index if not exists animal_embeddings_view_idx
  on animal_embeddings(animal_id, "view");

-- ---------------------------------------------------------------------------
-- 3. Загруженные фото и очередь на обработку
-- ---------------------------------------------------------------------------
-- Вектор признаков считает модель, а она живёт на мини-ПК фермы: в
-- браузере и на сервере дашборда её нет и не будет — это сотни мегабайт
-- и отдельный процессорный бюджет.
--
-- Поэтому фото кладётся в хранилище со статусом «ждёт», устройство
-- забирает его, считает вектор и отмечает готовым. Задержка — минуты,
-- и это нормально: заводят животное не каждый день.

create table if not exists animal_photos (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  animal_id uuid not null references animals(id) on delete cascade,
  "view" text not null check ("view" in ('front', 'left', 'right', 'back', 'overhead')),
  storage_path text not null,
  status text not null default 'pending'
    check (status in ('pending', 'done', 'failed')),
  -- Почему не получилось: «на снимке не найдено животное», «файл не
  -- читается». Показывается человеку, чтобы он переснял, а не гадал
  error text,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  -- Один снимок на ракурс: второй заменяет первый, а не копится рядом
  unique (animal_id, "view")
);

create index if not exists animal_photos_pending_idx
  on animal_photos(farm_id) where status = 'pending';

alter table animal_photos enable row level security;

drop policy if exists "animal_photos_read" on animal_photos;
create policy "animal_photos_read" on animal_photos
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "animal_photos_write" on animal_photos;
create policy "animal_photos_write" on animal_photos
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Устройство отмечает обработанные
drop policy if exists "animal_photos_device_update" on animal_photos;
create policy "animal_photos_device_update" on animal_photos
  for update using (farm_id = public.current_device_farm());

-- Хранилище под эталонные фото
insert into storage.buckets (id, name, public)
values ('animal-photos', 'animal-photos', false)
on conflict (id) do nothing;

drop policy if exists "animal_photos_storage_read" on storage.objects;
create policy "animal_photos_storage_read" on storage.objects
  for select using (
    bucket_id = 'animal-photos'
    and (
      (storage.foldername(name))[1] in (
        select id::text from farms where owner_user_id = auth.uid()
      )
      or public.is_admin()
      or (storage.foldername(name))[1] = public.current_device_farm()::text
    )
  );

-- with check обязателен. `for all using (...)` без него закрывает вставку:
-- USING проверяет существующие строки (select, update, delete), а новые
-- проверяются через WITH CHECK. Без него загрузка файла молча отбивается
-- по правам, и понять это по сообщению браузера невозможно.
drop policy if exists "animal_photos_storage_write" on storage.objects;
create policy "animal_photos_storage_write" on storage.objects
  for all using (
    bucket_id = 'animal-photos'
    and (
      (storage.foldername(name))[1] in (
        select id::text from farms where owner_user_id = auth.uid()
      )
      or public.is_admin()
    )
  )
  with check (
    bucket_id = 'animal-photos'
    and (
      (storage.foldername(name))[1] in (
        select id::text from farms where owner_user_id = auth.uid()
      )
      or public.is_admin()
    )
  );

-- ---------------------------------------------------------------------------
-- 4. Заведение животного одним вызовом
-- ---------------------------------------------------------------------------
-- Отдельная функция, чтобы понятно объяснить про двойника: сообщение
-- «нарушено уникальное ограничение animals_farm_label_unique» человеку
-- не говорит ничего.

create or replace function enroll_animal(
  target_farm_id uuid,
  new_label text,
  new_tag_number text default null,
  new_breed text default null,
  new_sex text default null,
  new_note text default null
)
returns animals
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_animal animals;
  v_label text := btrim(coalesce(new_label, ''));
begin
  if v_label = '' then
    raise exception 'Укажите кличку или номер животного';
  end if;

  if exists (
    select 1 from animals
    where farm_id = target_farm_id and lower(label) = lower(v_label)
  ) then
    raise exception 'Животное с кличкой «%» уже заведено', v_label;
  end if;

  insert into animals (farm_id, label, tag_number, breed, sex, note, enrolled)
  values (
    target_farm_id,
    v_label,
    nullif(btrim(coalesce(new_tag_number, '')), ''),
    nullif(btrim(coalesce(new_breed, '')), ''),
    new_sex,
    nullif(btrim(coalesce(new_note, '')), ''),
    true
  )
  returning * into v_animal;

  return v_animal;
end;
$$;

grant execute on function enroll_animal(uuid, text, text, text, text, text) to authenticated;

-- ---------------------------------------------------------------------------
-- 5. Поиск с учётом ракурса и происхождения эталона
-- ---------------------------------------------------------------------------
-- Три изменения против прежней версии:
--
--   1) можно ограничить поиск ракурсом — сравнивать вид сбоку с эталоном
--      спереди бессмысленно;
--   2) загруженные человеком эталоны весомее подтверждённых кадров;
--   3) возвращаем не только лучшего, но и отрыв от следующего. Именно
--      отрыв, а не расстояние, отвечает на вопрос «уверены ли мы»:
--      если два животных одинаково похожи, показывать кличку нельзя.

create or replace function match_animal(
  query_embedding vector(1024),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null
)
returns table (animal_id uuid, label text, distance real, margin real)
language sql
stable
as $$
  with scored as (
    select
      e.animal_id,
      a.label,
      -- Эталон, загруженный человеком, считается чуть ближе: он
      -- заведомо принадлежит этому животному, а подтверждённый кадр —
      -- лишь настолько, насколько внимателен был подтвердивший
      min(
        (e.embedding <=> query_embedding)
        - case when e.source = 'enrollment' then 0.02 else 0 end
      )::real as distance
    from animal_embeddings e
    join animals a on a.id = e.animal_id
    where e.farm_id = target_farm_id
      and (target_view is null or e."view" = target_view or e."view" = 'camera')
    group by e.animal_id, a.label
  ),
  ranked as (
    select
      s.*,
      lead(s.distance) over (order by s.distance) as runner_up
    from scored s
  )
  select
    r.animal_id,
    r.label,
    r.distance,
    -- Пусто, если сравнивать не с кем: одно животное на ферме всегда
    -- «уверенно узнано», и это надо видеть отдельно
    (r.runner_up - r.distance)::real as margin
  from ranked r
  where r.distance < match_threshold
  order by r.distance
  limit match_count;
$$;
