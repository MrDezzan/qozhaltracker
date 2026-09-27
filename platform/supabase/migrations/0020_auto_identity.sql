-- Система сама запоминает животное при первой встрече.
-- Применять ПОСЛЕ 0019_fix_photo_upload.sql.
--
-- До сих пор животное существовало, только если человек завёл его руками
-- и загрузил снимки. Незнакомое просто проходило мимо камеры и нигде не
-- оставалось — а хочется, чтобы система увидела особь, запомнила и со
-- следующего раза узнавала сама, без всякого участия.
--
-- Это возвращает часть отменённого автоматизма, но принципиально иначе.
-- Раньше копилась очередь кадров, которую человек должен был разбирать;
-- ничего не работало, пока он этого не сделал. Теперь особь заводится
-- сразу и сразу узнаётся, а человек лишь ПЕРЕИМЕНОВЫВАЕТ «№ 12» в
-- «Зорьку», когда захочет. Работа системы от него не зависит.
--
-- Честно про цену: автоматическое заведение НЕИЗБЕЖНО плодит двойников.
-- Животное, впервые снятое сзади в темноте, а второй раз сбоку днём,
-- станет двумя записями. Поэтому здесь же — инструмент слияния, без
-- которого дубликаты копились бы без всякого выхода.

-- ---------------------------------------------------------------------------
-- 1. Откуда взялась запись
-- ---------------------------------------------------------------------------

alter table animals
  add column if not exists auto_created boolean not null default false,
  -- Порядковый номер автоматической особи в пределах фермы. Нужен, чтобы
  -- давать понятные имена «№ 1», «№ 2», а не куски идентификатора
  add column if not exists auto_number integer;

comment on column animals.auto_created is
  'Особь заведена системой при первой встрече. Кличку человек даёт потом; '
  'до этого показывается «№ N».';

-- Эталон, снятый камерой автоматически. Доверие к нему ниже, чем к
-- загруженному фото, но выше, чем ни к чему
alter table animal_embeddings drop constraint if exists animal_embeddings_source_check;
alter table animal_embeddings add constraint animal_embeddings_source_check
  check (source in ('enrollment', 'sighting', 'auto'));

-- ---------------------------------------------------------------------------
-- 2. Завести особь по кадру
-- ---------------------------------------------------------------------------
-- Одним вызовом: номер, запись, эталон. Иначе устройству пришлось бы
-- делать три запроса подряд и разбираться, что делать, если второй
-- прошёл, а третий нет.

