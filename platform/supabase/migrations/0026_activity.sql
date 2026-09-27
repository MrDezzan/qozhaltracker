-- ---------------------------------------------------------------------------
-- Активность животного по камерам
-- ---------------------------------------------------------------------------
-- То, ради чего вешали носимые датчики: сколько животное прошло за сутки
-- и как часто подходило к корму. Датчиков больше нет — их цена росла с
-- каждой головой, а камеры уже стоят.
--
-- Что здесь считается честным, а что нет.
--
-- Пройденный путь по камере — это НЕ весь путь животного. Камера видит
-- кусок загона; то, что животное прошло вне кадра, не учтено. Поэтому
-- сравнивать метры между фермами или даже между камерами бессмысленно.
-- Осмысленно сравнивать животное с самим собой вчера и с соседями по
-- тому же загону сегодня — их видит та же камера в те же часы.
--
-- Именно так это и показывается: не «прошла 840 метров», а «на треть
-- меньше своей обычной». Абсолютное число без этой оговорки читалось бы
-- как измерение, каким оно не является.

create table if not exists activity_daily (
  farm_id uuid not null references farms(id) on delete cascade,
  animal_id uuid not null references animals(id) on delete cascade,
  day date not null,
  -- Метры получаются из пикселей через калибровку камеры. Без неё
  -- активность не считается вовсе: пиксель ничего не значит, а число,
  -- посчитанное «в пикселях», человек всё равно прочтёт как метры
  meters double precision not null default 0,
  -- Сколько отрезков сложилось в этот путь. По нему видно, много ли
  -- животное было в кадре: сто метров за пять отрезков и за пятьсот —
  -- разные по достоверности числа
  samples integer not null default 0,
  -- Сколько секунд животное было видно. Без этого метры не с чем
  -- соотнести: животное, попавшее в кадр на минуту, «прошло мало»
  seconds_visible double precision not null default 0,
  updated_at timestamptz not null default now(),
  primary key (animal_id, day)
);

create index if not exists activity_daily_farm_idx
  on activity_daily (farm_id, day desc);

alter table activity_daily enable row level security;

drop policy if exists "activity_daily_read" on activity_daily;
create policy "activity_daily_read" on activity_daily
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  );

