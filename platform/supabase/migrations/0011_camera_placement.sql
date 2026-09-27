-- Расположение камеры и настройки фермы через интерфейс, а не через SQL.
--
-- Раньше «камера смотрит сверху» было галочкой, а часовой пояс, пороги тревог
-- и сроки хранения правились запросами в базу. Всё, что настраивает клиент,
-- должно настраиваться кнопками: до базы он не дойдёт, а значит эти настройки
-- останутся в значениях по умолчанию навсегда.

-- ---------------------------------------------------------------------------
-- 1. Расположение камеры
-- ---------------------------------------------------------------------------
-- Флага «сверху / не сверху» мало: от того, как повешена камера, зависит,
-- что с неё вообще можно снять. Сверху — обмер силуэта и честный подсчёт.
-- Сбоку — зоны и распознавание особей. Обзорная — только охрана периметра.

alter table cameras add column if not exists placement text;

-- Перенос из старого флага — только если он ещё есть.
--
-- Без этой проверки миграцию нельзя выполнить второй раз: первый прогон
-- удаляет колонку `overhead` в конце этого же файла, и повторный падает
-- на «column overhead does not exist». Выполнять миграции повторно
-- приходится чаще, чем хочется: оборвалась сессия, применили не к той
-- базе, разворачиваем стенд заново.
do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'cameras'
      and column_name = 'overhead'
  ) then
    update cameras
    set placement = case
      when coalesce(overhead, false) then 'overhead'
      else 'side'
    end
    where placement is null;
  end if;
end
$$;

-- Камеры, заведённые уже без старого флага
update cameras set placement = 'side' where placement is null;

alter table cameras alter column placement set default 'side';
alter table cameras alter column placement set not null;

alter table cameras drop constraint if exists cameras_placement_check;
alter table cameras add constraint cameras_placement_check
  check (placement in ('overhead', 'side', 'wide'));

-- Старый флаг больше не нужен: он выводится из расположения
alter table cameras drop column if exists overhead;

comment on column cameras.placement is
  'overhead — над животными, снимается силуэт для веса; '
  'side — сбоку, зоны и распознавание особей; '
  'wide — общий обзор территории';

-- ---------------------------------------------------------------------------
-- 2. Владелец правит свои камеры сам
-- ---------------------------------------------------------------------------
-- Раньше любое изменение камеры требовало администратора. Но «перевесили
-- камеру, поменяйте расположение» — не та задача, ради которой стоит писать
-- поставщику. Заводит и удаляет камеры по-прежнему администратор.

drop policy if exists "cameras_owner_update" on cameras;
create policy "cameras_owner_update" on cameras
  for update using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- 3. Владелец правит часовой пояс своей фермы
-- ---------------------------------------------------------------------------
-- Ферма целиком остаётся под администратором: переименовать или переназначить
-- владельца клиент не может. Но пояс — это его местное время, и знает его он.

create or replace function set_farm_timezone(target_farm_id uuid, new_timezone text)
returns text
language plpgsql
security definer
set search_path = public
as $$
begin
  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = target_farm_id and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой ферме';
  end if;

  -- Проверка на существование пояса: иначе опечатка в названии сломала бы
  -- все графики по часам, и виноватой выглядела бы система
  perform now() at time zone new_timezone;

  update farms set timezone = new_timezone where id = target_farm_id;
  return new_timezone;
end;
$$;

grant execute on function set_farm_timezone(uuid, text) to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Сроки хранения — владельцу на чтение и правку
-- ---------------------------------------------------------------------------
-- Раньше писать туда мог только администратор, а решение «держать кадры
-- месяц или три» принимает хозяйство.

drop policy if exists "retention_admin_write" on retention_policy;
drop policy if exists "retention_write" on retention_policy;
create policy "retention_write" on retention_policy
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Строка настроек создаётся при первом обращении, чтобы интерфейсу
-- не приходилось различать «не настроено» и «настроено по умолчанию»
create or replace function ensure_retention_policy(target_farm_id uuid)
returns retention_policy
language plpgsql
security invoker
set search_path = public
as $$
declare
  v retention_policy;
begin
  insert into retention_policy (farm_id)
  values (target_farm_id)
  on conflict (farm_id) do nothing;

  select * into v from retention_policy where farm_id = target_farm_id;
  return v;
end;
$$;

grant execute on function ensure_retention_policy(uuid) to authenticated;

create or replace function ensure_alert_settings(target_farm_id uuid)
returns alert_settings
language plpgsql
security invoker
set search_path = public
as $$
declare
  v alert_settings;
begin
  insert into alert_settings (farm_id)
  values (target_farm_id)
  on conflict (farm_id) do nothing;

  select * into v from alert_settings where farm_id = target_farm_id;
  return v;
end;
$$;

grant execute on function ensure_alert_settings(uuid) to authenticated;
