-- Чему бот научился у человека.
--
-- Позвали человека, человек ответил — пара «вопрос → ответ» ложится
-- сюда. На похожий вопрос бот отвечает сам, словами владельца, и звать
-- больше не надо.
--
-- Заслонка запрещает боту ВЫДУМЫВАТЬ. Выученный ответ — не выдумка, это
-- то, что владелец сказал сам, глядя на этот самый вопрос. Поэтому урок
-- может открыть тему, которую заслонка закрыла.
--
-- Но не любую: деньги, гарантии, диагноз и недовольство остаются за
-- человеком навсегда. Список живёт в qozhal_manager/memory.py,
-- NEVER_REUSE.
--
-- КОЛОНКИ ЗДЕСЬ И В manager/schema.sql ОБЯЗАНЫ СОВПАДАТЬ.

create table if not exists lessons (
  id         uuid primary key default gen_random_uuid(),
  question   text not null,
  answer     text not null,
  topic      text not null default '',
  lead_id    uuid references leads (id) on delete set null,
  used       integer not null default 0,
  active     boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists lessons_fresh_idx
  on lessons (active, created_at desc);

alter table lessons enable row level security;

-- Уроки собраны из клиентской переписки, то есть содержат чужие слова.
-- Читает и пишет только служебная роль
drop policy if exists lessons_service_only on lessons;
create policy lessons_service_only on lessons
  for all to service_role using (true) with check (true);
