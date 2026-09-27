create extension if not exists pgcrypto;

create table if not exists farms (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  -- без FK на auth.users: избегаем блокировки при insert от service_role
  -- до появления реальных зарегистрированных пользователей (MVP-компромисс)
  owner_user_id uuid not null,
  created_at timestamptz not null default now()
);

create table if not exists cameras (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  name text not null,
  source_uri text not null,
  created_at timestamptz not null default now()
);

create table if not exists animals (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  label text not null,
  created_at timestamptz not null default now()
);

create table if not exists events (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  animal_id uuid references animals(id) on delete set null,
  event_type text not null check (
    event_type in ('detected', 'counted', 'weight_estimated', 'health_alert', 'face_id_matched')
  ),
  payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists events_farm_idx on events(farm_id);
create index if not exists events_animal_idx on events(animal_id);
create index if not exists events_occurred_idx on events(occurred_at);

alter table farms enable row level security;
alter table cameras enable row level security;
alter table animals enable row level security;
alter table events enable row level security;

create policy "farms_owner_all" on farms for all using (owner_user_id = auth.uid());

create policy "cameras_farm_all" on cameras for all using (
  farm_id in (select id from farms where owner_user_id = auth.uid())
);

create policy "animals_farm_all" on animals for all using (
  farm_id in (select id from farms where owner_user_id = auth.uid())
);

create policy "events_farm_select" on events for select using (
  farm_id in (select id from farms where owner_user_id = auth.uid())
);
create policy "events_farm_insert" on events for insert with check (
  farm_id in (select id from farms where owner_user_id = auth.uid())
);
