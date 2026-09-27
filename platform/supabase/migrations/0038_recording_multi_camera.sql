-- ---------------------------------------------------------------------------
-- Запись эталонов сразу с нескольких камер
-- ---------------------------------------------------------------------------
-- Сеанс был привязан к одной камере, и это оставляло дыру, которая
-- обнаруживается только на настоящей ферме.
--
-- Эталон должен приходить с той камеры, которая потом будет узнавать:
-- ровно поэтому убрали заведение по фотографиям. Но камер на проходе
-- две — сверху и сбоку, — и видят они разное. Сверху всегда одна и та
-- же спина, сбоку профиль. Для модели признаков это два несвязанных
-- набора.
--
-- Записанное только сбоку животное верхняя камера не узнает. А обмер
-- силуэта — то, ради чего верхняя камера и висит, — сохраняется с той
-- кличкой, которую распознала ОНА САМА. Не узнала — замер ложится
-- ничей: вес посчитан, а кому он принадлежит, неизвестно.
--
-- Теперь сеанс идёт по списку камер. Человек проводит животное по
-- проходу один раз, каждая камера берёт своё.
--
-- Камеры выбирает человек, а не система. Иначе не обойтись: если в этот
-- момент перед другой камерой в другом конце фермы стоит другое
-- животное, его кадры лягут под чужую кличку — молча и навсегда.
-- Правило простое и его надо знать: отмечать только те камеры, которые
-- смотрят на одно и то же место.

-- ---------------------------------------------------------------------------
-- Эталон помнит, с какой камеры снят
-- ---------------------------------------------------------------------------
-- Нужно двоим. Записи — чтобы считать квоту по каждой камере. Узнаванию
-- — чтобы предпочитать эталоны своей камеры чужим (миграция 0039).

alter table animal_embeddings
  add column if not exists camera_id uuid references cameras(id) on delete set null;

comment on column animal_embeddings.camera_id is
  'С какой камеры снят эталон. Пусто — со старых записей, до 0038';

create index if not exists animal_embeddings_camera_idx
  on animal_embeddings (farm_id, camera_id);

-- ---------------------------------------------------------------------------
-- Сеанс знает про список камер
-- ---------------------------------------------------------------------------

alter table enrollment_sessions
  add column if not exists camera_ids uuid[] not null default '{}',
  -- Сколько кадров берём с КАЖДОЙ камеры. Это и минимум, и потолок:
  -- набравшая своё камера перестаёт брать, иначе одна успевала бы
  -- набрать всё, а вторая — ничего, и мы вернулись бы к прежней дыре
  add column if not exists per_camera integer not null default 12,
  -- Сколько набрано по каждой камере: {"uuid-камеры": 7}
  add column if not exists captured_by jsonb not null default '{}'::jsonb,
  -- Что мешает КАЖДОЙ камере. Одна общая подсказка при двух камерах
  -- мигала бы: верхняя жалуется «никого не вижу», пока боковая
  -- спокойно берёт кадры
  add column if not exists hints jsonb not null default '{}'::jsonb;

-- Старые сеансы: список из одной камеры, той самой
update enrollment_sessions
   set camera_ids = array[camera_id]
 where cardinality(camera_ids) = 0;

create index if not exists enrollment_sessions_cameras_idx
  on enrollment_sessions using gin (camera_ids)
  where status = 'recording';

-- ---------------------------------------------------------------------------
-- Начало записи: список камер вместо одной
-- ---------------------------------------------------------------------------

drop function if exists start_recording(uuid, text, uuid);
drop function if exists start_recording(uuid[], text, uuid);

