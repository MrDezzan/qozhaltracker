-- Носимые датчики на животных: температура, активность, шаги, снятие с животного.
-- Применять ПОСЛЕ 0006_sightings.sql.
--
-- Камера и датчик дополняют друг друга, а не заменяют:
-- камера видит поведение и место, датчик — температуру и движение
-- круглосуточно, включая ночь и места без обзора.

create table if not exists sensors (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  -- Датчик может лежать на складе непривязанным
  animal_id uuid references animals(id) on delete set null,
  serial text not null,
  model text,
  battery_percent smallint check (battery_percent between 0 and 100),
  last_seen_at timestamptz,
  attached_at timestamptz,
  created_at timestamptz not null default now(),
  unique (farm_id, serial)
);

create index if not exists sensors_farm_idx on sensors(farm_id);
create index if not exists sensors_animal_idx on sensors(animal_id);

-- Показания. Держим одной таблицей с jsonb: у разных моделей датчиков
-- разный набор величин, а заводить колонку под каждую — тупик.
create table if not exists sensor_readings (
  id bigserial primary key,
  farm_id uuid not null references farms(id) on delete cascade,
  sensor_id uuid not null references sensors(id) on delete cascade,
  animal_id uuid references animals(id) on delete set null,
  measured_at timestamptz not null,
  temperature_c real,
  steps integer,
  activity_index real,
  battery_percent smallint,
  tamper boolean not null default false,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists sensor_readings_animal_idx
  on sensor_readings(animal_id, measured_at desc);
create index if not exists sensor_readings_farm_idx
  on sensor_readings(farm_id, measured_at desc);

alter table sensors enable row level security;
alter table sensor_readings enable row level security;

create policy "sensors_read" on sensors
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

create policy "sensors_write" on sensors
  for all using (
    public.is_admin()
    or farm_id in (select id from farms where owner_user_id = auth.uid())
  )
  with check (
    public.is_admin()
    or farm_id in (select id from farms where owner_user_id = auth.uid())
  );

create policy "sensor_readings_read" on sensor_readings
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

-- Показания шлёт шлюз фермы под учёткой устройства
create policy "sensor_readings_device_insert" on sensor_readings
  for insert with check (
    farm_id = public.current_device_farm() or public.is_admin()
  );

-- Последнее показание по каждому животному — то, что видно в карточке
create or replace view animal_latest_state
with (security_invoker = true) as
select distinct on (r.animal_id)
  r.animal_id,
  r.farm_id,
  r.sensor_id,
  r.measured_at,
  r.temperature_c,
  r.steps,
  r.activity_index,
  r.battery_percent,
  r.tamper
from sensor_readings r
where r.animal_id is not null
order by r.animal_id, r.measured_at desc;

-- Приём показания: одна операция вместо трёх запросов со шлюза.
-- Заодно обновляет отметку «датчик на связи» и заряд.
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
  returning id into v_id;

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
