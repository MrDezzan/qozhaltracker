-- Честный замер точности оценки веса.
-- Применять ПОСЛЕ 0020_auto_identity.sql.
--
-- Сейчас точность считает `fit_weight_model`, и считает НА ТЕХ ЖЕ
-- ДАННЫХ, по которым подбиралась формула. Такая ошибка всегда красивее
-- правды: формулу подогнали именно под эти точки, и она обязана на них
-- лежать хорошо. Показывать это число клиенту нельзя, и принимать по
-- нему решения тоже.
--
-- Настоящая ошибка меряется на данных, которых модель не видела.
-- Разбиваем взвешивания на части, подбираем формулу на всех кроме одной,
-- проверяем на отложенной — и так по кругу.
--
-- Разбиваем ПО ЖИВОТНЫМ, а не по взвешиваниям. Если одно и то же
-- животное попадёт и в подбор, и в проверку, модель будет угадывать
-- знакомое тело, а не работать по признакам, и ошибка снова выйдет
-- заниженной.

-- ---------------------------------------------------------------------------
-- 1. Подбор формулы на произвольном наборе животных
-- ---------------------------------------------------------------------------
-- Вынесено отдельно от fit_weight_model: та пишет результат в таблицу и
-- проверяет права, а здесь нужен чистый расчёт, вызываемый много раз.

create or replace function fit_power_law(
  target_farm_id uuid,
  exclude_animals uuid[]
)
returns table (coefficient_a double precision, exponent_b double precision, sample_count integer)
language sql
stable
set search_path = public
as $$
  select
    exp(regr_intercept(ln(weight_kg), ln(area_px))) as coefficient_a,
    regr_slope(ln(weight_kg), ln(area_px)) as exponent_b,
    count(*)::integer as sample_count
  from weight_training_pairs(target_farm_id)
  where area_px > 0
    and not (animal_id = any(exclude_animals));
$$;

-- ---------------------------------------------------------------------------
-- 2. Скользящий контроль
-- ---------------------------------------------------------------------------
-- Животные делятся на группы. Для каждой группы: формула подбирается на
-- остальных, ошибка считается на этой. Пять групп — обычный компромисс
-- между честностью и объёмом расчёта.
--
-- Возвращаем не одно число, а строку на каждое отложенное взвешивание:
-- по ним потом считается и средняя ошибка, и смещение, и худший случай,
-- и можно показать разброс на графике.

create or replace function weight_holdout_errors(
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
  -- Права: функция читает чужие данные, если ей дать чужой идентификатор
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
  from weight_training_pairs(target_farm_id) t
  where t.area_px > 0;

  v_total := coalesce(array_length(v_animals, 1), 0);

  -- Меньше трёх животных делить бессмысленно: в обучении не останется
  -- ничего, и формула выйдет бредовой
  if v_total < 3 then
    return;
  end if;

  -- Групп не больше, чем животных: иначе часть групп окажется пустой
  v_folds := least(greatest(coalesce(folds, 5), 2), v_total);

  for v_index in 0 .. v_folds - 1 loop
    -- Каждое v_folds-е животное, начиная с v_index. Раскладка по кругу,
    -- а не подряд: подряд идущие животные часто из одной группы (завезены
    -- вместе, одного возраста), и такая проверка была бы мягче реальности
    select array_agg(a)
    into v_holdout
    from unnest(v_animals) with ordinality as u(a, ord)
    where (ord - 1) % v_folds = v_index;

    if v_holdout is null then
      continue;
    end if;

    select f.coefficient_a, f.exponent_b, f.sample_count
    into v_a, v_b, v_count
    from fit_power_law(target_farm_id, v_holdout) f;

    -- На обучающей части не осталось данных — эту группу пропускаем
    if v_count is null or v_count < 2 or v_a is null or v_b is null then
      continue;
    end if;

    return query
    select
      t.animal_id,
      t.weight_kg,
      (v_a * power(t.area_px, v_b))::double precision,
      (v_a * power(t.area_px, v_b) - t.weight_kg)::double precision,
      (100.0 * (v_a * power(t.area_px, v_b) - t.weight_kg) / t.weight_kg)::double precision
    from weight_training_pairs(target_farm_id) t
    where t.area_px > 0
      and t.animal_id = any(v_holdout);
  end loop;
end;
$$;

grant execute on function weight_holdout_errors(uuid, integer) to authenticated;

comment on function weight_holdout_errors(uuid, integer) is
  'Ошибка оценки веса на животных, которых не было при подборе формулы. '
  'Единственный честный замер: показатель из fit_weight_model считается '
  'на обучающих данных и потому всегда занижен.';

-- ---------------------------------------------------------------------------
-- 3. Сводка одной строкой
-- ---------------------------------------------------------------------------

create or replace function weight_accuracy(target_farm_id uuid)
returns table (
  checked integer,
  animals integer,
  mae_kg double precision,
  mape_percent double precision,
  -- Систематическая ошибка: положительная — завышаем, отрицательная —
  -- занижаем. Средняя по модулю этого не показывает, а лечится
  -- смещение иначе, чем разброс
  bias_percent double precision,
  worst_percent double precision
)
language sql
stable
set search_path = public
as $$
  select
    count(*)::integer,
    count(distinct e.animal_id)::integer,
    avg(abs(e.error_kg)),
    avg(abs(e.error_percent)),
    avg(e.error_percent),
    max(abs(e.error_percent))
  from weight_holdout_errors(target_farm_id) e;
$$;

grant execute on function weight_accuracy(uuid) to authenticated;
