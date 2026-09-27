-- Промеры в сантиметрах и вторая формула веса.
-- Применять ПОСЛЕ 0022_subject_profile.sql.
--
-- Сейчас вес считается по площади силуэта. Площадь — не промер: она
-- меняется от поворота животного, от опущенной головы, от тени. Длина
-- и ширина от этого зависят гораздо слабее.
--
-- Но менять одно на другое вслепую нельзя. Поэтому здесь заводится
-- ВТОРАЯ формула — по длине и ширине, — и обе считаются на одних и тех
-- же данных. Какая точнее, покажет проверка с отложенной выборкой
-- из 0021. Решение принимается по числу, а не по убеждению.

-- ---------------------------------------------------------------------------
-- 1. Калибровка камеры
-- ---------------------------------------------------------------------------
-- Пиксели в сантиметры переводит один коэффициент. Он у камеры уже есть
-- (`cm_per_pixel` из 0009), но задать его было негде — только запросом
-- в базу. То есть на практике он всегда оставался пустым.
--
-- Способ задания: человек кладёт в кадр предмет известной длины
-- (рулетку, доску, метровую линейку), проводит по нему линию на снимке
-- и пишет, сколько это в сантиметрах. Всё остальное считается.

alter table cameras
  add column if not exists calibration_length_cm double precision,
  add column if not exists calibration_pixels double precision,
  add column if not exists calibrated_at timestamptz;

comment on column cameras.cm_per_pixel is
  'Сколько сантиметров в одном пикселе на уровне земли. Считается из '
  'калибровки: длина предмета в сантиметрах делится на его длину '
  'в пикселях. Пусто — промеры в сантиметрах недоступны.';

create or replace function calibrate_camera(
  target_camera_id uuid,
  real_length_cm double precision,
  pixel_length double precision
)
returns double precision
language plpgsql
security definer
set search_path = public
as $$
declare
  v_farm uuid;
  v_scale double precision;
begin
  select farm_id into v_farm from cameras where id = target_camera_id;
  if v_farm is null then
    raise exception 'Камера не найдена';
  end if;

  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = v_farm and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой камере';
  end if;

  if real_length_cm is null or real_length_cm <= 0 then
    raise exception 'Укажите длину предмета в сантиметрах';
  end if;
  if pixel_length is null or pixel_length <= 0 then
    raise exception 'Проведите линию по предмету на снимке';
  end if;

  v_scale := real_length_cm / pixel_length;

  -- Границы правдоподобия. Камера над проходом на трёх метрах даёт
  -- порядка 0,2–1,5 см на пиксель. Значение вне этого — почти наверняка
  -- перепутанные местами сантиметры и пиксели, и молча принять его
  -- значит получить корову длиной четыре метра
  if v_scale < 0.01 or v_scale > 20 then
    raise exception
      'Масштаб % см на пиксель неправдоподобен. Проверьте, что линия '
      'проведена по предмету, а длина указана в сантиметрах',
      round(v_scale::numeric, 3);
  end if;

  update cameras
  set cm_per_pixel = v_scale,
      calibration_length_cm = real_length_cm,
      calibration_pixels = pixel_length,
      calibrated_at = now()
  where id = target_camera_id;

  return v_scale;
end;
$$;

grant execute on function calibrate_camera(uuid, double precision, double precision) to authenticated;

-- ---------------------------------------------------------------------------
-- 2. Промеры в сантиметрах
-- ---------------------------------------------------------------------------
-- Считаются из пиксельных величин и масштаба. Отдельными колонками, а не
-- на лету: масштаб может поменяться при перекалибровке, а измерение
-- должно остаться таким, каким было сделано.

alter table body_measurements
  add column if not exists length_cm double precision,
  add column if not exists width_cm double precision;

-- Заполняем уже накопленное, где масштаб был известен
update body_measurements
set length_cm = length_px * cm_per_pixel,
    width_cm = width_px * cm_per_pixel
where cm_per_pixel is not null
  and length_cm is null;

-- ---------------------------------------------------------------------------
-- 3. Вторая формула веса
-- ---------------------------------------------------------------------------
-- Классическая зоотехническая формула считает вес от обхвата груди и
-- длины. Обхвата у нас нет, но ширина сверху с ним связана, поэтому
-- берём произведение длины на квадрат ширины — это объём с точностью до
-- постоянного множителя, а его подберёт регрессия.

alter table weight_models
  add column if not exists method text not null default 'area';

alter table weight_models drop constraint if exists weight_models_method_check;
alter table weight_models add constraint weight_models_method_check
  check (method in ('area', 'dimensions'));

comment on column weight_models.method is
  'area — вес по площади силуэта, работает без калибровки. '
  'dimensions — по длине и ширине в сантиметрах, требует калибровки '
  'камеры, но устойчивее к повороту животного.';

-- Ключ теперь пара «ферма + способ»: обе формулы живут рядом и
-- сравниваются на одних данных
alter table weight_models drop constraint if exists weight_models_pkey;
alter table weight_models add primary key (farm_id, method);

