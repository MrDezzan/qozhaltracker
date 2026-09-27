-- Укрепление схемы перед боевой эксплуатацией.
-- Разбито на блоки: каждый блок независим и безопасен для повторного запуска.

-- ---------------------------------------------------------------------------
-- 1. Часовой пояс фермы
-- ---------------------------------------------------------------------------
-- База хранит время в UTC, и это правильно. Но график «по часам суток»
-- без пояса показывает, что стадо ело в три часа ночи. Пояс принадлежит
-- ферме, а не пользователю: работники в одном хозяйстве живут по одним часам.

alter table farms add column if not exists timezone text not null default 'Asia/Almaty';

-- ---------------------------------------------------------------------------
-- 2. Показания датчиков: защита от повторов и от сбитых часов
-- ---------------------------------------------------------------------------
-- LoRa переотправляет пакет, если не дождалась подтверждения. Без ключа
-- идемпотентности одно измерение попадёт в базу дважды: шаги удвоятся,
-- индекс активности подскочит, система решит, что животное в охоте.

delete from sensor_readings a
using sensor_readings b
where a.sensor_id = b.sensor_id
  and a.measured_at = b.measured_at
  and a.id > b.id;

create unique index if not exists sensor_readings_unique_measurement
  on sensor_readings(sensor_id, measured_at);

-- ---------------------------------------------------------------------------
-- 3. Составной индекс событий
-- ---------------------------------------------------------------------------
-- Основной запрос дашборда — «последние события этой фермы». Двух отдельных
-- индексов для него мало: планировщик возьмёт один и отсортирует остаток.

create index if not exists events_farm_occurred_idx
  on events(farm_id, occurred_at desc);

create index if not exists sightings_farm_occurred_idx
  on sightings(farm_id, occurred_at desc);

-- ---------------------------------------------------------------------------
-- 4. Эталонные векторы животных
-- ---------------------------------------------------------------------------
-- Раньше поиск похожего животного перебирал всю историю кадров. За год это
-- сотни тысяч векторов по 4 КБ: и медленно, и точность падает, потому что
-- среди старых кадров попадаются неудачные.
--
-- Теперь у каждого животного своя небольшая подборка эталонов. Кадр,
-- которому вручную поставили кличку, становится эталоном; лишние вытесняются.

