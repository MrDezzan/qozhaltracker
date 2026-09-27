-- ---------------------------------------------------------------------------
-- Здоровье по камерам: данные для проверки и запись тревог
-- ---------------------------------------------------------------------------
-- Этап 4 плана docs/PLAN_POVEDENIE.md.
--
-- Решения здесь не принимаются. Они живут в cv_service/health.py чистыми
-- функциями — так каждое правило проверяется тестом, не поднимая ни
-- камеры, ни Postgres. База отдаёт строки и записывает итог.
--
-- Разделение не ради красоты. Пороги «мало» и «два дня подряд» уже
-- ловились мутационной проверкой на том, что их можно было менять как
-- угодно и ни один тест не падал. В SQL такую проверку не провести
-- вовсе.

-- ---------------------------------------------------------------------------
-- Сутки фермы
-- ---------------------------------------------------------------------------
-- Сервер живёт по UTC. Без приведения к времени фермы вечерняя
-- активность уезжает в следующие сутки, и «вчера» у половины стада
-- окажется разным.

create or replace function farm_timezone(target_farm_id uuid)
returns text
language sql
stable
set search_path = public
as $$
  select coalesce(timezone, 'UTC') from farms where id = target_farm_id
$$;

-- ---------------------------------------------------------------------------
-- Сколько часов камера была жива
-- ---------------------------------------------------------------------------
-- Живость считается по РАЗНЫМ часам, а не по числу событий. Камера,
-- выдавшая тысячу событий за один час и молчавшая остальные двадцать
-- три, работала один час.
--
-- Сетка «камера × день» строится полностью: камера, не приславшая
-- ничего, должна дать ноль часов, а не отсутствующую строку. Отсутствие
-- строки где-нибудь ниже прочтётся как «данных нет» и промолчит — а
-- умершая камера это ровно то, о чём молчать нельзя.

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
      (now() at time zone (select name from tz))::date - (days - 1),
      (now() at time zone (select name from tz))::date,
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

-- ---------------------------------------------------------------------------
-- Сутки животных
-- ---------------------------------------------------------------------------
-- Тоже полной сеткой, и по той же причине, только цена ошибки выше.
-- Животное, которого сутки не видели, не имеет строки в activity_daily.
-- Отдать «нет строки» значит промолчать ровно о том, ради чего всё
-- затевалось: пропавшая корова — самое срочное, что система может
-- заметить.

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
        where e.payload->>'zone_kind' = 'waterer'
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
    coalesce(z.water_visits, 0)
  from grid g
  left join activity_daily ad
    on ad.animal_id = g.animal_id and ad.day = g.day
  left join zones_by_day z
    on z.animal_id = g.animal_id and z.day = g.day
$$;

-- Сколько у животного эталонов: по этому решают, можно ли вообще судить
-- о его поведении. Мало эталонов — его нули это нули УЗНАВАНИЯ
create or replace function health_animals(target_farm_id uuid)
returns table (animal_id uuid, label text, embeddings integer)
language sql
stable
set search_path = public
as $$
  select
    a.id,
    a.label,
    (select count(*) from animal_embeddings e where e.animal_id = a.id)::integer
  from animals a
  where a.farm_id = target_farm_id
$$;

-- ---------------------------------------------------------------------------
-- Запись итога
-- ---------------------------------------------------------------------------
-- Тревоги по здоровью и только они. Список видов перечислен явно, и это
-- обязательно: закрытие устроено как «чего нет в новом наборе, того
-- больше нет», и без ограничения по видам проверка здоровья закрыла бы
-- тревогу о постороннем на территории.

create or replace function health_alert_kinds()
returns text[]
language sql
immutable
as $$
  select array[
    'low_activity', 'low_feeding', 'low_both',
    'not_seen', 'no_water', 'heat', 'herd_low'
  ]
$$;

create or replace function apply_health_findings(
  target_farm_id uuid,
  findings jsonb
)
returns table (opened integer, resolved integer)
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_opened integer := 0;
  v_resolved integer := 0;
  v_herd integer := 0;