-- ---------------------------------------------------------------------------
-- 4. Обучающие пары для формулы по промерам
-- ---------------------------------------------------------------------------

create or replace function weight_training_pairs_cm(target_farm_id uuid)
returns table (
  animal_id uuid,
  weight_kg double precision,
  length_cm double precision,
  width_cm double precision,
  -- Длина × ширина² — объём с точностью до множителя. Именно эта
  -- величина связана с массой линейно, а не длина сама по себе
  volume_proxy double precision
)
language sql
stable
set search_path = public
as $$
  select
    w.animal_id,
    w.weight_kg,
    avg(m.length_cm) as length_cm,
    avg(m.width_cm) as width_cm,
    avg(m.length_cm * m.width_cm * m.width_cm) as volume_proxy
  from weighings w
  join body_measurements m
    on m.animal_id = w.animal_id
   and m.quality >= 0.8
   and m.length_cm is not null
   and m.width_cm is not null
   and m.measured_at between w.weighed_at - interval '3 days'
                        and w.weighed_at + interval '3 days'
  where w.farm_id = target_farm_id
  group by w.id, w.animal_id, w.weight_kg
$$;

-- ---------------------------------------------------------------------------
-- 5. Ошибка формулы по промерам на отложенной выборке
-- ---------------------------------------------------------------------------
-- Тот же скользящий контроль, что в 0021, но по другому признаку.
-- Две функции вместо одной с параметром: запросы к разным источникам
-- данных, и параметризовать их значило бы собирать SQL строками.

create or replace function weight_holdout_errors_cm(
  target_farm_id uuid,
  folds integer default 5
)
returns table (
  animal_id uuid,
  actual_kg double precision,
  predicted_kg double precision,
  error_kg double precision,
  error_percent double precision
)
language plpgsql
stable
set search_path = public
as $$
declare
  v_animals uuid[];
  v_total integer;
  v_folds integer;
  v_index integer;
  v_holdout uuid[];
  v_a double precision;
  v_b double precision;
  v_count integer;
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

  select array_agg(distinct t.animal_id order by t.animal_id)
  into v_animals
  from weight_training_pairs_cm(target_farm_id) t
  where t.volume_proxy > 0;

  v_total := coalesce(array_length(v_animals, 1), 0);
  if v_total < 3 then
    return;
  end if;

  v_folds := least(greatest(coalesce(folds, 5), 2), v_total);

  for v_index in 0 .. v_folds - 1 loop
    select array_agg(a)
    into v_holdout
    from unnest(v_animals) with ordinality as u(a, ord)
    where (ord - 1) % v_folds = v_index;

    if v_holdout is null then
      continue;
    end if;

    select
      exp(regr_intercept(ln(weight_kg), ln(volume_proxy))),
      regr_slope(ln(weight_kg), ln(volume_proxy)),
      count(*)::integer
    into v_a, v_b, v_count
    from weight_training_pairs_cm(target_farm_id)
    where volume_proxy > 0
      and not (animal_id = any(v_holdout));

    if v_count is null or v_count < 2 or v_a is null or v_b is null then
      continue;
    end if;

    return query
    select
      t.animal_id,
      t.weight_kg,
      (v_a * power(t.volume_proxy, v_b))::double precision,
      (v_a * power(t.volume_proxy, v_b) - t.weight_kg)::double precision,
      (100.0 * (v_a * power(t.volume_proxy, v_b) - t.weight_kg) / t.weight_kg)::double precision
    from weight_training_pairs_cm(target_farm_id) t
    where t.volume_proxy > 0
      and t.animal_id = any(v_holdout);
  end loop;
end;
$$;

grant execute on function weight_holdout_errors_cm(uuid, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 6. Сравнение двух способов
-- ---------------------------------------------------------------------------
-- Главная функция этого этапа. Отвечает на вопрос, ради которого всё
-- затевалось: стоят ли промеры возни, или площади силуэта достаточно.

create or replace function weight_method_comparison(target_farm_id uuid)
returns table (
  method text,
  checked integer,
  animals integer,
  mape_percent double precision,
  bias_percent double precision,
  worst_percent double precision
)
language sql
stable
set search_path = public
as $$
  select
    'area'::text,
    count(*)::integer,
    count(distinct e.animal_id)::integer,
    avg(abs(e.error_percent)),
    avg(e.error_percent),
    max(abs(e.error_percent))
  from weight_holdout_errors(target_farm_id) e
  union all
  select
    'dimensions'::text,
    count(*)::integer,
    count(distinct e.animal_id)::integer,
    avg(abs(e.error_percent)),
    avg(e.error_percent),
    max(abs(e.error_percent))
  from weight_holdout_errors_cm(target_farm_id) e;
$$;

grant execute on function weight_method_comparison(uuid) to authenticated;

comment on function weight_method_comparison(uuid) is
  'Ошибка обеих формул на одних и тех же данных, на отложенной выборке. '
  'По ней решается, нужны ли промеры вместо площади силуэта.';
