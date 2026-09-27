-- ---------------------------------------------------------------------------
-- Потолок записи — ровно двадцать кадров
-- ---------------------------------------------------------------------------
-- Потолок стоял вдвое выше обещанного, то есть сорок. Я поставил его
-- таким, когда завершение записи зависело от набранных ракурсов, и
-- запас был нужен на случай, если ракурс никак не покажут.
--
-- Ракурсами запись больше не управляет — она идёт одним круговым
-- движением, — и запас потерял смысл. Осталось только то, что человек
-- видит: полоса дошла до ста процентов, написано «готово», а кадры всё
-- берутся. Это выглядит как неисправность, и по существу ею и является:
-- система делает работу, о конце которой уже отчиталась.
--
-- Двадцать — это и есть тот предел, за которым новые кадры почти ничего
-- не добавляют: они отбираются на непохожесть, и по-настоящему разных
-- положений за один круг больше не набрать.

create or replace function add_recording_embedding(
  session_id uuid,
  new_embedding vector(1536),
  taken_view text default null
)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
  v_view text := nullif(trim(coalesce(taken_view, '')), '');
  v_in_view integer;
  v_cap integer;
  v_all_views_closed boolean;
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
  values (
    v_row.farm_id,
    v_row.animal_id,
    new_embedding,
    coalesce(v_view, 'camera'),
    'recording'
  );

  update enrollment_sessions
     set captured = captured + 1
   where id = session_id
  returning captured into v_row.captured;

  -- Ракурс отмечаем, если он разобран. Ходом записи это больше не
  -- управляет, но в карточке животного видно, что именно записано
  if v_view is not null and not (v_view = any (v_row.views_done)) then
    select count(*) into v_in_view
    from animal_embeddings
    where animal_id = v_row.animal_id
      and source = 'recording'
      and "view" = v_view;

    if v_in_view >= v_row.per_view then
      update enrollment_sessions
         set views_done = case
               when v_view = any (views_done) then views_done
               else array_append(views_done, v_view)
             end
       where id = session_id
      returning views_done into v_row.views_done;
    end if;
  end if;

  if v_row.captured >= v_row.needed then
    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  v_all_views_closed := cardinality(v_row.views_order) > 0 and not exists (
    select 1 from unnest(v_row.views_order) as need
    where not (need = any (v_row.views_done))
      and not (need = any (v_row.views_skipped))
  );

  -- Ровно двадцать, без запаса
  v_cap := greatest(v_row.target, v_row.needed);

  if v_all_views_closed or v_row.captured >= v_cap then
    if not v_all_views_closed and cardinality(v_row.views_order) > 0 then
      update enrollment_sessions
         set views_skipped = (
           select coalesce(array_agg(need), '{}')
           from unnest(views_order) as need
           where not (need = any (views_done))
         )
       where id = session_id;
    end if;

    update enrollment_sessions
       set status = 'done', finished_at = now()
     where id = session_id;

    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  return v_row.captured;
end;
$$;

grant execute on function add_recording_embedding(uuid, vector, text) to authenticated;

-- Идущие сеансы, уже набравшие своё, закрываем сразу
update enrollment_sessions
   set status = 'done', finished_at = now()
 where status = 'recording'
   and captured >= greatest(target, needed);
