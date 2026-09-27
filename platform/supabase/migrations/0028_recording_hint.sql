-- ---------------------------------------------------------------------------
-- Почему счётчик записи стоит на месте
-- ---------------------------------------------------------------------------
-- Человек стоит перед камерой и видит одно число. Если оно не растёт,
-- он не знает ничего: то ли система его не видит, то ли он слишком
-- далеко, то ли рядом кто-то ещё. Молчащий счётчик — худшее, что может
-- быть в этом месте: попробовать нечего, и остаётся только уйти.
--
-- Устройство знает причину точно. Пусть говорит.

alter table enrollment_sessions
  add column if not exists hint text;

comment on column enrollment_sessions.hint is
  'Почему кадры сейчас не берутся. Пусто — берутся нормально';

create or replace function set_recording_hint(session_id uuid, new_hint text)
returns void
language sql
security invoker
set search_path = public
as $$
  update enrollment_sessions
     set hint = nullif(trim(coalesce(new_hint, '')), '')
   where id = session_id and status = 'recording';
$$;

-- Подсказка нужна и в том, что читает интерфейс
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
  s.hint,
  s.started_at,
  s.expires_at
from enrollment_sessions s
join animals a on a.id = s.animal_id
where s.status = 'recording' and s.expires_at > now();

revoke all on function set_recording_hint(uuid, text) from public;
grant execute on function set_recording_hint(uuid, text) to authenticated;
grant select on active_recording to authenticated;
