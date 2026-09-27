-- ---------------------------------------------------------------------------
-- Запись обязана заканчиваться, даже если ракурсы не набрались
-- ---------------------------------------------------------------------------
-- Что случилось вживую. Человек сидел перед камерой ноутбука: вбок не
-- ходил, к камере не приближался. Значит, ракурс не определялся ни разу
-- — а сеанс закрывается только по закрытым ракурсам. Кадры копились
-- (пятьдесят восемь!), проценты стояли на нуле, конца не предвиделось.
--
-- Это моя ошибка в проектировании: строгое требование всех ракурсов я
-- сделал единственным условием завершения. Требование осталось, но
-- единственным условием быть не может — иначе запись превращается в
-- бесконечную на любой камере, где животное не ходит поперёк кадра.
--
-- Потолок вдвое выше обещанного. За ним новые кадры почти ничего не
-- добавляют: они всё равно отбираются на непохожесть, и после сорока
-- по-настоящему разных положений набрать неоткуда.

drop function if exists add_recording_embedding(uuid, vector, text);

create function add_recording_embedding(
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

  -- Ракурс закрывается, когда в нём набралось достаточно кадров
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

  -- Годным животное становится, как только набрано обещанное
  if v_row.captured >= v_row.needed then
    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  v_all_views_closed := cardinality(v_row.views_order) > 0 and not exists (
    select 1 from unnest(v_row.views_order) as need
    where not (need = any (v_row.views_done))
      and not (need = any (v_row.views_skipped))
  );

  v_cap := greatest(v_row.target, v_row.needed) * 2;

  if v_all_views_closed or v_row.captured >= v_cap then
    -- Ракурсы, которые так и не показали, честно помечаем пропущенными:
    -- в карточке животного будет видно, чего у него нет, и запись можно
    -- будет дописать
    if not v_all_views_closed then
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

-- ---------------------------------------------------------------------------
-- Закрыть зависшие сеансы
-- ---------------------------------------------------------------------------
-- Те, что уже набрали больше потолка и висят с прошлого запуска.

update enrollment_sessions
   set views_skipped = (
     select coalesce(array_agg(need), '{}')
     from unnest(views_order) as need
     where not (need = any (views_done))
   ),
   status = 'done',
   finished_at = now()
 where status = 'recording'
   and captured >= greatest(target, needed) * 2;