begin
  create temp table incoming (
    animal_id uuid,
    kind text,
    severity text,
    title text,
    detail jsonb
  ) on commit drop;

  insert into incoming (animal_id, kind, severity, title, detail)
  select
    nullif(one->>'animal_id', '')::uuid,
    one->>'kind',
    one->>'severity',
    one->>'title',
    jsonb_build_object(
      'text', one->>'detail',
      'value', (one->>'value')::double precision,
      'baseline', (one->>'baseline')::double precision,
      'days_in_row', (one->>'days_in_row')::integer
    )
  from jsonb_array_elements(coalesce(findings, '[]'::jsonb)) as one
  where one->>'kind' = any (health_alert_kinds());

  -- --- новые ---
  -- Уникальный указатель по «ферма + вид + предмет» не даёт наплодить
  -- одинаковых. На тревоге о стаде предмета нет, и NULL в указателе
  -- считается отличным от NULL — поэтому её проверяем отдельно
  with fresh as (
    insert into alerts (farm_id, animal_id, kind, severity, title, detail)
    select target_farm_id, i.animal_id, i.kind, i.severity, i.title, i.detail
    from incoming i
    where i.animal_id is not null
    on conflict do nothing
    returning 1
  )
  select count(*) into v_opened from fresh;

  insert into alerts (farm_id, animal_id, kind, severity, title, detail)
  select target_farm_id, null, i.kind, i.severity, i.title, i.detail
  from incoming i
  where i.animal_id is null
    and not exists (
      select 1 from alerts a
      where a.farm_id = target_farm_id
        and a.kind = i.kind
        and a.subject_id is null
        and a.resolved_at is null
    );

  get diagnostics v_herd = row_count;
  v_opened := v_opened + v_herd;

  -- --- вернувшееся к норме закрываем само ---
  with closed as (
    update alerts a
       set resolved_at = now()
     where a.farm_id = target_farm_id
       and a.resolved_at is null
       and a.kind = any (health_alert_kinds())
       and not exists (
         select 1 from incoming i
         where i.kind = a.kind
           and i.animal_id is not distinct from a.animal_id
       )
    returning 1
  )
  select count(*) into v_resolved from closed;

  drop table incoming;
  return query select v_opened, v_resolved;
end;
$$;

grant execute on function health_camera_days(uuid, integer) to authenticated;
grant execute on function health_animal_days(uuid, integer) to authenticated;
grant execute on function health_animals(uuid) to authenticated;
grant execute on function apply_health_findings(uuid, jsonb) to authenticated;
grant execute on function farm_timezone(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Старая проверка по датчикам выключается
-- ---------------------------------------------------------------------------
-- Она читает `sensor_readings`, а датчиков в продукте больше нет:
-- их цена росла с каждой головой, а камеры уже стоят. Находить она
-- давно ничего не может.
--
-- Но закрывать продолжала бы исправно, и это не мелочь. Устроена она
-- так: «чего нет в моём наборе, того больше нет». Пока видов было два и
-- оба её, это работало. Теперь появились тревоги по камерам — и первый
-- же вызов из дашборда закрыл бы их все разом, молча и сразу после
-- открытия.
--
-- Можно было ограничить её своими видами. Но функция, которая ничего не
-- находит и не может найти, — это код, притворяющийся работающим.
-- Следующий человек полезет чинить «почему не срабатывают тревоги по
-- температуре» вместо того, чтобы узнать, что термометров нет.

create or replace function detect_farm_alerts_internal(target_farm_id uuid)
returns table (opened integer, resolved integer)
language plpgsql
security definer
set search_path = public
as $$
begin
  -- Тревоги по здоровью теперь поднимает устройство: оно считает
  -- поведение по камерам и зовёт apply_health_findings. Здесь не
  -- осталось ничего
  perform target_farm_id;
  return query select 0, 0;
end;
$$;

comment on function detect_farm_alerts_internal(uuid) is
  'Пустая с миграции 0041: датчиков нет, здоровье считается по камерам через apply_health_findings';
