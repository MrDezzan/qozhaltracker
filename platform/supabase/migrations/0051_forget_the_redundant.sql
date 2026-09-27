-- ---------------------------------------------------------------------------
-- Забываем похожее, а не старое
-- ---------------------------------------------------------------------------
-- У животного двенадцать автоматических эталонов. Когда банк полон,
-- один надо выбросить, и раньше выбрасывался САМЫЙ СТАРЫЙ.
--
-- Из-за этого система забывала ровно то, что стоило помнить.
--
-- Корова десять раз подряд прошла мимо верхней камеры. Десять спин,
-- почти одинаковых, легли в банк и вытеснили профиль, снятый когда-то
-- сбоку. Дальше эта корова перестала узнаваться сбоку вовсе — при том
-- что нужный эталон у неё был, и мы сами его стёрли.
--
-- Со стороны это выглядит как «сначала узнавало, потом перестало», и
-- связать одно с другим нечем: в журнале ничего не происходит.
--
-- Теперь выбрасывается САМЫЙ ПОХОЖИЙ НА СОСЕДА — тот, чьё исчезновение
-- меньше всего меняет память животного. Идея из REMIND (evict_strategy:
-- "redundant"): банк прототипов должен хранить РАЗНОЕ, а не свежее.
--
-- Записанные человеком эталоны (source <> 'auto') по-прежнему не
-- трогаются никогда: они и есть основа узнавания.

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
    -- Самый избыточный: тот, до чьего ближайшего соседа ближе всего.
    --
    -- Соседи считаются среди ВСЕХ эталонов животного, включая
    -- записанные человеком: автоматический кадр, повторяющий
    -- человеческую запись, не нужен тем более.
    --
    -- nulls last — на случай единственного эталона: сравнивать не с
    -- чем, и выбрасывать его в последнюю очередь.
    delete from animal_embeddings
    where id = (
      select a.id
      from animal_embeddings a
      where a.animal_id = target_animal_id
        and a.source = 'auto'
      order by (
        select min(a.embedding <=> b.embedding)
        from animal_embeddings b
        where b.animal_id = target_animal_id
          and b.id <> a.id
      ) asc nulls last
      limit 1
    );
  end if;

  insert into animal_embeddings (farm_id, animal_id, embedding, "view", source)
  values (v_farm, target_animal_id, new_embedding, new_view, 'auto');
end;
$$;

grant execute on function add_auto_embedding(uuid, vector, text, integer) to authenticated;