create or replace function register_seen_animal(
  target_farm_id uuid,
  new_embedding vector(1024),
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

grant execute on function register_seen_animal(uuid, vector, text) to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Добавить эталон к уже известной особи
-- ---------------------------------------------------------------------------
-- Чем больше ракурсов, тем надёжнее узнавание. Но копить бесконечно
-- нельзя: поиск замедлится, а старые кадры (тощее животное зимой) будут
-- тянуть назад.

create or replace function add_auto_embedding(
  target_animal_id uuid,
  new_embedding vector(1024),
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
    -- Выбрасываем самый старый автоматический. Загруженные человеком
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

grant execute on function add_auto_embedding(uuid, vector, text, integer) to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Слияние двойников
-- ---------------------------------------------------------------------------
-- Обязательная часть автоматического заведения, а не украшение. Без неё
-- одно животное, записанное трижды, останется тремя записями навсегда.

create or replace function merge_animals(keep_id uuid, merge_id uuid)
returns animals
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_keep animals;
  v_merge animals;
begin
  select * into v_keep from animals where id = keep_id;
  select * into v_merge from animals where id = merge_id;

  if v_keep.id is null or v_merge.id is null then
    raise exception 'Животное не найдено';
  end if;
  if v_keep.farm_id <> v_merge.farm_id then
    raise exception 'Животные с разных ферм не сливаются';
  end if;
  if keep_id = merge_id then
    raise exception 'Нечего сливать: это одна и та же запись';
  end if;

  -- Переносим всё, что ссылается на присоединяемую особь. Порядок
  -- значения не имеет, но пропустить хоть одну таблицу нельзя:
  -- строки с внешним ключом не дадут удалить запись, а без каскада
  -- потерялась бы история
  update animal_embeddings set animal_id = keep_id where animal_id = merge_id;
  update sightings set animal_id = keep_id where animal_id = merge_id;
  update events set animal_id = keep_id where animal_id = merge_id;
  update sensors set animal_id = keep_id where animal_id = merge_id;
  update sensor_readings set animal_id = keep_id where animal_id = merge_id;
  update body_measurements set animal_id = keep_id where animal_id = merge_id;
  update weighings set animal_id = keep_id where animal_id = merge_id;
  update alerts set animal_id = keep_id where animal_id = merge_id;

  -- Эталонные фото: у присоединяемой могут быть ракурсы, которых нет у
  -- оставляемой. Переносим только их — на занятый ракурс не наступаем
  update animal_photos p
  set animal_id = keep_id
  where p.animal_id = merge_id
    and not exists (
      select 1 from animal_photos q
      where q.animal_id = keep_id and q."view" = p."view"
    );

  delete from animal_photos where animal_id = merge_id;
  delete from animals where id = merge_id;

  select * into v_keep from animals where id = keep_id;
  return v_keep;
end;
$$;

grant execute on function merge_animals(uuid, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- 5. Переименование
-- ---------------------------------------------------------------------------
-- «№ 12» превращается в «Зорьку». Отдельной функцией ради понятного
-- сообщения о двойнике: уникальный индекс скажет только имя ограничения.

create or replace function rename_animal(target_animal_id uuid, new_label text)
returns animals
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_animal animals;
  v_label text := btrim(coalesce(new_label, ''));
  v_farm uuid;
begin
  if v_label = '' then
    raise exception 'Кличка не может быть пустой';
  end if;

  select farm_id into v_farm from animals where id = target_animal_id;
  if v_farm is null then
    raise exception 'Животное не найдено';
  end if;

  if exists (
    select 1 from animals
    where farm_id = v_farm
      and lower(label) = lower(v_label)
      and id <> target_animal_id
  ) then
    raise exception 'Кличка «%» уже занята', v_label;
  end if;

  update animals
  set label = v_label,
      -- Названная человеком особь больше не считается безымянной
      auto_created = false
  where id = target_animal_id
  returning * into v_animal;

  return v_animal;
end;
$$;

grant execute on function rename_animal(uuid, text) to authenticated;

-- ---------------------------------------------------------------------------
-- 6. Кто на кого похож — подсказка для слияния
-- ---------------------------------------------------------------------------
-- Человеку не найти двойников глазами среди тридцати «№ N». Пусть
-- система сама покажет пары, которые подозрительно близки.

create or replace function similar_animals(
  target_farm_id uuid,
  max_distance real default 0.22
)
returns table (
  a_id uuid,
  a_label text,
  b_id uuid,
  b_label text,
  distance real
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    a.animal_id as a_id,
    aa.label as a_label,
    b.animal_id as b_id,
    ab.label as b_label,
    min(a.embedding <=> b.embedding)::real as distance
  from animal_embeddings a
  join animal_embeddings b
    on b.farm_id = a.farm_id
   -- Пара считается один раз: без этого условия каждая пара пришла бы
   -- дважды, в обе стороны
   and b.animal_id > a.animal_id
  join animals aa on aa.id = a.animal_id
  join animals ab on ab.id = b.animal_id
  where a.farm_id = target_farm_id
  group by a.animal_id, aa.label, b.animal_id, ab.label
  having min(a.embedding <=> b.embedding) < max_distance
  order by min(a.embedding <=> b.embedding)
  limit 20;
$$;

grant execute on function similar_animals(uuid, real) to authenticated;
