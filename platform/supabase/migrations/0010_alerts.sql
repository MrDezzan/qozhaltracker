-- Тревоги, отклонения по датчикам и состояние парка трекеров.
--
-- Главная мысль всей этой миграции: пороги «температура выше 39,3» и
-- «шагов меньше тысячи» на живой ферме бесполезны. У каждого животного своя
-- норма, а стадо целиком реагирует на погоду, смену корма и перегон. Поэтому
-- отклонение считается дважды: относительно собственной нормы животного и
-- относительно того, как в тот же момент вело себя всё стадо.
--
-- Если шаги упали у всех — это буран, а не болезнь, и будить хозяина ночью
-- не нужно. Если упали у одного при спокойном стаде — вот это тревога.

-- ---------------------------------------------------------------------------
-- 1. Настройки чувствительности
-- ---------------------------------------------------------------------------
-- Вынесены в таблицу, а не зашиты: на откорме и на молочном стаде нормы
-- разные, и подкручивать их придётся по месту.

create table if not exists alert_settings (
  farm_id uuid primary key references farms(id) on delete cascade,
  -- Во сколько раз активность должна просесть относительно стада,
  -- чтобы это считалось тревогой. 0.6 — упало почти вдвое сильнее прочих
  activity_drop_ratio real not null default 0.6,
  -- Всплеск активности — признак охоты, а не болезни
  activity_spike_ratio real not null default 1.8,
  -- Отклонение температуры от собственной нормы животного, °C
  temp_deviation_c real not null default 0.7,
  temp_absolute_max real not null default 39.5,
  temp_absolute_min real not null default 37.5,
  -- Через сколько часов молчания датчик считается вышедшим из строя
  sensor_silence_hours integer not null default 6,
  low_battery_percent smallint not null default 15,
  -- Сколько дней истории нужно, чтобы говорить о «норме» животного
  baseline_min_days integer not null default 3
);

alter table alert_settings enable row level security;

drop policy if exists "alert_settings_read" on alert_settings;
create policy "alert_settings_read" on alert_settings
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "alert_settings_write" on alert_settings;
create policy "alert_settings_write" on alert_settings
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

create or replace function farm_alert_settings(target_farm_id uuid)
returns alert_settings
language plpgsql
stable
set search_path = public
as $$
declare
  v alert_settings;
begin
  select * into v from alert_settings where farm_id = target_farm_id;
  if not found then
    -- Ферма без своих настроек работает на значениях по умолчанию
    v.farm_id := target_farm_id;
    v.activity_drop_ratio := 0.6;
    v.activity_spike_ratio := 1.8;
    v.temp_deviation_c := 0.7;
    v.temp_absolute_max := 39.5;
    v.temp_absolute_min := 37.5;
    v.sensor_silence_hours := 6;
    v.low_battery_percent := 15;
    v.baseline_min_days := 3;
  end if;
  return v;
end;
$$;

-- ---------------------------------------------------------------------------
-- 2. Тревоги
-- ---------------------------------------------------------------------------

create table if not exists alerts (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  animal_id uuid references animals(id) on delete cascade,
  sensor_id uuid references sensors(id) on delete cascade,
  camera_id uuid references cameras(id) on delete cascade,
  kind text not null,
  severity text not null check (severity in ('info', 'warning', 'danger')),
  title text not null,
  detail jsonb not null default '{}'::jsonb,
  opened_at timestamptz not null default now(),
  -- Закрывается само, когда показатель вернулся к норме
  resolved_at timestamptz,
  -- Отмечается хозяином: «видел, разбираюсь»
  acknowledged_at timestamptz,
  acknowledged_by uuid references auth.users(id) on delete set null,
  -- К кому относится тревога: животное, датчик или камера
  subject_id uuid generated always as (
    coalesce(animal_id, sensor_id, camera_id)
  ) stored
);

-- Одна открытая тревога на пару «предмет + вид». Иначе датчик, молчащий
-- третьи сутки, за это время наплодил бы сотни одинаковых записей.
create unique index if not exists alerts_open_unique
  on alerts(farm_id, kind, subject_id)
  where resolved_at is null;

create index if not exists alerts_farm_open_idx
  on alerts(farm_id, opened_at desc)
  where resolved_at is null;
create index if not exists alerts_farm_history_idx on alerts(farm_id, opened_at desc);

