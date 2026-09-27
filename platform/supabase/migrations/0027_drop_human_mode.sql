-- ---------------------------------------------------------------------------
-- Убираем режим стенда: система считает скот, и только скот
-- ---------------------------------------------------------------------------
-- Режим заводился, чтобы проверять вес и узнавание на людях, пока нет
-- фермы. Он себя не оправдал: переключатель, который почти никогда не
-- трогают, всё время висел в настройках, требовал объяснений на каждом
-- экране и создавал целый класс ошибок вида «данные собраны в одном
-- режиме, а прочитаны в другом».
--
-- Проверять на людях можно и без отдельного режима — на своих же
-- камерах, просто не называя это фермой.

update farms set subject_profile = 'livestock' where subject_profile <> 'livestock';

drop function if exists set_farm_profile(uuid, text);
drop function if exists weight_bounds(uuid);

-- ---------------------------------------------------------------------------
-- Границы правдоподобия веса — постоянные
-- ---------------------------------------------------------------------------
-- Оценка вне них означает, что что-то не так: испорченная формула,
-- мусорный силуэт, слипшиеся в одну маску животные. Пустая клетка
-- честнее коровы весом четыре килограмма.

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
begin
  if p_area_px is null or p_area_px <= 0 then
    return null;
  end if;

  select * into v_model from weight_models where farm_id = target_farm_id;
  if not found then
    return null;
  end if;

  v_kg := v_model.coefficient_a * power(p_area_px, v_model.exponent_b);

  -- Телёнок весит от двадцати килограммов, бык — до полутора тонн.
  -- За этими границами оценке верить нельзя
  if v_kg < 20.0 or v_kg > 1500.0 then
    return null;
  end if;

  return round(v_kg::numeric, 1)::double precision;
end;
$$;

alter table farms drop constraint if exists farms_subject_profile_check;
alter table farms drop column if exists subject_profile;
