-- ---------------------------------------------------------------------------
-- Длина вектора признаков: 1536, а не 1024
-- ---------------------------------------------------------------------------
-- Ошибка тянулась с самого начала и была невидимой, пока модель не
-- запустилась по-настоящему. Колонка заведена как vector(1024), а
-- MegaDescriptor-L-384 построен на Swin-L и выдаёт 1536 чисел. База
-- отбивала каждый эталон: «expected 1024 dimensions, not 1536».
--
-- Почему это не всплыло раньше. Проверить длину можно было только на
-- живой модели, а она весит сотни мегабайт и в тестах заменена
-- заглушкой. Всё, что зависело от узнавания, молча не работало.
--
-- Правим базу под модель, а не наоборот: L-версия выбрана осознанно —
-- она заметно точнее на повторной идентификации животных, а это ровно
-- то, ради чего всё и делается.

-- Накопленные векторы удаляем. Выбора нет: 1024 числа нельзя дополнить
-- до 1536, а даже если бы можно — они посчитаны другой моделью и
-- сравнивать их с новыми бессмысленно. Практически их и нет: всё, что
-- писалось до сих пор, база отбивала.
delete from animal_embeddings;

drop index if exists animal_embeddings_vector_idx;

alter table animal_embeddings
  alter column embedding type vector(1536);

create index if not exists animal_embeddings_vector_idx
  on animal_embeddings using hnsw (embedding vector_cosine_ops);

-- Записи, начатые до правки, закрываем: их счётчик всё равно стоит на
-- нуле, и человеку понятнее увидеть «время вышло», чем ждать дальше
update enrollment_sessions
   set status = 'expired', finished_at = now()
 where status = 'recording';

-- ---------------------------------------------------------------------------
-- Функции, принимающие вектор
-- ---------------------------------------------------------------------------
-- Старые версии с vector(1024) удаляем поимённо: `create or replace` их
-- не заменит — у функции с другим типом аргумента другая сигнатура, и в
-- базе осталось бы две. Дальше устройство вызывало бы то одну, то
-- другую, в зависимости от того, как Postgres разберёт типы.

drop function if exists match_animal(vector, uuid, real, integer, text);
drop function if exists add_recording_embedding(uuid, vector);
drop function if exists add_auto_embedding(uuid, vector, text, integer);
drop function if exists register_seen_animal(uuid, vector, text);

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
  with scored as (
    select
      e.animal_id,
      a.label,
      min(
        (e.embedding <=> query_embedding)
        - case when e.source = 'recording' then 0.02 else 0 end
      )::real as distance
    from animal_embeddings e
    join animals a on a.id = e.animal_id
    where e.farm_id = target_farm_id
      and (target_view is null or e."view" = target_view or e."view" = 'camera')
    group by e.animal_id, a.label
  ),
  ranked as (
    select s.*, lead(s.distance) over (order by s.distance) as runner_up
    from scored s
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

create or replace function add_recording_embedding(
  session_id uuid,
  new_embedding vector(1536)
)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
begin
  select * into v_row from enrollment_sessions where id = session_id;
  if v_row.id is null or v_row.status <> 'recording' then
    return -1;
  end if;

  if v_row.expires_at < now() then
    update enrollment_sessions
       set status = 'expired', finished_at = now()
     where id = session_id;
    return -1;
  end if;

  insert into animal_embeddings (farm_id, animal_id, embedding, "view", source)
  values (v_row.farm_id, v_row.animal_id, new_embedding, 'camera', 'recording');

  update enrollment_sessions
     set captured = captured + 1
   where id = session_id
  returning captured into v_row.captured;

  -- Набрали достаточно — закрываем сами. Ждать, пока человек нажмёт
  -- «Готово», не нужно: он в этот момент у загона, а не у экрана
  if v_row.captured >= v_row.needed then
    update enrollment_sessions
       set status = 'done', finished_at = now()
     where id = session_id;

    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  return v_row.captured;
end;
$$;

create or replace function add_auto_embedding(
  target_animal_id uuid,
  new_embedding vector(1536),
  new_view text default 'camera',
  keep_max integer default 12
)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_farm uuid;
  v_count integer;
begin
  select farm_id into v_farm from animals where id = target_animal_id;
  if v_farm is null then
    return;
  end if;

  select count(*) into v_count
  from animal_embeddings
  where animal_id = target_animal_id and source = 'auto';

  if v_count >= keep_max then
    -- Выбрасываем самый старый автоматический. Записанные человеком
    -- не трогаем никогда: они и есть основа узнавания
    delete from animal_embeddings
    where id = (
      select id from animal_embeddings
      where animal_id = target_animal_id and source = 'auto'
      order by created_at
      limit 1
    );
  end if;

  insert into animal_embeddings (farm_id, animal_id, embedding, "view", source)
  values (v_farm, target_animal_id, new_embedding, new_view, 'auto');
end;
$$;

create or replace function register_seen_animal(
  target_farm_id uuid,
  new_embedding vector(1536),
  new_view text default 'camera'
)
returns animals
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_number integer;
  v_animal animals;
begin
  -- Номер продолжает нумерацию, а не начинается с числа записей:
  -- после удаления особи счёт не должен пойти по второму кругу
  select coalesce(max(auto_number), 0) + 1 into v_number
  from animals where farm_id = target_farm_id;

  insert into animals (farm_id, label, enrolled, auto_created, auto_number)
  values (target_farm_id, '№ ' || v_number, false, true, v_number)
  returning * into v_animal;

  insert into animal_embeddings (farm_id, animal_id, embedding, "view", source)
  values (target_farm_id, v_animal.id, new_embedding, new_view, 'auto');

  return v_animal;
end;
$$;

grant execute on function match_animal(vector, uuid, real, integer, text) to authenticated;
grant execute on function add_recording_embedding(uuid, vector) to authenticated;
grant execute on function add_auto_embedding(uuid, vector, text, integer) to authenticated;
grant execute on function register_seen_animal(uuid, vector, text) to authenticated;
