-- ---------------------------------------------------------------------------
-- Заведение животного записью с камеры вместо загрузки фотографий
-- ---------------------------------------------------------------------------
-- Почему фотографии убраны.
--
-- Дело не только в неудобстве. Узнавание сравнивает кадр с камеры с
-- эталоном, и модель признаков чувствительна к тому, ЧЕМ и КАК снято.
-- Фото с телефона — днём, с двух метров, сбоку — и кадр потолочной
-- камеры ночью для неё почти не связаны. Даже загруженные аккуратно,
-- такие эталоны давали слабое совпадение.
--
-- Запись с самой камеры снимает эту разницу целиком: эталон и рабочий
-- кадр приходят из одного источника, под одним светом, с одного угла.
-- Человеку при этом достаточно ввести кличку и провести животное мимо
-- камеры — ни телефона, ни загрузок.

-- ---------------------------------------------------------------------------
-- 1. Прежние эталоны из фотографий
-- ---------------------------------------------------------------------------
-- Удаляем сами эталоны, но не животных: клички, взвешивания и история
-- к фотографиям отношения не имеют, и терять их незачем.

-- Эталоны из фотографий лежат под источником 'enrollment' — так они
-- назывались, когда других способов завести животное не было
delete from animal_embeddings where source = 'enrollment';

alter table animal_embeddings drop constraint if exists animal_embeddings_source_check;
alter table animal_embeddings add constraint animal_embeddings_source_check
  check (source in ('recording', 'sighting', 'auto'));

drop table if exists animal_photos cascade;

-- Доступ к хранилищу снимков закрываем: политики без применения — это
-- разрешения, о которых через полгода никто не вспомнит.
--
-- Сами файлы миграцией не удаляем: Supabase запрещает прямое удаление
-- из storage.objects (`Direct deletion from storage tables is not
-- allowed`), и это правильно — записи в таблице и файлы в хранилище
-- удаляются вместе, а не по отдельности. Корзину animal-photos надо
-- удалить руками: Storage → animal-photos → Delete bucket. Пока она
-- есть, она просто занимает место и ни на что не влияет.
drop policy if exists "animal_photos_storage_read" on storage.objects;
drop policy if exists "animal_photos_storage_write" on storage.objects;

-- ---------------------------------------------------------------------------
-- 2. Сеанс записи
-- ---------------------------------------------------------------------------
-- Одна строка на «сейчас записываем вот это животное вот с этой камеры».
-- Устройство спрашивает её раз в пару секунд и, пока она есть, копит
-- эталоны с живого потока.

create table if not exists enrollment_sessions (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  animal_id uuid not null references animals(id) on delete cascade,
  status text not null default 'recording'
    check (status in ('recording', 'done', 'cancelled', 'expired')),
  captured integer not null default 0,
  -- Сколько РАЗНЫХ ракурсов нужно набрать, прежде чем считать животное
  -- записанным. Не «сколько кадров»: пятьдесят кадров одной и той же
  -- позы — это по сути один кадр
  needed integer not null default 12,
  started_at timestamptz not null default now(),
  -- Сеанс, о котором забыли, должен закрыться сам. Иначе камера будет
  -- вечно записывать эталоны первому встречному в кадре
  expires_at timestamptz not null default now() + interval '5 minutes',
  finished_at timestamptz
);

create index if not exists enrollment_sessions_active_idx
  on enrollment_sessions (camera_id, status)
  where status = 'recording';

create index if not exists enrollment_sessions_farm_idx
  on enrollment_sessions (farm_id, started_at desc);

alter table enrollment_sessions enable row level security;

drop policy if exists "enrollment_sessions_read" on enrollment_sessions;
create policy "enrollment_sessions_read" on enrollment_sessions
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  );

-- Открывает и закрывает сеанс хозяйство, отмечает набранное — устройство.
-- Обоим нужна запись, поэтому политика одна на всех, а проверки живут в
-- функциях ниже: там видно, что именно меняется и почему это можно
drop policy if exists "enrollment_sessions_write" on enrollment_sessions;
create policy "enrollment_sessions_write" on enrollment_sessions
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- Устройство должно уметь писать эталоны
-- ---------------------------------------------------------------------------
-- Прежняя политика разрешала запись только владельцу фермы и не имела
-- `with check` вовсе — а без него `for all using (...)` не пропускает
-- INSERT ни от кого. То есть эталоны, которые устройство копило само,
-- на самом деле не сохранялись. Записи с камеры это сломало бы сразу.

drop policy if exists "animal_embeddings_write" on animal_embeddings;
create policy "animal_embeddings_write" on animal_embeddings
  for all using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or farm_id = public.current_device_farm()
    or public.is_admin()
  );

