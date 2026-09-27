-- Тревога о постороннем на территории.
-- Применять ПОСЛЕ 0013_remote_stream.sql.
--
-- Детекция людей у нас работала с самого начала — она просто выключена и
-- стоит в чёрном списке, чтобы никто случайно не посчитал скотника за
-- корову. Здесь мы включаем её ВТОРЫМ, независимым потоком: человек не
-- попадает ни в поголовье, ни в визиты у кормушки, ни в оценку веса.
--
-- Человек на ферме днём — норма. Ночью в загоне — событие.

-- ---------------------------------------------------------------------------
-- 1. Ключ группировки тревог
-- ---------------------------------------------------------------------------
-- Это надо сделать здесь и сейчас, до всех новых видов тревог.
--
-- Сейчас ключ считается как coalesce(animal_id, sensor_id, camera_id).
-- Тревоге «корма кончаются» не соответствует ни животное, ни датчик, ни
-- камера, и subject_id стал бы NULL. А в Postgres NULL в уникальном
-- индексе НЕ КОНФЛИКТУЕТ САМ С СОБОЙ — то есть защита от дублей молча
-- отключилась бы, и одна тревога наплодила бы по записи на каждый прогон
-- расписания: 144 штуки в сутки.
--
-- Поэтому последним запасным вариантом ставим саму ферму: тогда ключ
-- не бывает пустым никогда, и дедупликация работает даже для тревог,
-- которые относятся к хозяйству целиком.

drop index if exists alerts_open_unique;
alter table alerts drop column if exists subject_id;

-- Внешние ключи на эти колонки появятся вместе с таблицами: item_id
-- в 0015 (склад), staff_id в 0019 (работники)
alter table alerts add column if not exists item_id uuid;
alter table alerts add column if not exists staff_id uuid;

alter table alerts add column subject_id uuid generated always as (
  coalesce(animal_id, sensor_id, camera_id, item_id, staff_id, farm_id)
) stored;

create unique index alerts_open_unique
  on alerts(farm_id, kind, subject_id)
  where resolved_at is null;

-- Снимок к тревоге: показать, кого именно увидели
alter table alerts add column if not exists snapshot_path text;

-- ---------------------------------------------------------------------------
-- 2. Устройство закрывает свои тревоги
-- ---------------------------------------------------------------------------
-- Тревогу о постороннем закрывает не расписание на сервере, а само
-- устройство: только оно знает, ушёл человек из кадра или нет.

drop policy if exists "alerts_device_resolve" on alerts;
create policy "alerts_device_resolve" on alerts
  for update using (farm_id = public.current_device_farm());

-- ---------------------------------------------------------------------------
-- 3. Охрана включается покамерно
-- ---------------------------------------------------------------------------
-- Не на всю ферму. Камера над кормовым столом ночью видит скотника на
-- утренней раздаче — там охрана не нужна и будет только мешать. Обзорная
-- на въезде — нужна.

alter table cameras add column if not exists security_enabled boolean not null default false;

comment on column cameras.security_enabled is
  'Следить ли за посторонними на этой камере. По умолчанию нет: '
  'снимать людей нельзя, пока на ферме не оформлены бумаги.';

-- ---------------------------------------------------------------------------
-- 4. Зона периметра
-- ---------------------------------------------------------------------------
-- Если на камере обведён периметр, тревога поднимается только когда
-- человек внутри него. Иначе будет срабатывать на дорогу за забором.

alter table zones drop constraint if exists zones_kind_check;
alter table zones add constraint zones_kind_check check (
  kind in ('feeder', 'water', 'gate', 'perimeter', 'other')
);

-- ---------------------------------------------------------------------------
-- 5. Настройки охраны
-- ---------------------------------------------------------------------------

alter table alert_settings
  add column if not exists guard_from time not null default '22:00',
  add column if not exists guard_to time not null default '06:00',
  -- Сколько секунд человек должен продержаться в кадре. Одиночное ложное
  -- срабатывание модели живёт один кадр, человек — секунды
  add column if not exists intruder_min_seconds integer not null default 5,
  -- Не поднимать вторую тревогу по той же камере сразу
  add column if not exists intruder_cooldown_minutes integer not null default 15,
  -- Через сколько минут без людей считать, что всё закончилось
  add column if not exists intruder_clear_minutes integer not null default 10;

comment on column alert_settings.guard_from is
  'Начало охранного окна в местном времени фермы. Если guard_from > guard_to, '
  'окно проходит через полночь — это обычный случай, а не ошибка.';

-- ---------------------------------------------------------------------------
-- 6. Срок хранения снимков с людьми
-- ---------------------------------------------------------------------------
-- Отдельной строкой и коротким по умолчанию: это персональные данные,
-- и держать их «на всякий случай» год нельзя.

alter table retention_policy
  add column if not exists intruder_snapshot_days integer not null default 30;

-- ---------------------------------------------------------------------------
-- 7. Уборка старых тревог о посторонних
-- ---------------------------------------------------------------------------
-- Сами тревоги живут по общему сроку событий, а вот снимки к ним надо
-- убирать раньше и отдельно.

create or replace function prune_intruder_snapshots()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_cleared integer;
begin
  update alerts a
  set snapshot_path = null
  from retention_policy r
  where r.farm_id = a.farm_id
    and a.kind = 'intruder'
    and a.snapshot_path is not null
    and a.opened_at < now() - make_interval(days => r.intruder_snapshot_days);

  get diagnostics v_cleared = row_count;
  return v_cleared;
end;
$$;

comment on function prune_intruder_snapshots() is
  'Стирает ссылки на снимки с людьми по истечении срока хранения. '
  'Сами файлы удаляются устройством по тому же сроку.';