drop policy if exists "activity_daily_write" on activity_daily;
create policy "activity_daily_write" on activity_daily
  for all using (
    farm_id = public.current_device_farm() or public.is_admin()
  )
  with check (
    farm_id = public.current_device_farm() or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- Накопление
-- ---------------------------------------------------------------------------
-- Устройство шлёт куски пути, а не итог за сутки: трек животного
-- заканчивается, когда оно вышло из кадра, и таких кусков за день
-- десятки. Сложение идёт в базе, чтобы устройство не держало сутки
-- состояния в памяти и не теряло его при перезапуске.

create or replace function add_activity(
  target_animal_id uuid,
  add_meters double precision,
  add_samples integer,
  add_seconds double precision,
  target_day date default null
)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_farm uuid;
  v_day date;
begin
  select farm_id into v_farm from animals where id = target_animal_id;
  if v_farm is null then
    return;
  end if;

  -- День берётся по времени фермы, а не сервера: сервер живёт по UTC, и
  -- вечерняя активность уезжала бы в следующие сутки
  v_day := coalesce(
    target_day,
    (now() at time zone coalesce(
      (select timezone from farms where id = v_farm), 'UTC'
    ))::date
  );

  insert into activity_daily (farm_id, animal_id, day, meters, samples, seconds_visible)
  values (v_farm, target_animal_id, v_day, add_meters, add_samples, add_seconds)
  on conflict (animal_id, day) do update
    set meters = activity_daily.meters + excluded.meters,
        samples = activity_daily.samples + excluded.samples,
        seconds_visible = activity_daily.seconds_visible + excluded.seconds_visible,
        updated_at = now();
end;
$$;

-- ---------------------------------------------------------------------------
-- Активность с собственной нормой животного
-- ---------------------------------------------------------------------------
-- Норма считается по предыдущим дням этого же животного, сегодняшний
-- день в неё не входит: иначе показатель сравнивался бы сам с собой и
-- отклонение всегда выходило бы меньше настоящего.
--
-- Медиана, а не среднее: один день, когда животное простояло у камеры
-- весь день, сдвинул бы среднее так, что все остальные дни стали бы
-- «ниже нормы».

create or replace function animal_activity(
  target_farm_id uuid,
  baseline_days integer default 14
)
returns table (
  animal_id uuid,
  label text,
  day date,
  meters double precision,
  seconds_visible double precision,
  baseline_meters double precision,
  ratio_to_own double precision,
  ratio_to_herd double precision,
  days_known integer
)
language sql
stable
set search_path = public
as $$
  with latest as (
    select distinct on (a.animal_id)
      a.animal_id, a.day, a.meters, a.seconds_visible
    from activity_daily a
    where a.farm_id = target_farm_id
    order by a.animal_id, a.day desc
  ),
  baseline as (
    select
      a.animal_id,
      percentile_cont(0.5) within group (order by a.meters) as median_meters,
      count(*)::integer as days_known
    from activity_daily a
    join latest l on l.animal_id = a.animal_id
    where a.farm_id = target_farm_id
      and a.day < l.day
      and a.day >= l.day - baseline_days
    group by a.animal_id
  ),
  herd as (
    -- Стадо за тот же день: общая просадка от жары или перегона не
    -- должна выглядеть как болезнь у каждого животного по очереди
    select l.day, percentile_cont(0.5) within group (order by l.meters) as median_meters
    from latest l
    group by l.day
  )
  select
    l.animal_id,
    an.label,
    l.day,
    round(l.meters::numeric, 1)::double precision,
    l.seconds_visible,
    round(b.median_meters::numeric, 1)::double precision,
    case when b.median_meters > 0 then l.meters / b.median_meters end,
    case when h.median_meters > 0 then l.meters / h.median_meters end,
    coalesce(b.days_known, 0)
  from latest l
  join animals an on an.id = l.animal_id
  left join baseline b on b.animal_id = l.animal_id
  left join herd h on h.day = l.day
  order by an.label
$$;

-- История по одному животному — для его карточки
create or replace function animal_activity_history(
  target_animal_id uuid,
  days integer default 30
)
returns table (
  day date,
  meters double precision,
  seconds_visible double precision
)
language sql
stable
set search_path = public
as $$
  select a.day, a.meters, a.seconds_visible
  from activity_daily a
  where a.animal_id = target_animal_id
    and a.day >= current_date - days
  order by a.day
$$;

-- ---------------------------------------------------------------------------
-- Подходы к корму и воде по каждому животному
-- ---------------------------------------------------------------------------
-- Визиты в зоны уже пишутся событиями. Здесь их только раскладывают по
-- животным: до сих пор они считались в целом по стаду, и «стадо ест
-- нормально» ничего не говорило о конкретной корове.

create or replace function animal_zone_visits(
  target_farm_id uuid,
  days integer default 1
)
returns table (
  animal_id uuid,
  zone_kind text,
  visits integer,
  seconds double precision
)
language sql
stable
set search_path = public
as $$
  select
    e.animal_id,
    coalesce(e.payload->>'zone_kind', 'unknown') as zone_kind,
    count(*)::integer as visits,
    sum(coalesce((e.payload->>'duration_s')::double precision, 0)) as seconds
  from events e
  where e.farm_id = target_farm_id
    and e.event_type = 'zone_exit'
    and e.animal_id is not null
    and e.payload ? 'zone_kind'
    and e.occurred_at >= now() - make_interval(days => days)
  group by e.animal_id, coalesce(e.payload->>'zone_kind', 'unknown')
$$;

revoke all on function add_activity(uuid, double precision, integer, double precision, date) from public;
revoke all on function animal_activity(uuid, integer) from public;
revoke all on function animal_activity_history(uuid, integer) from public;
revoke all on function animal_zone_visits(uuid, integer) from public;

grant execute on function add_activity(uuid, double precision, integer, double precision, date) to authenticated;
grant execute on function animal_activity(uuid, integer) to authenticated;
grant execute on function animal_activity_history(uuid, integer) to authenticated;
grant execute on function animal_zone_visits(uuid, integer) to authenticated;