alter table alerts enable row level security;

drop policy if exists "alerts_read" on alerts;
create policy "alerts_read" on alerts
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "alerts_ack" on alerts;
create policy "alerts_ack" on alerts
  for update using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

drop policy if exists "alerts_device_insert" on alerts;
create policy "alerts_device_insert" on alerts
  for insert with check (
    farm_id = public.current_device_farm() or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- 3. Норма животного и поведение стада
-- ---------------------------------------------------------------------------
-- Сравниваем последние 6 часов с тем же отрезком суток за предыдущие 7 дней.
-- Именно с тем же: активность подчинена суточному ритму, и сравнивать ночь
-- с днём — значит объявлять тревогу каждый вечер.

create or replace function animal_activity_windows(target_farm_id uuid)
returns table (
  animal_id uuid,
  steps_now double precision,
  steps_baseline double precision,
  activity_now double precision,
  activity_baseline double precision,
  temp_now double precision,
  temp_baseline double precision,
  baseline_days integer,
  readings_now integer
)
language sql
stable
set search_path = public
as $$
  with recent as (
    select
      r.animal_id,
      sum(r.steps)::double precision as steps_now,
      avg(r.activity_index)::double precision as activity_now,
      max(r.temperature_c)::double precision as temp_now,
      count(*)::integer as readings_now
    from sensor_readings r
    where r.farm_id = target_farm_id
      and r.animal_id is not null
      and r.measured_at > now() - interval '6 hours'
    group by r.animal_id
  ),
  -- Тот же отрезок суток в предыдущие дни, по каждому дню отдельно.
  -- Отсчёт идёт ровно сутками назад, а не по номерам часов: иначе окно,
  -- начавшееся вечером и кончившееся после полуночи, оказалось бы пустым.
  history as (
    select
      r.animal_id,
      d.n as day_offset,
      sum(r.steps)::double precision as steps,
      avg(r.activity_index)::double precision as activity,
      max(r.temperature_c)::double precision as temp
    from generate_series(1, 7) as d(n)
    join sensor_readings r
      on r.measured_at between now() - make_interval(days => d.n) - interval '6 hours'
                          and now() - make_interval(days => d.n)
    where r.farm_id = target_farm_id
      and r.animal_id is not null
    group by r.animal_id, d.n
  ),
  -- Медиана, а не среднее: один день с оборванным датчиком не должен
  -- утягивать норму вниз и порождать тревогу на ровном месте
  baseline as (
    select
      h.animal_id,
      percentile_cont(0.5) within group (order by h.steps) as steps_baseline,
      percentile_cont(0.5) within group (order by h.activity) as activity_baseline,
      percentile_cont(0.5) within group (order by h.temp) as temp_baseline,
      count(*)::integer as baseline_days
    from history h
    group by h.animal_id
  )
  select
    r.animal_id,
    r.steps_now,
    b.steps_baseline,
    r.activity_now,
    b.activity_baseline,
    r.temp_now,
    b.temp_baseline,
    coalesce(b.baseline_days, 0),
    r.readings_now
  from recent r
  left join baseline b on b.animal_id = r.animal_id
$$;

-- Как в целом ведёт себя стадо относительно своей нормы. Это и есть поправка
-- на погоду, перегон и смену корма: если просели все, поправка просядет вместе
-- с ними, и отдельные животные тревог не поднимут.
create or replace function herd_activity_ratio(target_farm_id uuid)
returns double precision
language sql
stable
set search_path = public
as $$
  select coalesce(
    percentile_cont(0.5) within group (
      order by w.steps_now / nullif(w.steps_baseline, 0)
    ),
    1.0
  )
  from animal_activity_windows(target_farm_id) w
  where w.steps_baseline > 0 and w.baseline_days >= 3
$$;

-- ---------------------------------------------------------------------------
-- 4. Поиск отклонений
-- ---------------------------------------------------------------------------

create or replace function detect_farm_alerts_internal(target_farm_id uuid)
returns table (opened integer, resolved integer)
language plpgsql
security definer
set search_path = public
as $$
declare
  s alert_settings;
  v_herd double precision;
  v_opened integer := 0;
  v_resolved integer := 0;
begin
  s := farm_alert_settings(target_farm_id);
  v_herd := greatest(herd_activity_ratio(target_farm_id), 0.2);

  create temp table current_alerts (
    animal_id uuid,
    sensor_id uuid,
    kind text,
    severity text,
    title text,
    detail jsonb
  ) on commit drop;

  -- --- отклонения по животным ---
  insert into current_alerts (animal_id, kind, severity, title, detail)
  select
    w.animal_id,
    case
      when w.temp_now >= s.temp_absolute_max
        or w.temp_now - w.temp_baseline >= s.temp_deviation_c then 'fever'
      when w.temp_now <= s.temp_absolute_min
        or w.temp_baseline - w.temp_now >= s.temp_deviation_c then 'hypothermia'
      when (w.steps_now / nullif(w.steps_baseline, 0)) / v_herd
             >= s.activity_spike_ratio then 'activity_spike'
      else 'activity_drop'
    end,
    case
      when w.temp_now >= s.temp_absolute_max then 'danger'
      when w.temp_now <= s.temp_absolute_min then 'danger'
      when (w.steps_now / nullif(w.steps_baseline, 0)) / v_herd < 0.4 then 'danger'
      else 'warning'
    end,
    a.label,
    jsonb_build_object(
      'steps_now', round(w.steps_now),
      'steps_baseline', round(w.steps_baseline),
      'ratio_to_herd', round(((w.steps_now / nullif(w.steps_baseline, 0)) / v_herd)::numeric, 2),
      'herd_ratio', round(v_herd::numeric, 2),
      'temp_now', round(w.temp_now::numeric, 1),
      'temp_baseline', round(w.temp_baseline::numeric, 1),
      'baseline_days', w.baseline_days
    )
  from animal_activity_windows(target_farm_id) w
  join animals a on a.id = w.animal_id
  where w.baseline_days >= s.baseline_min_days
    and w.readings_now >= 3
    and (
      -- температура вышла за собственную норму или за физиологические границы
      (w.temp_now is not null and w.temp_baseline is not null
        and abs(w.temp_now - w.temp_baseline) >= s.temp_deviation_c)
      or (w.temp_now is not null
        and (w.temp_now >= s.temp_absolute_max or w.temp_now <= s.temp_absolute_min))
      -- активность просела сильнее, чем у стада
      or (w.steps_baseline > 50
        and (w.steps_now / w.steps_baseline) / v_herd < s.activity_drop_ratio)
      -- или наоборот подскочила
      or (w.steps_baseline > 50
        and (w.steps_now / w.steps_baseline) / v_herd >= s.activity_spike_ratio)
    );

  -- --- состояние парка датчиков ---
  insert into current_alerts (sensor_id, animal_id, kind, severity, title, detail)
  select
    sn.id,
    sn.animal_id,
    'sensor_offline',
    'danger',
    sn.serial,
    jsonb_build_object(
      'last_seen_at', sn.last_seen_at,
      'silence_hours', s.sensor_silence_hours
    )
  from sensors sn
  where sn.farm_id = target_farm_id
    and sn.attached_at is not null
    and (
      sn.last_seen_at is null
      or sn.last_seen_at < now() - make_interval(hours => s.sensor_silence_hours)
    );

  insert into current_alerts (sensor_id, animal_id, kind, severity, title, detail)
  select
    sn.id, sn.animal_id, 'low_battery', 'warning', sn.serial,
    jsonb_build_object('battery_percent', sn.battery_percent)
  from sensors sn
  where sn.farm_id = target_farm_id
    and sn.battery_percent is not null
    and sn.battery_percent <= s.low_battery_percent;

  insert into current_alerts (sensor_id, animal_id, kind, severity, title, detail)
  select distinct on (r.sensor_id)
    r.sensor_id, r.animal_id, 'tamper', 'danger', sn.serial,
    jsonb_build_object('measured_at', r.measured_at)
  from sensor_readings r
  join sensors sn on sn.id = r.sensor_id
  where r.farm_id = target_farm_id
    and r.tamper
    and r.measured_at > now() - interval '12 hours'
  order by r.sensor_id, r.measured_at desc;

  -- --- новые тревоги ---
  with inserted as (
    insert into alerts (farm_id, animal_id, sensor_id, kind, severity, title, detail)
    select target_farm_id, c.animal_id, c.sensor_id, c.kind, c.severity, c.title, c.detail
    from current_alerts c
    on conflict do nothing
    returning 1
  )
  select count(*) into v_opened from inserted;

  -- --- то, что вернулось к норме, закрываем само ---
  with closed as (
    update alerts a
    set resolved_at = now()
    where a.farm_id = target_farm_id
      and a.resolved_at is null
      and not exists (
        select 1 from current_alerts c
        where c.kind = a.kind
          and coalesce(c.animal_id, c.sensor_id) is not distinct from a.subject_id
      )
    returning 1
  )
  select count(*) into v_resolved from closed;

  drop table current_alerts;
  return query select v_opened, v_resolved;
end;
$$;

revoke execute on function detect_farm_alerts_internal(uuid) from public;

-- Обёртка для вызова из интерфейса. Работу делает та же функция, но здесь
-- сперва проверяется, что ферма действительно принадлежит вызывающему:
-- иначе чужой идентификатор в параметре открыл бы доступ к чужому хозяйству.
create or replace function detect_farm_alerts(target_farm_id uuid)
returns table (opened integer, resolved integer)
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
    or target_farm_id = public.current_device_farm()
  ) then
    raise exception 'Нет доступа к этой ферме';
  end if;

  return query select * from detect_farm_alerts_internal(target_farm_id);
