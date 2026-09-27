-- ---------------------------------------------------------------------------
-- Одна функция поиска вместо трёх
-- ---------------------------------------------------------------------------
-- Прошлая миграция добавила версию с порогом, оставив прежнюю «для
-- совместимости». В базе оказалось три `match_animal` — с четырьмя,
-- пятью и шестью аргументами, — и устройство перестало опознавать
-- вообще:
--
--   Could not choose the best candidate function between: ...
--
-- Причина в том, как устроен доступ к базе через HTTP: аргументы
-- передаются по именам, и если под одно имя подходит несколько функций,
-- выбрать он не может и отказывается вызывать любую. Обычному SQL это
-- не мешает — он разбирает по типам, — поэтому ошибку легко не заметить,
-- пока не позовёшь так, как зовёт устройство.
--
-- Вывод на будущее: перегрузок здесь быть не должно. Ни одной.

drop function if exists match_animal(vector, uuid, real, integer);
drop function if exists match_animal(vector, uuid, real, integer, text);
drop function if exists match_animal(vector, uuid, real, integer, text, integer);

create function match_animal(
  query_embedding vector(1536),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null,
  -- Начиная с какого числа эталонов переходить на индексный поиск.
  --
  -- Индексный поиск приблизительный: он может не найти самый близкий
  -- эталон, и тогда ближайшим окажется другое животное — с хорошим
  -- отрывом. То есть система назовёт ЧУЖУЮ кличку уверенно, а это
  -- худшее, что она может сделать.
  --
  -- Ширину поиска по индексу подняли бы через `hnsw.ef_search`, но на
  -- Supabase менять этот параметр из функции не разрешено. Поэтому до
  -- трёхсот эталонов (примерно пятнадцать голов) считаем перебором:
  -- доли миллисекунды, ошибиться негде. Выше — индекс, потому что
  -- перебор начинает стоить заметно.
  index_above integer default 300
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
    -- Сорок ближайших, а не больше: без права поднять ширину поиска
    -- просить у индекса больше сорока бессмысленно. Сорока хватает —
    -- у одного животного эталонов не больше тридцати двух, значит в
    -- выборке всегда есть кто-то ещё, и отрыв от второго кандидата
    -- считается верно
    select
      e.animal_id,
      e.source,
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
      min(n.raw - case when n.source = 'recording' then 0.02 else 0 end)::real
        as distance
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
    -- Пусто, если сравнивать не с кем: одно животное на ферме всегда
    -- «уверенно узнано», и это надо видеть отдельно
    (r.runner_up - r.distance)::real as margin
  from ranked r
  where r.distance < match_threshold
  order by r.distance
  limit match_count;
$$;

grant execute on function
  match_animal(vector, uuid, real, integer, text, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- Чтобы перегрузка не вернулась незамеченной
-- ---------------------------------------------------------------------------
-- Проверка на один запрос. Если функций снова окажется больше одной,
-- доступ через HTTP отвалится с «Could not choose the best candidate
-- function», и виноват будет не тот, кто это увидит.

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
    -- Так сравниваются именно два пути, а не два запуска одного и того же
    select m.animal_id into v_fast
    from match_animal(v_sample.embedding, target_farm_id, 1.0, 1, null, 0) m;

    select m.animal_id into v_exact
    from match_animal(
      v_sample.embedding, target_farm_id, 1.0, 1, null, 1000000000
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
