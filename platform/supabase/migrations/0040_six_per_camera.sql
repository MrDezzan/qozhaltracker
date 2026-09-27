-- ---------------------------------------------------------------------------
-- Шесть кадров с камеры вместо двенадцати
-- ---------------------------------------------------------------------------
-- Камеры пишут одновременно, а не по очереди: животное идёт по проходу
-- один раз, и обе видят его в один и тот же момент. Двенадцать кадров с
-- каждой означали двенадцать РАЗНЫХ положений — то есть человек стоял и
-- водил животное кругами, пока набиралось.
--
-- Шесть — это по-прежнему шесть заметно разных положений: кадры
-- отбираются на непохожесть, и одинаковые в счёт не идут.
--
-- Плата названа честно: эталонов вдвое меньше, отрыв ближайшего от
-- второго кандидата в среднем меньше, спорных опознаний больше. Их
-- разбирает переспрос по другому кадру — тот самый, что появился вместе
-- с записью на две камеры. Если на ферме окажется, что клички
-- появляются с задержкой или не появляются вовсе, это число поднимается
-- обратно одним update и без перезаписи животных.

alter table enrollment_sessions alter column per_camera set default 6;

comment on column enrollment_sessions.per_camera is
  'Сколько кадров берёт каждая отмеченная камера. И минимум, и потолок: набравшая своё замолкает';

-- Идущие сеансы переводим тоже. Иначе человек, начавший запись минуту
-- назад, будет водить животное до двенадцати, а на экране уже новые
-- проценты
update enrollment_sessions
   set per_camera = 6
 where status = 'recording' and per_camera = 12;

-- ---------------------------------------------------------------------------
-- «Заведено» больше не привязано к числу двенадцать
-- ---------------------------------------------------------------------------
-- Ловушка, которую легко не заметить. Флаг ставился при `captured >=
-- needed`, а needed равен двенадцати. При двух камерах по шесть это
-- ровно двенадцать и сходится, а при ОДНОЙ камере набирается шесть —
-- и животное, записанное полностью и успешно, навсегда осталось бы
-- «не заведённым».

create or replace function add_recording_embedding(
  session_id uuid,
  new_embedding vector(1536),
  taken_view text default null,
  taken_camera_id uuid default null
)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
  v_view text := nullif(trim(coalesce(taken_view, '')), '');
  v_camera uuid;
  v_key text;
  v_mine integer;
  v_in_view integer;
  v_done boolean;
  v_enough integer;
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

  -- Камеру не угадываем: не назвалась — считаем, что это первая из
  -- списка. Так продолжают работать устройства, не знающие про 0038
  v_camera := coalesce(taken_camera_id, v_row.camera_ids[1]);

  if not (v_camera = any (v_row.camera_ids)) then
    return -1;
  end if;

  v_key := v_camera::text;
  v_mine := coalesce((v_row.captured_by ->> v_key)::integer, 0);

  if v_mine >= v_row.per_camera then
    return -2;
  end if;

  insert into animal_embeddings (
    farm_id, animal_id, camera_id, embedding, "view", source
  )
  values (
    v_row.farm_id,
    v_row.animal_id,
    v_camera,
    new_embedding,
    coalesce(v_view, 'camera'),
    'recording'
  );

  update enrollment_sessions
     set captured = captured + 1,
         captured_by = jsonb_set(
           captured_by, array[v_key], to_jsonb(v_mine + 1), true
         ),
         -- Кадр взят — значит, эта камера ни на что не жалуется
         hints = hints - v_key
   where id = session_id
  returning captured, captured_by into v_row.captured, v_row.captured_by;

  -- Ракурс отмечаем, если он разобран. Ходом записи это не управляет
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
       where id = session_id;
    end if;
  end if;

  -- Сколько кадров вообще может набраться в этом сеансе. Меньшее из
  -- обещанного и возможного: требовать двенадцати там, где камера одна
  -- и потолок шесть, значит не признать заведённым никого
  v_enough := least(
    v_row.needed,
    v_row.per_camera * greatest(1, cardinality(v_row.camera_ids))
  );

  if v_row.captured >= v_enough then
    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  -- Готово, когда КАЖДАЯ отмеченная камера набрала своё. Не «всего
  -- столько-то»: иначе верхняя камера, стоящая удачнее, набрала бы всё
  -- сама, и боковая осталась бы ни с чем — то есть ровно та беда,
  -- ради которой всё это и делается
  v_done := not exists (
    select 1 from unnest(v_row.camera_ids) as cam
    where coalesce((v_row.captured_by ->> cam::text)::integer, 0)
          < v_row.per_camera
  );

  if v_done then
    update enrollment_sessions
       set status = 'done', finished_at = now()
     where id = session_id;

    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  return v_row.captured;
end;
$$;

grant execute on function
  add_recording_embedding(uuid, vector, text, uuid) to authenticated;

-- Сеансы, уже перебравшие новый потолок, закрываем сразу: иначе они
-- висели бы до истечения срока, занимая свои камеры
-- `cardinality > 0` обязательна. Без неё «не существует камеры, которой
-- не хватает» верно и для сеанса вообще без камер — и закрылись бы все
-- подряд, включая только что начатые
update enrollment_sessions
   set status = 'done', finished_at = now()
 where status = 'recording'
   and cardinality(camera_ids) > 0
   and not exists (
     select 1 from unnest(camera_ids) as cam
     where coalesce((captured_by ->> cam::text)::integer, 0) < per_camera
   );