end;
$$;

grant execute on function detect_farm_alerts(uuid) to authenticated;

-- Обход всех ферм — это и вешается на расписание
create or replace function detect_all_alerts()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  f record;
  total integer := 0;
  r record;
begin
  for f in select id from farms loop
    select * into r from detect_farm_alerts_internal(f.id);
    total := total + coalesce(r.opened, 0);
  end loop;
  return total;
end;
$$;

revoke execute on function detect_all_alerts() from public;
grant execute on function detect_all_alerts() to service_role;

-- ---------------------------------------------------------------------------
-- 5. Парк трекеров
-- ---------------------------------------------------------------------------
-- «Сколько всего трекеров зарегистрировано и сколько из них живы» —
-- вопрос, на который должен быть ответ одним взглядом.

create or replace view sensor_fleet
with (security_invoker = true) as
select
  sn.farm_id,
  count(*)::integer as total,
  count(*) filter (
    where sn.last_seen_at > now() - interval '6 hours'
  )::integer as online,
  count(*) filter (
    where sn.attached_at is not null
      and (sn.last_seen_at is null or sn.last_seen_at <= now() - interval '6 hours')
  )::integer as failed,
  count(*) filter (where sn.animal_id is null)::integer as unassigned,
  count(*) filter (where sn.battery_percent <= 15)::integer as low_battery,
  min(sn.battery_percent)::integer as worst_battery
