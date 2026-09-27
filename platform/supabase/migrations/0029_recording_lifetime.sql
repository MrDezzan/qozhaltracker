-- ---------------------------------------------------------------------------
-- Запись живёт дольше и не исчезает молча
-- ---------------------------------------------------------------------------
-- Пять минут оказались нереально коротким сроком. Человек нажимает
-- «Добавить животное» у экрана, потом идёт к загону, выводит животное,
-- ставит его перед камерой — на это уходит больше пяти минут даже без
-- заминок. Сеанс к тому моменту уже закрыт.
--
-- Хуже другое: закрывался он молча. Полоса записи просто исчезала со
-- страницы, и понять, чем всё кончилось — набралось, отменилось,
-- истекло, — было неоткуда.

alter table enrollment_sessions
  alter column expires_at set default now() + interval '20 minutes';

update enrollment_sessions
   set expires_at = started_at + interval '20 minutes'
 where status = 'recording';

-- ---------------------------------------------------------------------------
-- Чем кончилась последняя запись
-- ---------------------------------------------------------------------------
-- Показывается на странице животных, пока человек не начнёт следующую.
-- Без этого единственным следом неудачной записи было животное без
-- эталонов в списке — и никакого объяснения.

create or replace function last_recording(target_farm_id uuid)
returns table (
  id uuid,
  label text,
  status text,
  captured integer,
  needed integer,
  hint text,
  finished_at timestamptz
)
language sql
stable
set search_path = public
as $$
  select s.id, a.label, s.status, s.captured, s.needed, s.hint, s.finished_at
  from enrollment_sessions s
  join animals a on a.id = s.animal_id
  where s.farm_id = target_farm_id
    and s.status <> 'recording'
    and s.finished_at > now() - interval '1 hour'
  order by s.finished_at desc
  limit 1
$$;

revoke all on function last_recording(uuid) from public;
grant execute on function last_recording(uuid) to authenticated;

-- Сеанс, у которого вышло время, должен закрываться сам, а не висеть
-- «идущим» до следующей попытки начать запись
create or replace function expire_recordings()
returns integer
language sql
security definer
set search_path = public
as $$
  with closed as (
    update enrollment_sessions
       set status = 'expired', finished_at = now()
     where status = 'recording' and expires_at < now()
    returning 1
  )
  select count(*)::integer from closed
$$;

revoke all on function expire_recordings() from public;
grant execute on function expire_recordings() to authenticated;
