-- Режим стенда: считаем людей вместо скота.
-- Применять ПОСЛЕ 0021_weight_accuracy.sql.
--
-- Фермы ещё нет, а проверять оценку веса, промеры и узнавание надо уже
-- сейчас. Единственные доступные подопытные — мы сами.
--
-- Почему это настройка, а не правка кода. Режим влияет на несколько
-- несвязанных вещей сразу:
--
--   охрана поднимает тревогу на человека — на стенде это каждый кадр;
--   границы правдоподобия веса заданы под корову, вес человека
--     система молча отбросила бы как ошибку;
--   в интерфейсе «поголовье» и «привес» читаются как настоящие данные.
--
-- Один забытый пункт из трёх — и стенд даёт цифры, которым нельзя
-- верить, причём выглядят они правдоподобно. Поэтому переключатель
-- один и хранится в одном месте.

alter table farms
  add column if not exists subject_profile text not null default 'livestock';

alter table farms drop constraint if exists farms_subject_profile_check;
alter table farms add constraint farms_subject_profile_check
  check (subject_profile in ('livestock', 'human'));

comment on column farms.subject_profile is
  'livestock — настоящая ферма, считаем скот. '
  'human — стенд: считаем людей, охрана выключена, данные не годятся '
  'ни для продажи, ни для подбора формулы веса на ферме.';

-- ---------------------------------------------------------------------------
-- Переключение
-- ---------------------------------------------------------------------------
-- Отдельной функцией, а не политикой на update: смена режима сбрасывает
-- подобранную формулу веса, и забыть это сделать нельзя.
--
-- Формула подбирается по контрольным взвешиваниям. Если она обучилась на
-- людях, а ферму переключили на скот, оценки уедут на порядок — и
-- выглядеть будут правдоподобно, потому что формула-то есть.

create or replace function set_farm_profile(target_farm_id uuid, new_profile text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_old text;
begin
  if new_profile not in ('livestock', 'human') then
    raise exception 'Неизвестный режим: %', new_profile;
  end if;

  if not (
    public.is_admin()
    or exists (
      select 1 from farms f
      where f.id = target_farm_id and f.owner_user_id = auth.uid()
    )
  ) then
    raise exception 'Нет доступа к этой ферме';
  end if;

  select subject_profile into v_old from farms where id = target_farm_id;
  if v_old is null then
    raise exception 'Ферма не найдена';
  end if;

  if v_old = new_profile then
    return new_profile;
  end if;

  update farms set subject_profile = new_profile where id = target_farm_id;

  -- Формула, подобранная на прежних подопечных, к новым отношения не
  -- имеет. Удаляем, а не пересчитываем: пересчитать не из чего
  delete from weight_models where farm_id = target_farm_id;

  return new_profile;
end;
$$;

grant execute on function set_farm_profile(uuid, text) to authenticated;

-- ---------------------------------------------------------------------------
-- Границы правдоподобия веса
-- ---------------------------------------------------------------------------
-- Оценка вне границ отбрасывается. Пустая клетка честнее коровы весом
-- четыре килограмма, а на стенде — человека весом полтонны.

create or replace function weight_bounds(target_farm_id uuid)
returns table (min_kg double precision, max_kg double precision)
language sql
stable
set search_path = public
as $$
  select
    case when f.subject_profile = 'human' then 20.0 else 20.0 end,
    case when f.subject_profile = 'human' then 250.0 else 1500.0 end
  from farms f
  where f.id = target_farm_id;
$$;

-- Оценка веса теперь молчит, если результат неправдоподобен
create or replace function estimate_weight_kg(
  target_farm_id uuid,
  p_area_px double precision
)
returns double precision
language plpgsql
stable
set search_path = public
as $$
declare
  v_model weight_models%rowtype;
  v_kg double precision;
  v_min double precision;
  v_max double precision;
begin
  if p_area_px is null or p_area_px <= 0 then
    return null;
  end if;

  select * into v_model from weight_models where farm_id = target_farm_id;
  if not found then
    return null;
  end if;

  v_kg := v_model.coefficient_a * power(p_area_px, v_model.exponent_b);

  select b.min_kg, b.max_kg into v_min, v_max from weight_bounds(target_farm_id) b;
  if v_min is null then
    return v_kg;
  end if;

  -- Вне границ — значит что-то не так: не тот режим, испорченная формула,
  -- мусорный силуэт. Показывать такое число нельзя
  if v_kg < v_min or v_kg > v_max then
    return null;
  end if;

  return round(v_kg::numeric, 1)::double precision;
end;
$$;
