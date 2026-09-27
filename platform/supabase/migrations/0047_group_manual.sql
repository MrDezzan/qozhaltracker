-- Рабочая группа админов, тема на клиента и ручной режим.
--
-- Зачем. Бот зовёт человека, когда не может ответить сам. До сих пор он
-- слал карточку в личку владельца, и дальше владелец шёл в переписку с
-- клиентом руками. Теперь карточка уходит в общую группу, у неё кнопка
-- «Ответить», и ответ уходит клиенту от имени бота — без подписи, чтобы
-- клиент не разбирался, с кем он сейчас говорит.
--
-- КОЛОНКИ ЗДЕСЬ И В manager/schema.sql ОБЯЗАНЫ СОВПАДАТЬ. Разойдутся —
-- бот, отлаженный на локальной схеме, упадёт на боевой. Сверяет
-- manager/tests/test_schema.py.

alter table leads
  -- Тема в группе-форуме: у каждого клиента своя, чтобы через неделю
  -- переписка была разложена по людям, а не свалена в один поток
  add column if not exists topic_id bigint,
  -- Кто сейчас ведёт разговор. 'manual' — отвечает человек, и бот в
  -- этот разговор не лезет вовсе: иначе он ответит поверх живого
  -- менеджера, и клиент увидит две разные позиции подряд
  add column if not exists mode text not null default 'auto',
  -- До какого времени держится ручной режим. Без срока все клиенты
  -- однажды окажутся в manual навсегда, бот замолчит, и отличить это от
  -- «никто не пишет» будет нельзя
  add column if not exists manual_until timestamptz,
  -- Клиента уже позвали, карточка в теме висит и ждёт ответа
  add column if not exists handoff_open boolean not null default false;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'leads_mode_check'
  ) then
    alter table leads
      add constraint leads_mode_check check (mode in ('auto', 'manual'));
  end if;
end $$;

-- Мелкие настройки, которые заводятся из чата, а не из .env: id рабочей
-- группы, например. В .env их держать нельзя — тогда привязка группы
-- требовала бы правки файла на сервере и перезапуска.
create table if not exists settings (
  key        text primary key,
  value      text not null,
  updated_at timestamptz not null default now()
);

alter table settings enable row level security;

-- Читать и писать может только служебная роль. Настройки боевые: в них
-- лежит адрес группы, куда уходит вся клиентская переписка
drop policy if exists settings_service_only on settings;
create policy settings_service_only on settings
  for all to service_role using (true) with check (true);