from sensors sn
group by sn.farm_id;

-- ---------------------------------------------------------------------------
-- 6. Живой просмотр камеры
-- ---------------------------------------------------------------------------
-- Видео с фермы не гоняем: один поток — это два мегабита в секунду, а канал
-- на ферме один на всё хозяйство. Вместо этого, пока открыто окно просмотра,
-- устройство отдаёт кадры часто. Хозяин просит живой режим — в базе ставится
-- отметка до какого момента, устройство её видит и ускоряется.

alter table cameras add column if not exists live_until timestamptz;
alter table cameras add column if not exists stream_url text;

create or replace function request_live_view(target_camera_id uuid, seconds integer default 60)
returns timestamptz
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_until timestamptz;
begin
  -- Потолок нужен, чтобы забытая вкладка не держала ускоренный режим сутками
  v_until := now() + make_interval(secs => least(greatest(seconds, 5), 300));
  update cameras set live_until = v_until where id = target_camera_id;
  if not found then
    raise exception 'Камера не найдена';
  end if;
  return v_until;
end;
$$;

grant execute on function request_live_view(uuid, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 7. Публикация для обновлений в реальном времени
-- ---------------------------------------------------------------------------
-- Без этого страница узнавала бы о новой тревоге только при перезагрузке.

do $$
begin
  begin
    alter publication supabase_realtime add table alerts;
  exception when duplicate_object then null;
  end;
  begin
    alter publication supabase_realtime add table events;
  exception when duplicate_object then null;
  end;
  begin
    alter publication supabase_realtime add table sensor_readings;
  exception when duplicate_object then null;
  end;
end
$$;