-- ---------------------------------------------------------------------------
-- 3. Начать запись
-- ---------------------------------------------------------------------------
-- Заводит животное, если его ещё нет, и открывает сеанс. Две вещи в
-- одной функции намеренно: между «завёл» и «начал писать» не должно
-- быть состояния, в котором животное есть, а эталонов у него никогда
-- не появится.

create or replace function start_recording(
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

  insert into enrollment_sessions (farm_id, camera_id, animal_id)
  values (v_farm, target_camera_id, v_animal)
  returning id into v_session;

  return v_session;
end;
$$;

-- ---------------------------------------------------------------------------
-- 4. Эталон из живого кадра
-- ---------------------------------------------------------------------------
-- Зовёт устройство. Кадр уже отобран на его стороне: в кадре ровно одно
-- животное, оно не у края и не слиплось с соседом.

create or replace function add_recording_embedding(
  session_id uuid,
  new_embedding vector(1024)
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

-- ---------------------------------------------------------------------------
-- 5. Закончить и отменить
-- ---------------------------------------------------------------------------

create or replace function finish_recording(session_id uuid)
returns text
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
begin
  select * into v_row from enrollment_sessions where id = session_id;
  if v_row.id is null then
    raise exception 'Сеанс не найден';
  end if;

  if v_row.status <> 'recording' then
    return v_row.status;
  end if;

  -- Досрочная остановка при пустой записи — это отмена, а не успех.
  -- Иначе животное осталось бы «записанным» без единого эталона и
  -- молча никогда не узнавалось
  if v_row.captured = 0 then
    update enrollment_sessions
       set status = 'cancelled', finished_at = now()
     where id = session_id;
    return 'cancelled';
  end if;

  update enrollment_sessions
     set status = 'done', finished_at = now()
   where id = session_id;

  update animals set enrolled = true where id = v_row.animal_id;
  return 'done';
end;
$$;

create or replace function cancel_recording(session_id uuid)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_row enrollment_sessions;
begin
  select * into v_row from enrollment_sessions where id = session_id;
  if v_row.id is null then
    return;
  end if;

  update enrollment_sessions
     set status = 'cancelled', finished_at = now()
   where id = session_id and status = 'recording';

  -- Животное, заведённое ради этой записи и не набравшее ни одного
  -- эталона, удаляем. Иначе каждая передумка оставляет в списке пустую
  -- строку, и через месяц там сорок «Зорек», которых никто не заводил
  delete from animals a
   where a.id = v_row.animal_id
     and a.enrolled = false
     and not exists (select 1 from animal_embeddings e where e.animal_id = a.id)
     and not exists (select 1 from weighings w where w.animal_id = a.id);
end;
$$;

-- ---------------------------------------------------------------------------
-- 6. Записанное с камеры весит больше подтверждённого кадра
-- ---------------------------------------------------------------------------
-- Прежний вариант давал прибавку эталонам из фотографий. Их больше нет,
-- а прибавка должна достаться записи с камеры: она сделана заведомо с
-- этого животного, тогда как обычный кадр — лишь настолько, насколько
-- уверенно он был опознан.

create or replace function match_animal(
  query_embedding vector(1024),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5,
  target_view text default null
)
returns table (animal_id uuid, label text, distance real, margin real)
language sql
stable
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
    select
      s.*,
      lead(s.distance) over (order by s.distance) as runner_up
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

-- ---------------------------------------------------------------------------
-- 7. Что показывать и что забирать устройству
-- ---------------------------------------------------------------------------

-- security_invoker обязателен: без него вид выполняется от имени
-- владельца и обходит разграничение доступа — любое хозяйство видело бы
-- записи всех остальных
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
  s.started_at,
  s.expires_at
from enrollment_sessions s
join animals a on a.id = s.animal_id
where s.status = 'recording' and s.expires_at > now();

-- Сколько эталонов у животного и когда снят последний. По этому
-- в списке видно, готово ли животное к узнаванию
create or replace function animal_readiness(target_farm_id uuid)
returns table (
  animal_id uuid,
  embeddings integer,
  last_recorded_at timestamptz
)
language sql
stable
set search_path = public
as $$
  select
    e.animal_id,
    count(*)::integer,
    max(e.created_at)
  from animal_embeddings e
  where e.farm_id = target_farm_id
  group by e.animal_id
$$;

revoke all on function start_recording(uuid, text, uuid) from public;
revoke all on function add_recording_embedding(uuid, vector) from public;
revoke all on function finish_recording(uuid) from public;
revoke all on function cancel_recording(uuid) from public;
revoke all on function animal_readiness(uuid) from public;

grant execute on function start_recording(uuid, text, uuid) to authenticated;
grant execute on function add_recording_embedding(uuid, vector) to authenticated;
grant execute on function finish_recording(uuid) to authenticated;
grant execute on function cancel_recording(uuid) to authenticated;
grant execute on function animal_readiness(uuid) to authenticated;
grant select on active_recording to authenticated;
