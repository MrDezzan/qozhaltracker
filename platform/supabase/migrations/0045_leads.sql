-- 0045: клиенты из переписки — лиды, сообщения, расчёты
--
-- Под ИИ-менеджера, который ведёт Instagram Direct и WhatsApp.
-- Устройство разобрано в docs/MENEDZHER.md.
--
-- Три решения, которые тут зафиксированы.
--
-- 1. Расчёты хранятся ИСТОРИЕЙ, а не перезаписью. Клиент говорит
--    «двести голов», через месяц «четыреста» — нужны оба, иначе не
--    видно, что изменилось и почему выросла смета.
--
-- 2. Переписка это персональные данные. Держать внутри Казахстана, как
--    и видео с людьми.
--
-- 3. Лиды видит только админ. Ферма не должна видеть чужие переписки,
--    а менеджер бота — данные ферм. Это разные роли.

create table if not exists leads (
  id           uuid primary key default gen_random_uuid(),
  channel      text not null check (channel in ('telegram', 'instagram', 'whatsapp')),
  -- id собеседника в этом канале. Пара «канал + внешний id» уникальна:
  -- один и тот же номер в WhatsApp это один лид, сколько бы раз он
  -- ни писал
  external_id  text not null,
  display_name text,
  -- Ответы анкеты как есть. Схема тут нарочно свободная: вопросы будут
  -- меняться, а миграция на каждое изменение анкеты — это дорого
  answers      jsonb not null default '{}'::jsonb,
  status       text not null default 'new'
               check (status in ('new', 'asking', 'ready', 'handoff', 'closed')),
  -- Почему передали человеку. По этому полю потом видно, каких ответов
  -- боту не хватает — это главный источник его улучшения
  handoff_topic text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (channel, external_id)
);

create index if not exists leads_status_idx on leads (status, updated_at desc);

create table if not exists lead_messages (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references leads (id) on delete cascade,
  -- Кто сказал. 'manager' это живой человек, писавший вручную: его
  -- ответы отличать от ботовых обязательно, иначе не понять, чему учить
  author     text not null check (author in ('client', 'bot', 'manager')),
  body       text not null,
  -- Если бот смолчал, здесь причина. Пусто у обычных сообщений
  gate_topic text,
  created_at timestamptz not null default now()
);

create index if not exists lead_messages_lead_idx
  on lead_messages (lead_id, created_at);

create table if not exists lead_quotes (
  id         uuid primary key default gen_random_uuid(),
  lead_id    uuid not null references leads (id) on delete cascade,
  -- Ответы, по которым считали. Снимок, а не ссылка на leads.answers:
  -- ответы поменяются, а расчёт должен остаться объяснимым
  answers    jsonb not null,
  races      integer not null,
  cams_race  integer not null,
  cams_pens  integer not null,
  cams_guard integer not null,
  cams_total integer not null,
  computers  integer not null,
  created_at timestamptz not null default now()
);

create index if not exists lead_quotes_lead_idx
  on lead_quotes (lead_id, created_at desc);

-- ------------------------------------------------------------- доступ

alter table leads enable row level security;
alter table lead_messages enable row level security;
alter table lead_quotes enable row level security;

-- Политики пересоздаются целиком: повторный запуск миграции не должен
-- падать с «policy already exists»
drop policy if exists leads_admin_all on leads;
drop policy if exists lead_messages_admin_all on lead_messages;
drop policy if exists lead_quotes_admin_all on lead_quotes;

create policy leads_admin_all on leads
  for all using (is_admin()) with check (is_admin());

create policy lead_messages_admin_all on lead_messages
  for all using (is_admin()) with check (is_admin());

create policy lead_quotes_admin_all on lead_quotes
  for all using (is_admin()) with check (is_admin());

-- Бот ходит не под пользователем, а сервисным ключом на своём VPS, и
-- RLS его не касается. Политики выше — для людей в админке.

create or replace function touch_lead_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists leads_touch on leads;
create trigger leads_touch
  before update on leads
  for each row execute function touch_lead_updated_at();
