-- ---------------------------------------------------------------------------
-- Ракурсы: какой набран, какой ждём
-- ---------------------------------------------------------------------------
-- До сих пор запись копила «двадцать разных положений» без разбора,
-- какие именно. Теперь каждый эталон помечается ракурсом, а сеанс знает,
-- чего ещё не хватает, — на этом держатся и голосовые подсказки, и
-- список на экране.
--
-- Значения ракурса намеренно не «левый» и «правый». Который бок левый,
-- зависит от того, как повешена камера, и системе это неизвестно. Она
-- различает два РАЗНЫХ бока — для узнавания важно именно это, а не как
-- они называются.

alter table animal_embeddings drop constraint if exists animal_embeddings_view_check;
alter table animal_embeddings add constraint animal_embeddings_view_check
  check ("view" in ('camera', 'side_a', 'side_b', 'front', 'rear'));

comment on column animal_embeddings."view" is
  'side_a и side_b — два разных бока (какой левый, система не знает); front и rear — навстречу камере и от неё; camera — ракурс не разбирали';

-- ---------------------------------------------------------------------------
-- Что сеанс знает про ракурсы
-- ---------------------------------------------------------------------------

alter table enrollment_sessions
  add column if not exists views_order text[] not null default '{}',
  add column if not exists views_done text[] not null default '{}',
  add column if not exists views_skipped text[] not null default '{}';

comment on column enrollment_sessions.views_order is
  'В каком порядке просить ракурсы. Пусто — камера ракурсов не различает';
comment on column enrollment_sessions.views_done is
  'Уже набранные ракурсы';
comment on column enrollment_sessions.views_skipped is
  'Ракурсы, которые человек пропустил: животное их не показало';

-- ---------------------------------------------------------------------------
-- Сколько кадров на ракурс
-- ---------------------------------------------------------------------------
-- Ракурс считается набранным, когда в нём накопилось столько разных
-- положений. Пять на ракурс, четыре ракурса — те же двадцать, что
-- набираются сейчас.

alter table enrollment_sessions
  add column if not exists per_view integer not null default 5;

-- ---------------------------------------------------------------------------
-- Начало записи: порядок ракурсов зависит от камеры
-- ---------------------------------------------------------------------------
-- Просить у камеры то, чего она не покажет, — верный способ загнать
-- человека в тупик: он будет крутить животное, а счётчик стоять.

create or replace function views_for_camera(target_camera_id uuid)
returns text[]
language sql
stable
set search_path = public
as $$
  select case
    -- Сверху всегда одна и та же спина. Что бы животное ни делало,
    -- другого ракурса с этой камеры не появится
    when c.placement = 'overhead' then '{}'::text[]

    -- У кормушки животное стоит мордой к корму — иначе оно не ест.
    -- Поэтому перед идёт первым: он там берётся сразу
    when exists (
      select 1 from zones z
      where z.camera_id = c.id and z.kind = 'feeder'
    ) then array['front', 'side_a', 'side_b', 'rear']

    -- Сбоку от прохода. Бока первыми: они определяются надёжнее всего —
    -- два согласных признака против одного у переда с задом, — и дают
    -- больше всего для узнавания. Бросят запись на середине, останется
    -- самое ценное
    else array['side_a', 'side_b', 'front', 'rear']
  end
  from cameras c
  where c.id = target_camera_id
$$;

drop function if exists start_recording(uuid, text, uuid);

create function start_recording(
  target_camera_id uuid,
  animal_label text,
  existing_animal_id uuid default null
)
returns uuid
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_farm uuid;
  v_animal uuid;
  v_label text := trim(coalesce(animal_label, ''));
  v_session uuid;
  v_views text[];