create table if not exists animal_embeddings (
  id bigserial primary key,
  farm_id uuid not null references farms(id) on delete cascade,
  animal_id uuid not null references animals(id) on delete cascade,
  embedding vector(1024) not null,
  source_sighting_id uuid references sightings(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists animal_embeddings_farm_idx on animal_embeddings(farm_id);
create index if not exists animal_embeddings_animal_idx
  on animal_embeddings(animal_id, created_at desc);

-- hnsw вместо ivfflat: ivfflat строит центроиды по содержимому таблицы,
-- а на момент миграции таблица пуста — индекс получался бесполезным.
-- hnsw обучения не требует и достраивается по мере наполнения.
create index if not exists animal_embeddings_vector_idx
  on animal_embeddings using hnsw (embedding vector_cosine_ops);

alter table animal_embeddings enable row level security;

drop policy if exists "animal_embeddings_read" on animal_embeddings;
create policy "animal_embeddings_read" on animal_embeddings
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "animal_embeddings_write" on animal_embeddings;
create policy "animal_embeddings_write" on animal_embeddings
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Сколько эталонов держим на животное. Больше — точнее в разных позах,
-- но дороже поиск. Двадцать перекрывают ракурсы и освещение.
create or replace function trim_animal_embeddings(p_animal_id uuid, p_keep integer default 20)
returns void
language sql
security definer
set search_path = public
as $$
  delete from animal_embeddings
  where id in (
    select id from animal_embeddings
    where animal_id = p_animal_id
    order by created_at desc
    offset p_keep
  );
$$;

revoke execute on function trim_animal_embeddings(uuid, integer) from public;

-- Как только кадру присвоили животное, он становится эталоном.
create or replace function promote_sighting_to_embedding()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.animal_id is null or new.embedding is null then
    return new;
  end if;
  if tg_op = 'UPDATE' and old.animal_id is not distinct from new.animal_id then
    return new;
  end if;

  insert into animal_embeddings (farm_id, animal_id, embedding, source_sighting_id)
  values (new.farm_id, new.animal_id, new.embedding, new.id);

  perform trim_animal_embeddings(new.animal_id);
  return new;
end;
$$;

drop trigger if exists sightings_promote_embedding on sightings;
create trigger sightings_promote_embedding
  after insert or update of animal_id on sightings
  for each row execute function promote_sighting_to_embedding();

-- Перенос уже накопленных названных кадров в эталоны
insert into animal_embeddings (farm_id, animal_id, embedding, source_sighting_id)
select s.farm_id, s.animal_id, s.embedding, s.id
from sightings s
where s.animal_id is not null
  and s.embedding is not null
  and not exists (
    select 1 from animal_embeddings e where e.source_sighting_id = s.id
  );

-- Поиск теперь идёт по эталонам, а не по всей истории.
create or replace function match_animal(
  query_embedding vector(1024),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5
)
returns table (animal_id uuid, label text, distance real)
language sql
stable
as $$
  select
    e.animal_id,
    a.label,
    min(e.embedding <=> query_embedding)::real as distance
  from animal_embeddings e
  join animals a on a.id = e.animal_id
  where e.farm_id = target_farm_id
  group by e.animal_id, a.label
  having min(e.embedding <=> query_embedding) < match_threshold
  order by min(e.embedding <=> query_embedding)
  limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- 5. Срок хранения
-- ---------------------------------------------------------------------------
-- Ничто не удалялось. Кадры животных лежат по уникальным путям, то есть
-- хранилище росло монотонно и на бесплатном тарифе кончилось бы за месяцы.
--
-- Сводки по поголовью и визиты — это история хозяйства, их держим дольше.
-- Картинки — расходный материал: они нужны, пока по ним кого-то называют.

create table if not exists retention_policy (
  farm_id uuid primary key references farms(id) on delete cascade,
  events_days integer not null default 400,
  sightings_days integer not null default 30,
  snapshots_days integer not null default 7,
  sensor_readings_days integer not null default 400
);

alter table retention_policy enable row level security;

drop policy if exists "retention_read" on retention_policy;
create policy "retention_read" on retention_policy
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

drop policy if exists "retention_admin_write" on retention_policy;
create policy "retention_admin_write" on retention_policy
  for all using (public.is_admin());

-- Уборка. Возвращает, сколько чего удалено, чтобы это было видно в журнале.
create or replace function prune_old_data()
returns table (
  deleted_events bigint,
  deleted_sightings bigint,
  deleted_readings bigint,
  deleted_files bigint
)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_events bigint := 0;
  v_sightings bigint := 0;
  v_readings bigint := 0;
  v_files bigint := 0;
begin
  -- Ферма без своей политики убирается по значениям по умолчанию
  insert into retention_policy (farm_id)
  select f.id from farms f
  where not exists (select 1 from retention_policy p where p.farm_id = f.id);

  with removed as (
    delete from events e
    using retention_policy p
    where e.farm_id = p.farm_id
      and e.occurred_at < now() - make_interval(days => p.events_days)
    returning 1
  )
  select count(*) into v_events from removed;

  -- Названные кадры не трогаем: они основа эталонов и датасета
  with removed as (
    delete from sightings s
    using retention_policy p
    where s.farm_id = p.farm_id
      and s.animal_id is null
      and s.occurred_at < now() - make_interval(days => p.sightings_days)
    returning 1
  )
  select count(*) into v_sightings from removed;

  with removed as (
    delete from sensor_readings r
    using retention_policy p
    where r.farm_id = p.farm_id
      and r.measured_at < now() - make_interval(days => p.sensor_readings_days)
    returning 1
  )
  select count(*) into v_readings from removed;

  -- Файлы, на которые больше никто не ссылается
  with removed as (
    delete from storage.objects o
    where o.bucket_id = 'crops'
      and o.created_at < now() - interval '30 days'
      and not exists (
        select 1 from sightings s where s.crop_path = o.name
      )
    returning 1
  )
  select count(*) into v_files from removed;

  return query select v_events, v_sightings, v_readings, v_files;
end;
$$;

revoke execute on function prune_old_data() from public;
grant execute on function prune_old_data() to service_role;

-- ---------------------------------------------------------------------------
-- 6. Согласие с условиями
-- ---------------------------------------------------------------------------
-- Видеонаблюдение за работниками и обработка их изображений требуют
-- документального основания. Факт принятия условий фиксируется с версией:
-- при изменении текста согласие спрашивается заново.

create table if not exists terms_acceptances (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  version text not null,
  accepted_at timestamptz not null default now(),
  unique (user_id, version)
);

alter table terms_acceptances enable row level security;

drop policy if exists "terms_self_read" on terms_acceptances;
create policy "terms_self_read" on terms_acceptances
  for select using (user_id = auth.uid() or public.is_admin());

drop policy if exists "terms_self_insert" on terms_acceptances;
create policy "terms_self_insert" on terms_acceptances
  for insert with check (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- 7. Приём показаний: проверка времени
-- ---------------------------------------------------------------------------
-- У шлюза садится батарейка часов, и он начинает слать измерения из 1970-го
-- или из 2099-го. Показание из будущего особенно вредно: представление
-- «последнее состояние» берёт максимум по времени и залипает на нём навсегда.

create or replace function ingest_sensor_reading(
  p_serial text,
  p_measured_at timestamptz,
  p_temperature_c real default null,
  p_steps integer default null,
  p_activity_index real default null,
  p_battery_percent smallint default null,
  p_tamper boolean default false,
  p_payload jsonb default '{}'::jsonb
)
returns bigint
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_sensor sensors%rowtype;
  v_id bigint;
begin
  if p_measured_at > now() + interval '10 minutes' then
    raise exception 'Время измерения в будущем (%). Проверьте часы шлюза', p_measured_at;
  end if;
  if p_measured_at < now() - interval '30 days' then
    raise exception 'Время измерения слишком старое (%). Проверьте часы шлюза', p_measured_at;
  end if;
  if p_temperature_c is not null and (p_temperature_c < 20 or p_temperature_c > 45) then
    raise exception 'Температура % вне физиологического диапазона', p_temperature_c;
  end if;

  select * into v_sensor
  from sensors
  where serial = p_serial
    and farm_id = public.current_device_farm();

  if not found then
    raise exception 'Датчик % не найден на этой ферме', p_serial;
  end if;

  insert into sensor_readings (
    farm_id, sensor_id, animal_id, measured_at,
    temperature_c, steps, activity_index, battery_percent, tamper, payload
  )
  values (
    v_sensor.farm_id, v_sensor.id, v_sensor.animal_id, p_measured_at,
    p_temperature_c, p_steps, p_activity_index, p_battery_percent, p_tamper, p_payload
  )
  -- Повтор пакета — не ошибка шлюза, а нормальная работа радиоканала
  on conflict (sensor_id, measured_at) do nothing
  returning id into v_id;

  if v_id is null then
    select id into v_id from sensor_readings
    where sensor_id = v_sensor.id and measured_at = p_measured_at;
    return v_id;
  end if;

  update sensors
  set last_seen_at = greatest(coalesce(last_seen_at, p_measured_at), p_measured_at),
      battery_percent = coalesce(p_battery_percent, battery_percent)
  where id = v_sensor.id;

  return v_id;
end;
$$;

grant execute on function ingest_sensor_reading(
  text, timestamptz, real, integer, real, smallint, boolean, jsonb
) to authenticated;
