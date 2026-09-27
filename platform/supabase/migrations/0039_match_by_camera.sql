-- ---------------------------------------------------------------------------
-- Узнавание с оглядкой на камеру
-- ---------------------------------------------------------------------------
-- Эталоны животного теперь приходят с разных камер, и они не равноценны
-- для кадра, который мы опознаём.
--
-- Кадр с верхней камеры — спина. Среди эталонов того же животного есть
-- спины с этой же камеры и профили с боковой. Профиль от спины отличается
-- сильнее, чем спина одного животного от спины другого. То есть чужой
-- эталон, снятый «правильным» ракурсом, может оказаться ближе своего —
-- и система назовёт чужую кличку.
--
-- Лечится надбавкой: эталон, снятый ЭТОЙ ЖЕ камерой, считается чуть
-- ближе, чем он есть.
--
-- Надбавка нарочно меньше требуемого отрыва. Сама решить спор она не
-- может: если два животных похожи почти одинаково, отрыв всё равно
-- окажется мал и система промолчит. Надбавка лишь помогает своей камере
-- выиграть там, где разница и так была.
--
-- Жёсткий отбор «только своя камера» здесь не годится. Животное, которое
-- успели записать только сбоку, перестало бы узнаваться сверху вовсе —
-- а это худший исход, чем небольшая неточность.

-- ---------------------------------------------------------------------------
-- Ровно одна функция. Перегрузок быть не должно ни одной
-- ---------------------------------------------------------------------------
-- Аргументы уходят по именам через HTTP: под одно имя подходит несколько
-- функций — и устройство перестаёт опознавать вовсе, с невнятным
-- «Could not choose the best candidate function». Это уже случалось.

drop function if exists match_animal(vector, uuid, real, integer);
drop function if exists match_animal(vector, uuid, real, integer, text);
drop function if exists match_animal(vector, uuid, real, integer, text, integer);
drop function if exists match_animal(vector, uuid, real, integer, text, integer, uuid);

create function match_animal(
  query_embedding vector(1536),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null,
  index_above integer default 300,
  -- С какой камеры пришёл опознаваемый кадр. Пусто — надбавки нет
  target_camera_id uuid default null
)
returns table (animal_id uuid, label text, distance real, margin real)
language sql
stable
set search_path = public
as $$
  with stored as (
    select count(*) as total
    from animal_embeddings e
    where e.farm_id = target_farm_id
  ),
  use_index as (
    select (select total from stored) > index_above as ok
  ),
  nearest as (
    -- Порядок задаётся ЧИСТЫМ расстоянием, без арифметики: любая
    -- надбавка внутри `order by` увела бы запрос с индекса.
    --
    -- Поэтому надбавка за свою камеру применяется НИЖЕ, после отбора
    -- сорока ближайших. На индексном пути это значит, что эталон своей
    -- камеры, не попавший в сорок ближайших, надбавкой уже не спасётся.
    -- Так и должно быть: не попал в сорок — значит, действительно далёк
    select
      e.animal_id,
      e.source,
      e.camera_id,
      (e.embedding <=> query_embedding)::real as raw
    from animal_embeddings e
    where (select ok from use_index)
      and e.farm_id = target_farm_id
      and (target_view is null or e."view" = target_view or e."view" = 'camera')
    order by e.embedding <=> query_embedding
    limit 40
  ),
  fast as (
    select
      n.animal_id,
      a.label,
      min(
        n.raw
        - case when n.source = 'recording' then 0.02 else 0 end
        - case
            when target_camera_id is not null and n.camera_id = target_camera_id
            then 0.03 else 0
          end
      )::real as distance
    from nearest n
    join animals a on a.id = n.animal_id
    group by n.animal_id, a.label
  ),
  exact as (
    -- Честный перебор по одной ферме. Условие вычисляется один раз, и
    -- когда работает индексный путь, эта ветка не выполняется
    select
      e.animal_id,
      a.label,
      min(
        (e.embedding <=> query_embedding)
        - case when e.source = 'recording' then 0.02 else 0 end
        - case
            when target_camera_id is not null and e.camera_id = target_camera_id
            then 0.03 else 0
          end
      )::real as distance
    from animal_embeddings e
    join animals a on a.id = e.animal_id
    where not (select ok from use_index)
      and e.farm_id = target_farm_id
      and (target_view is null or e."view" = target_view or e."view" = 'camera')
    group by e.animal_id, a.label
  ),
  chosen as (
    select * from fast
    union all
    select * from exact
  ),
  ranked as (
    select c.*, lead(c.distance) over (order by c.distance) as runner_up
    from chosen c
  )
  select
    r.animal_id,
    r.label,
    r.distance,
    (r.runner_up - r.distance)::real as margin
  from ranked r
  where r.distance < match_threshold
  order by r.distance
  limit match_count;
$$;

grant execute on function
  match_animal(vector, uuid, real, integer, text, integer, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Самопроверка: та же, но с новым числом аргументов
-- ---------------------------------------------------------------------------

create or replace function check_match_animal(
  target_farm_id uuid,
  samples integer default 20
)
returns text
language plpgsql
stable
set search_path = public
as $$
declare
  v_sample record;
  v_fast uuid;
  v_exact uuid;
  v_checked integer := 0;
  v_wrong integer := 0;
  v_total integer;
  v_overloads integer;
begin
  select count(*) into v_overloads
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname = 'match_animal';

  if v_overloads <> 1 then
    return format(
      'ПЛОХО: функций match_animal в базе %s, а должна быть одна. '
      'Устройство не сможет её вызвать',
      v_overloads
    );
  end if;

  select count(*) into v_total
  from animal_embeddings where farm_id = target_farm_id;

  for v_sample in
    select e.embedding
    from animal_embeddings e
    where e.farm_id = target_farm_id
    order by random()
    limit samples
  loop
    -- Порог 0 заставляет идти по индексу, заведомо большой — перебором.
    -- Надбавку за камеру не включаем: сравниваются два ПУТИ поиска, и
    -- лишнее слагаемое здесь только зашумило бы сравнение
    select m.animal_id into v_fast
    from match_animal(v_sample.embedding, target_farm_id, 1.0, 1, null, 0, null) m;

    select m.animal_id into v_exact
    from match_animal(
      v_sample.embedding, target_farm_id, 1.0, 1, null, 1000000000, null
    ) m;

    v_checked := v_checked + 1;
    if v_fast is distinct from v_exact then
      v_wrong := v_wrong + 1;
    end if;
  end loop;

  if v_checked = 0 then
    return 'функция одна, но проверять не на чем: у фермы нет эталонов';
  end if;

  if v_wrong = 0 then
    return format(
      'всё сходится: функция одна, проверено %s эталонов из %s, оба пути '
      'дали один и тот же ответ',
      v_checked, v_total
    );
  end if;

  return format(
    'РАСХОЖДЕНИЕ: из %s проверок %s дали разный ответ. Индексный путь '
    'ошибается — поднимите порог index_above, чтобы он не включался',
    v_checked, v_wrong
  );
end;
$$;

revoke all on function check_match_animal(uuid, integer) from public;
grant execute on function check_match_animal(uuid, integer) to authenticated;
