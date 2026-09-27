-- Зоны интереса на кадре: кормушка, поилка, проход.
-- Применять ПОСЛЕ 0003_snapshots.sql.
--
-- Идея: чтобы понять, что животное ест, не нужна отдельная нейросеть.
-- Достаточно обвести кормушку многоугольником и смотреть, попадает ли
-- в него нижняя точка рамки животного. Время внутри = время кормления.

create table if not exists zones (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  name text not null,
  kind text not null check (kind in ('feeder', 'water', 'gate', 'other')),
  -- Координаты в долях от 0 до 1, а не в пикселях: зона переживает
  -- смену разрешения камеры и одинаково работает на снимке и на видео.
  polygon jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists zones_camera_idx on zones(camera_id);
create index if not exists zones_farm_idx on zones(farm_id);

alter table zones enable row level security;

create policy "zones_read" on zones
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or is_admin()
    or farm_id = current_device_farm()
  );

create policy "zones_admin_write" on zones
  for all using (is_admin()) with check (is_admin());

-- Новые типы событий: вход в зону и выход с длительностью визита
alter table events drop constraint if exists events_event_type_check;
alter table events add constraint events_event_type_check check (
  event_type in (
    'detected',
    'counted',
    'weight_estimated',
    'health_alert',
    'face_id_matched',
    'zone_enter',
    'zone_exit'
  )
);

-- Сводка по кормлению за сутки: сколько визитов и сколько времени.
-- Пока без разбивки по животным — для этого нужна re-identification.
create or replace view farm_zone_activity
with (security_invoker = true) as
select
  e.farm_id,
  (e.payload->>'zone_id')::uuid            as zone_id,
  e.payload->>'zone_name'                  as zone_name,
  e.payload->>'zone_kind'                  as zone_kind,
  date_trunc('hour', e.occurred_at)        as hour,
  count(*)                                 as visits,
  coalesce(sum((e.payload->>'duration_s')::numeric), 0) as total_seconds
from events e
where e.event_type = 'zone_exit'
group by 1, 2, 3, 4, 5;
