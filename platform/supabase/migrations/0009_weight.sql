-- Оценка живой массы по силуэту сверху.
--
-- Замысел. Камера сверху видит проекцию спины. Её площадь связана с объёмом
-- тела, а объём — с массой. Связь не универсальная: она своя у каждой породы,
-- возрастной группы и у каждой камеры (высота подвеса задаёт масштаб).
-- Поэтому мы не зашиваем формулу, а подбираем её на месте по контрольным
-- взвешиваниям конкретного хозяйства.
--
-- Разделение обязанностей: сервис на ферме измеряет силуэт и складывает сырые
-- числа. Формула живёт в базе. Значит, можно перепроверить оценку задним
-- числом на уже собранных измерениях, не переустанавливая ничего на ферме.

-- ---------------------------------------------------------------------------
-- 1. Масштаб камеры
-- ---------------------------------------------------------------------------
-- Сантиметров на пиксель на уровне спины животного. Заполняется при монтаже.
-- Если не задан — работаем в пикселях: коэффициент подбора всё равно вбирает
-- в себя постоянный масштаб, лишь бы камеру потом не двигали.

alter table cameras add column if not exists cm_per_pixel double precision;
alter table cameras add column if not exists mount_height_m double precision;
alter table cameras add column if not exists overhead boolean not null default false;

-- ---------------------------------------------------------------------------
-- 2. Измерения силуэта
-- ---------------------------------------------------------------------------

create table if not exists body_measurements (
  id bigserial primary key,
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  animal_id uuid references animals(id) on delete set null,
  sighting_id uuid references sightings(id) on delete set null,
  track_id integer not null,
  -- Сырые пиксельные величины: площадь маски, длина и ширина
  -- минимального описанного прямоугольника
  area_px double precision not null,
  length_px double precision not null,
  width_px double precision not null,
  -- Масштаб на момент измерения. Хранится копией: если камеру
  -- перекалибруют, старые измерения останутся пересчитываемыми
  cm_per_pixel double precision,
  -- Насколько кадру можно верить: 1.0 — животное целиком в кадре,
  -- одно, стоит ровно
  quality double precision not null default 1.0,
  measured_at timestamptz not null default now()
);

create index if not exists body_measurements_farm_idx
  on body_measurements(farm_id, measured_at desc);
create index if not exists body_measurements_animal_idx
  on body_measurements(animal_id, measured_at desc);

alter table body_measurements enable row level security;

drop policy if exists "body_measurements_read" on body_measurements;
create policy "body_measurements_read" on body_measurements
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "body_measurements_device_insert" on body_measurements;
create policy "body_measurements_device_insert" on body_measurements
  for insert with check (farm_id = public.current_device_farm() or public.is_admin());

-- ---------------------------------------------------------------------------
-- 3. Контрольные взвешивания
-- ---------------------------------------------------------------------------
-- Без них оценка веса — гадание. Это единственный источник правды,
-- по которому подбирается формула и по которому же считается её ошибка.

create table if not exists weighings (
  id bigserial primary key,
  farm_id uuid not null references farms(id) on delete cascade,
  animal_id uuid not null references animals(id) on delete cascade,
  weight_kg double precision not null check (weight_kg > 0 and weight_kg < 2000),
  weighed_at timestamptz not null default now(),
  source text not null default 'scale' check (source in ('scale', 'manual', 'import')),
  note text,
  created_at timestamptz not null default now()
);

create index if not exists weighings_farm_idx on weighings(farm_id, weighed_at desc);
create index if not exists weighings_animal_idx on weighings(animal_id, weighed_at desc);

alter table weighings enable row level security;

drop policy if exists "weighings_read" on weighings;
create policy "weighings_read" on weighings
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

drop policy if exists "weighings_write" on weighings;
create policy "weighings_write" on weighings
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- 4. Подобранная формула
-- ---------------------------------------------------------------------------
-- Степенная зависимость: масса = a * площадь^b. В логарифмах она становится
-- прямой, а прямую Postgres умеет проводить сам, без внешних библиотек.
-- Показатель b теоретически около 1.5 (площадь растёт как квадрат линейного
-- размера, масса — как куб); сильное отклонение означает, что данные плохие.

create table if not exists weight_models (
  farm_id uuid primary key references farms(id) on delete cascade,
  coefficient_a double precision not null,
  exponent_b double precision not null,
  sample_count integer not null,
  mae_kg double precision,
  mape_percent double precision,
  r_squared double precision,
  fitted_at timestamptz not null default now()
);

alter table weight_models enable row level security;

drop policy if exists "weight_models_read" on weight_models;
create policy "weight_models_read" on weight_models
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

drop policy if exists "weight_models_admin_write" on weight_models;
create policy "weight_models_admin_write" on weight_models
  for all using (public.is_admin());

-- Сколько взвешиваний нужно, чтобы формуле вообще можно было верить.
-- Меньше десятка — это подгонка под шум.
create or replace function weight_min_samples() returns integer
language sql immutable as $$ select 10 $$;

