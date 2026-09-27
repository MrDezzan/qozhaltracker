-- ---------------------------------------------------------------------------
-- Поиск по эталонам: точный на малых стадах, индексный на больших
-- ---------------------------------------------------------------------------
-- Прежний запрос перебирал ВСЕ эталоны фермы. Индекс, построенный ровно
-- для этого, не использовался: его ломали группировка по животному и
-- надбавка за источник эталона внутри `min(...)`.
--
-- Тысяча голов по двадцать ракурсов — двадцать тысяч сравнений на каждое
-- опознание, а опознаний по несколько на каждый проход мимо камеры.
--
-- ---------------------------------------------------------------------------
-- Почему индексный поиск включается НЕ ВСЕГДА
-- ---------------------------------------------------------------------------
-- Поиск по индексу приблизительный: он может не найти самый близкий
-- эталон. Обычно это значит «не узнали в этот раз» — не страшно. Но
-- если пропущен именно правильный, ближайшим окажется другое животное,
-- и с хорошим отрывом. То есть система назовёт ЧУЖУЮ кличку уверенно.
--
-- Это худшее, что она может сделать: неверная кличка на кадре рушит
-- доверие быстрее, чем её отсутствие.
--
-- Ширину поиска по индексу (`hnsw.ef_search`) можно было бы поднять и
-- почти убрать эту вероятность, но на Supabase параметр менять из
-- функции не разрешено: «permission denied to set parameter».
--
-- Поэтому размен делается честно и по обстоятельствам:
--
--   до 300 эталонов — считаем перебором. Это доли миллисекунды, и
--   ошибиться негде. Триста эталонов — это примерно пятнадцать голов;
--   стада меньше сотни живут здесь всегда;
--
--   больше 300 — включаем индекс, потому что перебор начинает стоить
--   заметно, а вероятность промаха на широком стаде уже размывается
--   тем, что животных много и все они разные.
--
-- Порог вынесен в параметр: когда появится настоящая ферма, его можно
-- будет подвинуть по замерам, не переписывая функцию.

create or replace function match_animal(
  query_embedding vector(1536),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null,
  -- Начиная с какого числа эталонов переходить на индекс
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
    -- Быстрый путь. Порядок задаётся ЧИСТЫМ расстоянием, без арифметики:
    -- любая надбавка внутри `order by` увела бы запрос с индекса.
    --
    -- Сорок ближайших, а не больше: без права поднять ширину поиска
    -- просить у индекса больше сорока бессмысленно — он столько и
    -- просматривает. Сорока хватает: у одного животного эталонов не
    -- больше тридцати двух, значит в выборке всегда есть кто-то ещё,
    -- и отрыв от второго кандидата считается верно
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
    -- Честный перебор по одной ферме — ровно то, что было до этой
    -- правки. Условие вычисляется один раз, и когда работает индексный
    -- путь, эта ветка не выполняется
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

grant execute on function match_animal(vector, uuid, real, integer, text, integer) to authenticated;

-- Прежняя пятиаргументная версия остаётся: устройство зовёт функцию без
-- порога, и обе сигнатуры должны существовать, иначе вызов не найдёт
-- функцию. Тело просто передаёт значение по умолчанию
create or replace function match_animal(
  query_embedding vector(1536),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null
)
returns table (animal_id uuid, label text, distance real, margin real)
language sql
stable
set search_path = public
as $$
  select * from match_animal(
    query_embedding, target_farm_id, match_threshold, match_count, target_view, 300
  );
$$;

grant execute on function match_animal(vector, uuid, real, integer, text) to authenticated;

-- Перебор должен идти по строкам одного хозяйства, а не по всей таблице
create index if not exists animal_embeddings_farm_animal_idx
  on animal_embeddings (farm_id, animal_id);

-- ---------------------------------------------------------------------------
-- Самопроверка
-- ---------------------------------------------------------------------------
-- Индексный путь обязан давать тот же ответ, что и честный перебор.
-- Верить этому на слово нельзя: ошибка здесь не падает с сообщением, а
-- тихо называет чужую кличку.
--
-- Функция берёт настоящие эталоны фермы и прогоняет каждый через оба
-- пути. Запускать после применения миграции и потом при любом сомнении,
-- особенно когда стадо перевалит за порог:
--
--     select check_match_animal('идентификатор-фермы');

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
begin
  select count(*) into v_total
  from animal_embeddings where farm_id = target_farm_id;

  for v_sample in
    select e.embedding
    from animal_embeddings e
    where e.farm_id = target_farm_id
    order by random()
    limit samples
  loop
    -- Порог 0 заставляет идти по индексу, порог заведомо большой —
    -- перебором. Так сравниваются именно два пути, а не два запуска
    -- одного и того же
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
    return 'проверять нечего: у этой фермы нет ни одного эталона';
  end if;

  if v_wrong = 0 then
    return format(
      'всё сходится: проверено %s эталонов из %s, оба пути дали один и '
      'тот же ответ',
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