begin
  select farm_id into v_farm from cameras where id = target_camera_id;
  if v_farm is null then
    raise exception 'Камера не найдена';
  end if;

  -- Просроченные сеансы закрываем здесь же: отдельное расписание ради
  -- этого заводить не стоит, а живой сеанс на камере должен быть один
  update enrollment_sessions
     set status = 'expired', finished_at = now()
   where status = 'recording' and expires_at < now();

  if exists (
    select 1 from enrollment_sessions
    where camera_id = target_camera_id and status = 'recording'
  ) then
    raise exception 'На этой камере уже идёт запись';
  end if;

  if existing_animal_id is not null then
    select id into v_animal
    from animals
    where id = existing_animal_id and farm_id = v_farm;

    if v_animal is null then
      raise exception 'Животное не найдено';
    end if;
  else
    if v_label = '' then
      raise exception 'Укажите кличку или номер';
    end if;

    insert into animals (farm_id, label, enrolled)
    values (v_farm, v_label, false)
    returning id into v_animal;
  end if;

  v_views := views_for_camera(target_camera_id);

  insert into enrollment_sessions (farm_id, camera_id, animal_id, views_order)
  values (v_farm, target_camera_id, v_animal, v_views)
  returning id into v_session;

  return v_session;
end;
$$;

grant execute on function start_recording(uuid, text, uuid) to authenticated;
grant execute on function views_for_camera(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Эталон с пометкой ракурса
-- ---------------------------------------------------------------------------
-- Ракурс засчитывается, когда в нём накопилось `per_view` кадров.
-- Кадры без ракурса не пропадают: они годятся для узнавания, просто не
-- закрывают ни один пункт списка.

drop function if exists add_recording_embedding(uuid, vector);
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
      -- Проверка на повтор ещё раз, уже в самом update: прочитанное в
      -- начале могло устареть, а дважды добавленный ракурс сделал бы
      -- список на экране бессмысленным
      update enrollment_sessions
         set views_done = case
               when v_view = any (views_done) then views_done
               else array_append(views_done, v_view)
             end
       where id = session_id
      returning views_done into v_row.views_done;
    end if;
  end if;

  -- Годным животное становится, как только набрано обещанное. Если
  -- человек уведёт его раньше конца, узнавание уже работает
  if v_row.captured >= v_row.needed then
    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  -- Запись закончена, когда закрыты все нужные ракурсы — или, если
  -- камера ракурсов не различает, просто набрано нужное число кадров
  if (
    cardinality(v_row.views_order) > 0
    and not exists (
      select 1 from unnest(v_row.views_order) as need
      where not (need = any (v_row.views_done))
        and not (need = any (v_row.views_skipped))
    )
  ) or (
    cardinality(v_row.views_order) = 0
    and v_row.captured >= greatest(v_row.target, v_row.needed)
  ) then
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
-- Пропустить ракурс
-- ---------------------------------------------------------------------------
-- Без этого строгое требование всех четырёх ракурсов превращает запись в
-- тупик на первом же упрямом животном. Пропущенный ракурс виден в
-- карточке, и запись можно дописать потом.

create or replace function skip_recording_view(session_id uuid)
returns text
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
  v_next text;
begin
  select * into v_row from enrollment_sessions where id = session_id;
  if v_row.id is null or v_row.status <> 'recording' then
    return null;
  end if;

  select need into v_next
  from unnest(v_row.views_order) with ordinality as t(need, ord)
  where not (need = any (v_row.views_done))
    and not (need = any (v_row.views_skipped))
  order by ord
  limit 1;

  if v_next is null then
    return null;
  end if;

  update enrollment_sessions
     set views_skipped = case
           when v_next = any (views_skipped) then views_skipped
           else array_append(views_skipped, v_next)
         end
   where id = session_id;

  return v_next;
end;
$$;

grant execute on function skip_recording_view(uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Что показывает интерфейс и что забирает устройство
-- ---------------------------------------------------------------------------

drop view if exists active_recording;
create view active_recording
with (security_invoker = true) as
select
  s.id,
  s.farm_id,
  s.camera_id,
  s.animal_id,
  a.label,
  s.captured,
  s.needed,
  s.target,
  s.per_view,
  s.views_order,
  s.views_done,
  s.views_skipped,
  -- Какой ракурс ждём сейчас: первый из порядка, который ещё не набран
  -- и не пропущен
  (
    select need
    from unnest(s.views_order) with ordinality as t(need, ord)
    where not (need = any (s.views_done))
      and not (need = any (s.views_skipped))
    order by ord
    limit 1
  ) as awaiting_view,
  s.hint,
  s.started_at,
  s.expires_at
from enrollment_sessions s
join animals a on a.id = s.animal_id
where s.status = 'recording' and s.expires_at > now();

grant select on active_recording to authenticated;
