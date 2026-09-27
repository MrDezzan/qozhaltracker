-- Личная лента: один заготовленный текст на несколько аккаунтов Threads.
--
-- Отдельно от `channels` и `threads_posts`: там рабочая лента Qozhal,
-- где бот сочиняет пост сам и проверяет его на цены и обещания. Здесь
-- текст пишет владелец, и трогать его нельзя. Общего у них только
-- «сходить в Threads API».
--
-- Повторный запуск безвреден: всё через `if not exists`.

create table if not exists feed_text (
  id         uuid primary key default gen_random_uuid(),
  body       text not null,
  created_at timestamptz not null default now()
);

create index if not exists feed_text_fresh_idx
  on feed_text (created_at desc);

create table if not exists feed_accounts (
  id            uuid primary key default gen_random_uuid(),
  username      text not null default '',
  account_id    text not null,
  secret_sealed text not null,
  secret_mark   text not null default '',
  on_air        boolean not null default true,
  last_error    text not null default '',
  connected_at  timestamptz not null default now(),
  unique (account_id)
);

create table if not exists feed_log (
  id          uuid primary key default gen_random_uuid(),
  account     uuid references feed_accounts (id) on delete cascade,
  external_id text not null default '',
  ok          boolean not null default false,
  error       text not null default '',
  posted_at   timestamptz not null default now()
);

create index if not exists feed_log_fresh_idx
  on feed_log (posted_at desc);

alter table feed_text enable row level security;
alter table feed_accounts enable row level security;
alter table feed_log enable row level security;

drop policy if exists feed_text_service on feed_text;
create policy feed_text_service on feed_text
  for all to service_role using (true) with check (true);

drop policy if exists feed_accounts_service on feed_accounts;
create policy feed_accounts_service on feed_accounts
  for all to service_role using (true) with check (true);

drop policy if exists feed_log_service on feed_log;
create policy feed_log_service on feed_log
  for all to service_role using (true) with check (true);
