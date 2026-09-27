-- Роли пользователей, устройства ферм и разграничение доступа.
-- Применять ПОСЛЕ 0001_init_schema.sql.

-- ============================================================
-- 1. Профили: роль каждого пользователя
-- ============================================================

create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null default 'owner' check (role in ('admin', 'owner', 'device')),
  -- для role='device': к какой ферме привязано устройство
  farm_id uuid references farms(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

-- Профиль создаётся автоматически при регистрации пользователя.
-- Роль по умолчанию 'owner' — повысить до 'admin' может только админ.
create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, role)
  values (new.id, coalesce(new.raw_app_meta_data->>'role', 'owner'))
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- Профили для уже существующих пользователей
insert into profiles (id, role)
select id, 'owner' from auth.users
on conflict (id) do nothing;

-- ============================================================
-- 2. Helper-функции
--
-- SECURITY DEFINER обязателен: функция читает profiles в обход RLS.
-- Без этого политика на profiles, которая читает profiles, уходит
-- в бесконечную рекурсию — классическая ошибка в Supabase.
-- ============================================================

create or replace function is_admin()
returns boolean
language sql
security definer
stable
set search_path = public
as $$
  select exists (
    select 1 from profiles where id = auth.uid() and role = 'admin'
  );
$$;

-- Ферма, к которой привязано текущее устройство (null для людей)
create or replace function current_device_farm()
returns uuid
language sql
security definer
stable
set search_path = public
as $$
  select farm_id from profiles where id = auth.uid() and role = 'device';
$$;

-- ============================================================
-- 3. Устройства ферм (мини-ПК с cv-service)
-- ============================================================

create table if not exists devices (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  login text not null unique,
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists devices_farm_idx on devices(farm_id);

alter table devices enable row level security;

-- ============================================================
-- 4. Политики доступа
--
-- Принцип: админ видит всё; владелец — только свою ферму;
-- устройство — только свою ферму и только на запись событий.
-- ============================================================

-- profiles: свой профиль читаем, админ читает и меняет все.
-- Пользователь НЕ может менять свою роль — политики update для него нет вовсе.
drop policy if exists "profiles_self_select" on profiles;
create policy "profiles_self_select" on profiles
  for select using (id = auth.uid() or is_admin());

drop policy if exists "profiles_admin_all" on profiles;
create policy "profiles_admin_all" on profiles
  for all using (is_admin()) with check (is_admin());

alter table profiles enable row level security;

-- farms
drop policy if exists "farms_owner_all" on farms;
create policy "farms_owner_select" on farms
  for select using (
    owner_user_id = auth.uid()
    or is_admin()
    or id = current_device_farm()
  );
create policy "farms_admin_write" on farms
  for all using (is_admin()) with check (is_admin());

-- cameras: устройство читает свои камеры, админ управляет всеми
drop policy if exists "cameras_farm_all" on cameras;
create policy "cameras_read" on cameras
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or is_admin()
    or farm_id = current_device_farm()
  );
create policy "cameras_admin_write" on cameras
  for all using (is_admin()) with check (is_admin());

-- animals
drop policy if exists "animals_farm_all" on animals;
create policy "animals_read" on animals
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or is_admin()
    or farm_id = current_device_farm()
  );
create policy "animals_write" on animals
  for all using (is_admin() or farm_id = current_device_farm())
  with check (is_admin() or farm_id = current_device_farm());

-- events: устройство пишет только своей ферме
drop policy if exists "events_farm_select" on events;
drop policy if exists "events_farm_insert" on events;
create policy "events_read" on events
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or is_admin()
    or farm_id = current_device_farm()
  );
create policy "events_device_insert" on events
  for insert with check (
    farm_id = current_device_farm() or is_admin()
  );

-- devices: пароли здесь не хранятся (они в auth.users), но логины
-- видны только админу и самому устройству
create policy "devices_read" on devices
  for select using (is_admin() or user_id = auth.uid());
create policy "devices_admin_write" on devices
  for all using (is_admin()) with check (is_admin());

-- Устройство отмечает "я жив": разрешаем менять только свою строку.
create or replace function device_heartbeat()
returns void
language sql
security definer
set search_path = public
as $$
  update devices set last_seen_at = now() where user_id = auth.uid();
$$;

-- ============================================================
-- 5. Сводка по фермам для админки (одним запросом вместо N+1)
-- ============================================================

create or replace view admin_farm_overview
with (security_invoker = true) as
select
  f.id            as farm_id,
  f.name          as farm_name,
  f.created_at    as farm_created_at,
  (select count(*) from cameras c where c.farm_id = f.id)          as cameras_count,
  (select max(d.last_seen_at) from devices d where d.farm_id = f.id) as device_last_seen,
  (select count(*) from events e
     where e.farm_id = f.id and e.occurred_at > now() - interval '24 hours') as events_24h,
  (select max(e.occurred_at) from events e where e.farm_id = f.id)  as last_event_at
from farms f;
