-- Хозяйство само размечает кормушки, поилки и периметр.
-- Применять ПОСЛЕ 0015_security_always.sql.
--
-- До сих пор зоны рисовал только администратор, то есть мы. Это неверно
-- по существу: кормушку переставили, загон перегородили, камеру повернули
-- на пять градусов — и зона показывает пустое место. Такое случается не
-- раз в год, а каждый месяц, и писать нам ради этого никто не станет.
--
-- Итог предсказуем: зона остаётся неверной, время у кормушки считается
-- по пустому углу, и клиент делает вывод, что система врёт. Причём
-- формально она не врёт — ей показали не туда.
--
-- Всё, что меняется при обычной работе хозяйства, должно настраиваться
-- самим хозяйством.

drop policy if exists "zones_owner_write" on zones;
create policy "zones_owner_write" on zones
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Старая политика администратора остаётся: она шире и покрывает
-- случай, когда админ правит чужую ферму.

-- ---------------------------------------------------------------------------
-- Защита от зон, которые ничего не значат
-- ---------------------------------------------------------------------------
-- Раньше проверка «не меньше трёх точек» жила только в интерфейсе. Когда
-- писать в таблицу мог один администратор, этого хватало. Теперь пишет
-- клиент, и проверку надо иметь в базе: иначе одна кривая форма или
-- случайный двойной клик оставят зону из двух точек, которая молча
-- не сработает никогда.

create or replace function zone_polygon_is_sane(polygon jsonb)
returns boolean
language plpgsql
immutable
as $$
declare
  v_point jsonb;
  v_count integer := 0;
begin
  if polygon is null or jsonb_typeof(polygon) <> 'array' then
    return false;
  end if;

  for v_point in select * from jsonb_array_elements(polygon) loop
    if jsonb_typeof(v_point) <> 'array' or jsonb_array_length(v_point) <> 2 then
      return false;
    end if;
    -- Координаты — доли кадра от 0 до 1. Пиксели тут были бы ошибкой:
    -- зона перестала бы работать при смене разрешения камеры
    if (v_point->>0)::numeric < 0 or (v_point->>0)::numeric > 1
       or (v_point->>1)::numeric < 0 or (v_point->>1)::numeric > 1 then
      return false;
    end if;
    v_count := v_count + 1;
  end loop;

  return v_count >= 3;
exception
  when others then
    -- Нечисловые координаты и прочий мусор
    return false;
end;
$$;

alter table zones drop constraint if exists zones_polygon_check;
alter table zones add constraint zones_polygon_check
  check (zone_polygon_is_sane(polygon));

comment on constraint zones_polygon_check on zones is
  'Не меньше трёх точек, координаты — доли кадра от 0 до 1. '
  'Проверка в базе, а не только в форме: зоны теперь рисует клиент.';