create function start_recording(
  target_camera_ids uuid[],
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
  v_farms integer;
  v_animal uuid;
  v_label text := trim(coalesce(animal_label, ''));
  v_session uuid;
  v_views text[];
  v_count integer := coalesce(cardinality(target_camera_ids), 0);
begin
  if v_count = 0 then
    raise exception 'Отметьте хотя бы одну камеру';
  end if;

  -- Камеры должны быть одной фермы. Иначе сеанс писал бы эталоны через
  -- границу хозяйства, а RLS проверяет ферму сеанса, не каждой камеры
  select count(distinct farm_id), min(farm_id)
    into v_farms, v_farm
  from cameras
  where id = any (target_camera_ids);

  if v_farm is null or v_farms <> 1 then
    raise exception 'Камеры не найдены или принадлежат разным фермам';
  end if;

  update enrollment_sessions
     set status = 'expired', finished_at = now()
   where status = 'recording' and expires_at < now();

  -- Пересечение, а не равенство: две записи, делящие одну камеру,
  -- поделили бы и её кадры между двумя животными
  if exists (
    select 1 from enrollment_sessions
    where status = 'recording' and camera_ids && target_camera_ids
  ) then
    raise exception 'На одной из этих камер уже идёт запись';
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

  -- Ракурсы берём по первой камере. Ходом записи они больше не
  -- управляют — она идёт одним круговым движением, — и нужны только
  -- чтобы в карточке было видно, что именно записано
  v_views := views_for_camera(target_camera_ids[1]);

  insert into enrollment_sessions (
    farm_id, camera_id, camera_ids, animal_id, views_order
  )
  values (
    v_farm, target_camera_ids[1], target_camera_ids, v_animal, v_views
  )
  returning id into v_session;

  return v_session;
end;
$$;

grant execute on function start_recording(uuid[], text, uuid) to authenticated;

-- ---------------------------------------------------------------------------
-- Эталон: со своей камеры и в счёт её квоты
-- ---------------------------------------------------------------------------
-- Возвращает:
--   -1  сеанс закончился или камера не из списка — прекратить
--   -2  квота этой камеры набрана — прекратить, но сеанс живой
--   >=0 сколько всего набрано

drop function if exists add_recording_embedding(uuid, vector);
drop function if exists add_recording_embedding(uuid, vector, text);
drop function if exists add_recording_embedding(uuid, vector, text, uuid);

create function add_recording_embedding(
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

  if v_row.captured >= v_row.needed then
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

-- ---------------------------------------------------------------------------
-- Подсказка — своя у каждой камеры
-- ---------------------------------------------------------------------------

drop function if exists set_recording_hint(uuid, text);
drop function if exists set_recording_hint(uuid, uuid, text);

create function set_recording_hint(
  session_id uuid,
  camera_id uuid,
  new_hint text
)
returns void
language sql
security invoker
set search_path = public
as $$
  update enrollment_sessions
     set hints = case
           when nullif(trim(coalesce(new_hint, '')), '') is null
             then hints - camera_id::text
           else jsonb_set(
             hints, array[camera_id::text], to_jsonb(trim(new_hint)), true
           )
         end,
         -- Старая одиночная колонка остаётся и хранит ПОСЛЕДНЮЮ помеху,
         -- какой бы камере она ни принадлежала. По ней потом пишется
         -- «Время записи вышло. Последнее, что мешало: слишком далеко».
         -- Без этого разбор неудавшейся записи снова стал бы гаданием
         hint = coalesce(
           nullif(trim(coalesce(new_hint, '')), ''), hint
         )
   where id = session_id and status = 'recording';
$$;

revoke all on function set_recording_hint(uuid, uuid, text) from public;
grant execute on function set_recording_hint(uuid, uuid, text) to authenticated;

-- ---------------------------------------------------------------------------
-- Что видит интерфейс и что забирает устройство
-- ---------------------------------------------------------------------------

drop view if exists active_recording;
create view active_recording
with (security_invoker = true) as
select
  s.id,
  s.farm_id,
  s.camera_id,
  s.camera_ids,
  s.animal_id,
  a.label,
  s.captured,
  s.needed,
  s.target,
  s.per_camera,
  s.captured_by,
  s.per_view,
  s.views_order,
  s.views_done,
  s.views_skipped,
  (
    select need
    from unnest(s.views_order) with ordinality as t(need, ord)
    where not (need = any (s.views_done))
      and not (need = any (s.views_skipped))
    order by ord
    limit 1
  ) as awaiting_view,
  -- Одна подсказка на всех — и только когда жалуются ВСЕ незакрытые
  -- камеры. Пока хоть одна берёт кадры, ничего не мешает, и писать
  -- человеку «никого не вижу» значит гнать его не туда
  case
    when not exists (
      select 1 from unnest(s.camera_ids) as cam
      where coalesce((s.captured_by ->> cam::text)::integer, 0) < s.per_camera
        and coalesce(s.hints ->> cam::text, '') = ''
    )
    then (
      select s.hints ->> cam::text
      from unnest(s.camera_ids) as cam
      where coalesce((s.captured_by ->> cam::text)::integer, 0) < s.per_camera
      limit 1
    )
  end as hint,
  s.hints,
  s.started_at,
  s.expires_at
from enrollment_sessions s
join animals a on a.id = s.animal_id
where s.status = 'recording' and s.expires_at > now();

grant select on active_recording to authenticated;

-- ---------------------------------------------------------------------------
-- Идущие сеансы, уже набравшие своё, закрываем сразу
-- ---------------------------------------------------------------------------
-- Иначе сеанс, начатый до этой миграции, повис бы: старая проверка
-- «набрано двадцать» больше не выполняется, а новая по камерам на нём
-- не сойдётся никогда — captured_by у него пуст

update enrollment_sessions
   set status = 'done', finished_at = now()
 where status = 'recording'
   and captured >= greatest(target, needed)
   and captured_by = '{}'::jsonb;
