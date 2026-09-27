-- 0044: судить только по кончившимся суткам
--
-- Обе сетки дней доходили до СЕГОДНЯШНЕЙ даты включительно, а health.py
-- берёт последний день сетки как тот, о котором судит. То есть система
-- сравнивала неполные текущие сутки с медианой целых.
--
-- Как это выглядело на ферме. Норма коровы 600 м и 50 минут у корма.
-- К часу дня камера набирает свои двенадцать часов, сутки объявляются
-- годными, а корова прошла 330 м и постояла у корма 28 минут — потому
-- что день ещё идёт. Ответ системы: «мало ест и мало двигается, два
-- признака сразу, это повод позвать ветврача». Каждый день, на всём
-- стаде, до полуночи.
--
-- Хуже того, на стаде личные тревоги схлопывались в одну herd_low, а
-- run_check при herd_low не поднимает личных тревог вовсе. То есть
-- ежедневная ложная тревога заодно ослепляла систему до полуночи.
--
-- Правка: верхняя граница сетки — ВЧЕРА. Нижняя сдвинута на день, чтобы
-- окно осталось прежней длины: days суток, кончая вчерашними.
--
-- Почему в базе, а не в питоне. Часовой пояс фермы знает только база
-- (farm_timezone). Мини-ПК в коровнике может стоять с любым временем и
-- без синхронизации, и вычислять «сегодня» по его часам — значит менять
-- одну ошибку на другую, менее заметную.
--
-- Повторный запуск безопасен: обе функции переопределяются целиком.

create or replace function health_camera_days(
  target_farm_id uuid,
  days integer default 14
)
returns table (
  camera_id uuid,
  day date,
  alive_hours double precision,
  has_feeder boolean
)
language sql
stable
set search_path = public
as $$
  with tz as (
    select farm_timezone(target_farm_id) as name
  ),
  grid as (
    select c.id as camera_id, d::date as day
    from cameras c
    cross join generate_series(
      (now() at time zone (select name from tz))::date - days,
      (now() at time zone (select name from tz))::date - 1,
      interval '1 day'
    ) as d
    where c.farm_id = target_farm_id
  ),
  lively as (
    select
      e.camera_id,
      (e.occurred_at at time zone (select name from tz))::date as day,
      count(distinct date_trunc(
        'hour', e.occurred_at at time zone (select name from tz)
      )) as hours
    from events e
    where e.farm_id = target_farm_id
      and e.occurred_at >= now() - make_interval(days => days + 1)
    group by 1, 2
  )
  select
    g.camera_id,
    g.day,
    coalesce(l.hours, 0)::double precision,
    exists (
      select 1 from zones z
      where z.camera_id = g.camera_id and z.kind = 'feeder'
    )
  from grid g
  left join lively l on l.camera_id = g.camera_id and l.day = g.day
$$;

create or replace function health_animal_days(
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
      (now() at time zone (select name from tz))::date - days,
      (now() at time zone (select name from tz))::date - 1,
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

grant execute on function health_camera_days(uuid, integer) to authenticated;
grant execute on function health_animal_days(uuid, integer) to authenticated;