-- Пары «взвешивание — измерение силуэта»: берём измерения того же животного
-- в пределах трёх суток от взвешивания. За трое суток вес меняется меньше
-- чем на процент, а вот силуэт успевает попасться в разных позах.
create or replace function weight_training_pairs(target_farm_id uuid)
returns table (animal_id uuid, weight_kg double precision, area_px double precision)
language sql
stable
set search_path = public
as $$
  select
    w.animal_id,
    w.weight_kg,
    avg(m.area_px) as area_px
  from weighings w
  join body_measurements m
    on m.animal_id = w.animal_id
   and m.quality >= 0.8
   and m.measured_at between w.weighed_at - interval '3 days'
                        and w.weighed_at + interval '3 days'
  where w.farm_id = target_farm_id
  group by w.id, w.animal_id, w.weight_kg
$$;

-- Подбор формулы. Возвращает саму формулу и честную оценку её ошибки.
create or replace function fit_weight_model(target_farm_id uuid)
returns weight_models
language plpgsql
security definer
set search_path = public
as $$
declare
  v_slope double precision;
  v_intercept double precision;
  v_r2 double precision;
  v_count integer;
  v_a double precision;
  v_mae double precision;
  v_mape double precision;
  v_result weight_models;
begin
  -- Функция работает от имени владельца схемы, поэтому «ваша ли это ферма»
  -- проверяем здесь: иначе чужой идентификатор в параметре подобрал бы
  -- формулу чужому хозяйству
  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = target_farm_id and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой ферме';
  end if;

  select
    regr_slope(ln(weight_kg), ln(area_px)),
    regr_intercept(ln(weight_kg), ln(area_px)),
    regr_r2(ln(weight_kg), ln(area_px)),
    count(*)
  into v_slope, v_intercept, v_r2, v_count
  from weight_training_pairs(target_farm_id)
  where area_px > 0;

  if v_count is null or v_count < weight_min_samples() then
    raise exception
      'Для подбора формулы нужно не меньше % взвешиваний со снятым силуэтом, есть %',
      weight_min_samples(), coalesce(v_count, 0);
  end if;

  v_a := exp(v_intercept);

  -- Ошибка считается на тех же данных, поэтому она оптимистична.
  -- Настоящая проверка — на животных, которых не было в подборе.
  select
    avg(abs(v_a * power(area_px, v_slope) - weight_kg)),
    avg(abs(v_a * power(area_px, v_slope) - weight_kg) / weight_kg * 100)
  into v_mae, v_mape
  from weight_training_pairs(target_farm_id)
  where area_px > 0;

  insert into weight_models (
    farm_id, coefficient_a, exponent_b, sample_count, mae_kg, mape_percent, r_squared, fitted_at
  )
  values (target_farm_id, v_a, v_slope, v_count, v_mae, v_mape, v_r2, now())
  on conflict (farm_id) do update set
    coefficient_a = excluded.coefficient_a,
    exponent_b = excluded.exponent_b,
    sample_count = excluded.sample_count,
    mae_kg = excluded.mae_kg,
    mape_percent = excluded.mape_percent,
    r_squared = excluded.r_squared,
    fitted_at = excluded.fitted_at
  returning * into v_result;

  return v_result;
end;
$$;

grant execute on function fit_weight_model(uuid) to authenticated;

-- Оценка веса по измерению. Null, если формулы для фермы ещё нет —
-- лучше пустая клетка, чем красивое, но выдуманное число.
create or replace function estimate_weight_kg(target_farm_id uuid, p_area_px double precision)
returns double precision
language sql
stable
as $$
  select round((m.coefficient_a * power(p_area_px, m.exponent_b))::numeric, 1)::double precision
  from weight_models m
  where m.farm_id = target_farm_id and p_area_px > 0
$$;

-- Текущий вес животного: усреднение по измерениям за последние трое суток.
-- Одиночное измерение шумит — животное могло стоять боком или нагнуться.
create or replace view animal_weight_estimates
with (security_invoker = true) as
select
  m.farm_id,
  m.animal_id,
  a.label,
  count(*) as measurements,
  avg(m.area_px) as avg_area_px,
  estimate_weight_kg(m.farm_id, avg(m.area_px)) as estimated_weight_kg,
  max(m.measured_at) as last_measured_at
from body_measurements m
join animals a on a.id = m.animal_id
where m.animal_id is not null
  and m.quality >= 0.8
  and m.measured_at > now() - interval '3 days'
group by m.farm_id, m.animal_id, a.label;

-- Привес: сравнение с оценкой месячной давности. Это и есть та цифра,
-- ради которой существует откормочная площадка.
create or replace view animal_daily_gain
with (security_invoker = true) as
with windows as (
  select
    m.farm_id,
    m.animal_id,
    avg(m.area_px) filter (
      where m.measured_at > now() - interval '3 days'
    ) as area_now,
    avg(m.area_px) filter (
      where m.measured_at between now() - interval '33 days' and now() - interval '27 days'
    ) as area_before
  from body_measurements m
  where m.animal_id is not null and m.quality >= 0.8
  group by m.farm_id, m.animal_id
)
select
  w.farm_id,
  w.animal_id,
  a.label,
  estimate_weight_kg(w.farm_id, w.area_now) as weight_now_kg,
  estimate_weight_kg(w.farm_id, w.area_before) as weight_30d_ago_kg,
  round(
    ((estimate_weight_kg(w.farm_id, w.area_now)
      - estimate_weight_kg(w.farm_id, w.area_before)) / 30.0)::numeric, 2
  )::double precision as daily_gain_kg
from windows w
join animals a on a.id = w.animal_id
where w.area_now is not null and w.area_before is not null;
