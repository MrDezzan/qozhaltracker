-- ---------------------------------------------------------------------------
-- Сколько раз животное подходило к корму, и аналитика по одному животному
-- ---------------------------------------------------------------------------
-- Применять ПОСЛЕ 0042_training_frames.sql.
--
-- Здесь три вещи: исправление тихой ошибки, новый счётчик и функция для
-- страницы животного.

-- ---------------------------------------------------------------------------
-- 1. ОШИБКА: поилка не считалась никогда
-- ---------------------------------------------------------------------------
-- В 0041 счёт визитов к поилке шёл по `zone_kind = 'waterer'`. Но виды
-- зон заданы ограничением в 0004: 'feeder', 'water', 'gate', 'other'.
-- Значения 'waterer' в базе не бывает.
--
-- Значит `water_visits` всегда возвращал ноль, а тревога «нет воды» не
-- могла сработать ни разу. Ошибка тихая: функция отрабатывает, число
-- есть, оно просто всегда нулевое.
--
-- Ниже функция переписана целиком с правильным видом зоны.

-- ---------------------------------------------------------------------------
-- 2. Новый счётчик: приёмов пищи за сутки
-- ---------------------------------------------------------------------------
-- Раньше по корму было только ВРЕМЯ (`feeder_seconds`). Для владельца
-- понятнее число: «сегодня подходил к корму два раза вместо обычных
-- шести». Время и число ловят разное: животное может простоять у корма
-- долго, но подойти один раз, — и наоборот.
--
-- Один подход = один визит в зону. Пауза внутри визита 60 секунд
-- (GRACE_BY_KIND в zones.py), поэтому поднятая на жвачку голова визит не
-- разрывает и лишних «приёмов пищи» не создаёт.

drop function if exists health_animal_days(uuid, integer);

create function health_animal_days(
  target_farm_id uuid,
  days integer default 14
)
returns table (
  animal_id uuid,
  day date,
  meters double precision,
  seconds_visible double precision,
  feeder_seconds double precision,
  feeder_visits integer,
  water_visits integer
)
language sql
stable
set search_path = public
as $$
  with tz as (
    select farm_timezone(target_farm_id) as name
  ),
  grid as (
    -- Полная сетка «животное x день»: животное, которого не видели,
    -- должно дать нули, а не отсутствующую строку. Отсутствие строки
    -- прочтётся как «данных нет» и промолчит — а пропавшее животное это
    -- ровно то, о чём молчать нельзя
    select a.id as animal_id, d::date as day
    from animals a
    cross join generate_series(
      (now() at time zone (select name from tz))::date - (days - 1),
      (now() at time zone (select name from tz))::date,
      interval '1 day'
    ) as d
    where a.farm_id = target_farm_id
  ),
  zones_by_day as (
    select
      e.animal_id,
      (e.occurred_at at time zone (select name from tz))::date as day,
      sum(
        case when e.payload->>'zone_kind' = 'feeder'
        then coalesce((e.payload->>'duration_s')::double precision, 0)
        else 0 end
      ) as feeder_seconds,
      count(*) filter (
        where e.payload->>'zone_kind' = 'feeder'
      )::integer as feeder_visits,
      count(*) filter (
        where e.payload->>'zone_kind' = 'water'
      )::integer as water_visits
    from events e
    where e.farm_id = target_farm_id
      and e.event_type = 'zone_exit'
      and e.animal_id is not null
      and e.payload ? 'zone_kind'
      and e.occurred_at >= now() - make_interval(days => days + 1)
    group by 1, 2
  )
  select
    g.animal_id,
    g.day,
    coalesce(ad.meters, 0)::double precision,
    coalesce(ad.seconds_visible, 0)::double precision,
    coalesce(z.feeder_seconds, 0)::double precision,
    coalesce(z.feeder_visits, 0),
    coalesce(z.water_visits, 0)
  from grid g
  left join activity_daily ad
    on ad.animal_id = g.animal_id and ad.day = g.day
  left join zones_by_day z
    on z.animal_id = g.animal_id and z.day = g.day
$$;

