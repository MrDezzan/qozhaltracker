-- ---------------------------------------------------------------------------
-- Запоминаем больше ракурсов, чем показываем
-- ---------------------------------------------------------------------------
-- Двенадцать ракурсов — это то, после чего животное уже узнаётся, и
-- ровно столько человек видит на экране: дальше полоса заполнена, и
-- можно уводить.
--
-- Но узнавание тем надёжнее, чем больше разных положений записано:
-- голова опущена, животное отвернулось, отошло дальше, встало против
-- света. Поэтому пока оно ещё в кадре, запись продолжается молча до
-- двадцати.
--
-- Почему не показать сразу двадцать. Человек стоит и ждёт, когда можно
-- уйти. Двадцать он будет добирать те же лишние полминуты, а разницы
-- для него никакой: животное узнаётся уже на двенадцати. Лишние
-- ракурсы — подарок, а не обязанность.

alter table enrollment_sessions
  add column if not exists target integer not null default 20;

comment on column enrollment_sessions.needed is
  'Сколько ракурсов показываем человеку: после стольких животное уже узнаётся';
comment on column enrollment_sessions.target is
  'Сколько на самом деле набираем, пока животное в кадре';

update enrollment_sessions
   set target = greatest(target, needed)
 where target < needed;

-- ---------------------------------------------------------------------------
-- Запись закрывается на target, а годным животное считается на needed
-- ---------------------------------------------------------------------------

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

  -- Годным животное становится раньше, чем запись заканчивается: если
  -- человек уведёт его на четырнадцати, узнавание уже работает
  if v_row.captured >= v_row.needed then
    update animals set enrolled = true where id = v_row.animal_id;
  end if;

  if v_row.captured >= greatest(v_row.target, v_row.needed) then
    update enrollment_sessions
       set status = 'done', finished_at = now()
     where id = session_id;
  end if;

  return v_row.captured;
end;
$$;

grant execute on function add_recording_embedding(uuid, vector) to authenticated;

-- Интерфейсу нужны оба числа: одно рисует полосу, второе объясняет,
-- почему запись ещё идёт при заполненной полосе
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
  s.hint,
  s.started_at,
  s.expires_at
from enrollment_sessions s
join animals a on a.id = s.animal_id
where s.status = 'recording' and s.expires_at > now();

grant select on active_recording to authenticated;
