-- Охрана работает круглосуточно.
-- Применять ПОСЛЕ 0014_security.sql.
--
-- В 0014 охранное окно включало и выключало охрану целиком, и днём система
-- не смотрела вообще. Это дыра: воруют и среди бела дня, а на дальнем загоне
-- человек днём так же неуместен, как ночью.
--
-- Но и «всегда срочно» не годится. Днём по ферме ходят свои: доярки,
-- скотники, ветврач, водитель кормовоза. Тревога на каждого приучает
-- не читать тревоги — и тогда система бесполезна как раз в ту ночь,
-- ради которой её ставили.
--
-- Поэтому время суток теперь определяет НЕ «работает/не работает»,
-- а срочность и строгость:
--
--   в охранные часы  — «срочно», выдержка 5 секунд, пауза 15 минут;
--   в остальное время — «внимание», выдержка 30 секунд, пауза час.
--
-- Тридцать секунд днём — это не «прошёл мимо», а «стоит и что-то делает».
-- Именно это и стоит показать хозяину, не поднимая его с места.

-- ---------------------------------------------------------------------------
-- 1. Дневной режим
-- ---------------------------------------------------------------------------

alter table alert_settings
  -- Насколько срочной считать дневную тревогу. 'off' — не поднимать вовсе:
  -- на проходном дворе с постоянным движением иначе будет шум
  add column if not exists guard_day_severity text not null default 'warning',
  add column if not exists intruder_day_min_seconds integer not null default 30,
  add column if not exists intruder_day_cooldown_minutes integer not null default 60;

alter table alert_settings drop constraint if exists alert_settings_day_severity_check;
alter table alert_settings add constraint alert_settings_day_severity_check
  check (guard_day_severity in ('off', 'info', 'warning', 'danger'));

comment on column alert_settings.guard_day_severity is
  'Срочность тревоги о постороннем вне охранных часов. off — не поднимать. '
  'Охранные часы задаются guard_from и guard_to и означают повышенную '
  'строгость, а не единственное время работы охраны.';

comment on column alert_settings.intruder_day_min_seconds is
  'Сколько секунд человек должен продержаться в кадре днём. Больше ночного: '
  'днём люди ходят по делу, и тревожить стоит только на задержавшегося.';

-- ---------------------------------------------------------------------------
-- 2. Камеры, где людей не должно быть никогда
-- ---------------------------------------------------------------------------
-- Дальний загон, склад, топливная ёмкость. Там человек днём — такое же
-- происшествие, как ночью, и снижать срочность неправильно.

alter table cameras add column if not exists security_mode text not null default 'schedule';

alter table cameras drop constraint if exists cameras_security_mode_check;
alter table cameras add constraint cameras_security_mode_check
  check (security_mode in ('schedule', 'always'));

comment on column cameras.security_mode is
  'schedule — днём мягче, ночью строже; '
  'always — человек здесь неуместен в любое время, всегда «срочно».';

-- ---------------------------------------------------------------------------
-- 3. Реестр своего транспорта
-- ---------------------------------------------------------------------------
-- Заводим сейчас, работать начнёт вместе с распознаванием номеров.
--
-- Честно про текущее состояние: пока на въезде нет камеры с короткой
-- выдержкой и подсветкой, читать номера нечем, и реестр остаётся списком
-- без применения. Но список этот клиент составляет один раз и надолго,
-- собирать его можно уже сейчас — к моменту установки камеры он будет готов.

create table if not exists vehicles (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  -- Хранится в верхнем регистре без пробелов и дефисов: сравнивать надо
  -- нормализованное, иначе «123 ABC 02» и «123ABC02» окажутся разными
  plate text not null,
  label text,
  kind text not null default 'other'
    check (kind in ('own', 'supplier', 'service', 'other')),
  -- Разрешена ли машина. Отдельный флаг, а не удаление строки: уволенного
  -- поставщика полезно оставить в списке с пометкой «больше нельзя»
  allowed boolean not null default true,
  note text,
  created_at timestamptz not null default now(),
  unique (farm_id, plate)
);

create index if not exists vehicles_farm_idx on vehicles(farm_id);

alter table vehicles enable row level security;

drop policy if exists "vehicles_read" on vehicles;
create policy "vehicles_read" on vehicles
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "vehicles_write" on vehicles;
create policy "vehicles_write" on vehicles
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Приведение номера к сравнимому виду. Одна функция на всех, чтобы
-- нормализация при записи и при поиске не разъехалась.
create or replace function normalize_plate(raw text)
returns text
language sql
immutable
as $$
  select upper(regexp_replace(coalesce(raw, ''), '[^0-9A-Za-zА-Яа-я]', '', 'g'));
$$;

-- Нормализуем на входе, а не надеемся на аккуратность интерфейса
create or replace function vehicles_normalize_plate()
returns trigger
language plpgsql
as $$
begin
  new.plate := public.normalize_plate(new.plate);
  if new.plate = '' then
    raise exception 'Номер не может быть пустым';
  end if;
  return new;
end;
$$;

drop trigger if exists vehicles_normalize on vehicles;
create trigger vehicles_normalize
  before insert or update on vehicles
  for each row execute function vehicles_normalize_plate();