grant execute on function health_animal_days(uuid, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Вид тревоги: мало подходов к корму
-- ---------------------------------------------------------------------------

create or replace function health_alert_kinds()
returns text[]
language sql
immutable
as $$
  select array[
    'not_seen', 'low_both', 'low_activity', 'low_feeding',
    'few_meals', 'no_water', 'heat'
  ]
$$;

-- ---------------------------------------------------------------------------
-- 4. Аналитика по одному животному
-- ---------------------------------------------------------------------------
-- Для страницы животного в дашборде. День за днём: сколько ел, сколько
-- раз подходил, сколько прошёл, какого размера силуэт.
--
-- Размер даётся в пикселях, и это не недоделка. Вес в килограммах
-- требует формулы, подобранной по контрольным взвешиваниям; пока их нет,
-- формулы нет тоже. А площадь силуэта копится с первого дня, и
-- ОТНОСИТЕЛЬНЫЙ рост по ней виден: «+8% за месяц» — честное число,
-- полученное без весов.
--
-- Медиана за день, а не среднее: за сутки животное попадает в кадр
-- десятки раз, и один кадр с задранной головой или обрезанным краем
-- сдвинул бы среднее заметно.

create or replace function animal_daily(
  target_animal_id uuid,
  days integer default 30
)
returns table (
  day date,
  meters double precision,
  seconds_visible double precision,
  feeder_seconds double precision,
  feeder_visits integer,
  water_visits integer,
  area_px double precision,
  length_cm double precision,
  width_cm double precision,
  measurements integer
)
language sql
stable
set search_path = public
as $$
  with animal as (
    select id, farm_id from animals where id = target_animal_id
  ),
  tz as (
    select farm_timezone((select farm_id from animal)) as name
  ),
  grid as (
    select d::date as day
    from generate_series(
      (now() at time zone (select name from tz))::date - (days - 1),
      (now() at time zone (select name from tz))::date,
      interval '1 day'
    ) as d
  ),
  zones_by_day as (
    select
      (e.occurred_at at time zone (select name from tz))::date as day,
      sum(
        case when e.payload->>'zone_kind' = 'feeder'
        then coalesce((e.payload->>'duration_s')::double precision, 0)
        else 0 end
      ) as feeder_seconds,
      count(*) filter (where e.payload->>'zone_kind' = 'feeder')::integer as feeder_visits,
      count(*) filter (where e.payload->>'zone_kind' = 'water')::integer as water_visits
    from events e
    where e.animal_id = target_animal_id
      and e.event_type = 'zone_exit'
      and e.payload ? 'zone_kind'
      and e.occurred_at >= now() - make_interval(days => days + 1)
    group by 1
  ),
  size_by_day as (
    select
      (m.measured_at at time zone (select name from tz))::date as day,
      percentile_cont(0.5) within group (order by m.area_px) as area_px,
      percentile_cont(0.5) within group (order by m.length_cm) as length_cm,
      percentile_cont(0.5) within group (order by m.width_cm) as width_cm,
      count(*)::integer as measurements
    from body_measurements m
    where m.animal_id = target_animal_id
      and m.measured_at >= now() - make_interval(days => days + 1)
    group by 1
  )
  select
    g.day,
    coalesce(ad.meters, 0)::double precision,
    coalesce(ad.seconds_visible, 0)::double precision,
    coalesce(z.feeder_seconds, 0)::double precision,
    coalesce(z.feeder_visits, 0),
    coalesce(z.water_visits, 0),
    s.area_px,
    s.length_cm,
    s.width_cm,
    coalesce(s.measurements, 0)
  from grid g
  left join activity_daily ad
    on ad.animal_id = target_animal_id and ad.day = g.day
  left join zones_by_day z on z.day = g.day
  left join size_by_day s on s.day = g.day
  order by g.day
$$;

grant execute on function animal_daily(uuid, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 5. Неделя к неделе
-- ---------------------------------------------------------------------------
-- Одно число, ради которого владелец открывает страницу: стало лучше или
-- хуже. Сравниваются последние семь дней с предыдущими семью.
--
-- Нули в размере не считаются: день без единого промера — это не
-- «размер ноль», а «не измеряли». Поэтому размер берётся только по дням,
-- где промеры были, и если их не было вовсе, возвращается null.

create or replace function animal_week_change(target_animal_id uuid)
returns table (
  feeder_visits_now double precision,
  feeder_visits_before double precision,
  feeder_seconds_now double precision,
  feeder_seconds_before double precision,
  meters_now double precision,
  meters_before double precision,
  area_now double precision,
  area_before double precision,
  area_change_pct double precision,
  days_with_size integer
)
language sql
stable
set search_path = public
as $$
  with rows as (
    select *, row_number() over (order by day desc) as back
    from animal_daily(target_animal_id, 14)
  ),
  now7 as (select * from rows where back <= 7),
  prev7 as (select * from rows where back between 8 and 14),
  size_now as (select avg(area_px) as v, count(*)::integer as n
               from now7 where area_px is not null),
  size_prev as (select avg(area_px) as v from prev7 where area_px is not null)
  select
    (select avg(feeder_visits) from now7),
    (select avg(feeder_visits) from prev7),
    (select avg(feeder_seconds) from now7),
    (select avg(feeder_seconds) from prev7),
    (select avg(meters) from now7),
    (select avg(meters) from prev7),
    (select v from size_now),
    (select v from size_prev),
    case
      when (select v from size_prev) is null then null
      when (select v from size_prev) <= 0 then null
      when (select v from size_now) is null then null
      else round(
        (((select v from size_now) / (select v from size_prev)) - 1) * 100
      )::double precision
    end,
    coalesce((select n from size_now), 0)
$$;

grant execute on function animal_week_change(uuid) to authenticated;

notify pgrst, 'reload schema';
