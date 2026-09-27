-- Threads: посты про боль фермера и короткие ответы под ними.
--
-- Публикуется БЕЗ одобрения владельца, поэтому проверка на выходе здесь
-- строже, чем в переписке: пост нельзя отменить следующим сообщением.
-- Логика и проверки — qozhal_manager/threads.py.
--
-- КОЛОНКИ ЗДЕСЬ И В manager/schema.sql ОБЯЗАНЫ СОВПАДАТЬ.

alter table channels drop constraint if exists channels_kind_check;
alter table channels add constraint channels_kind_check
  check (kind in ('telegram', 'whatsapp', 'instagram', 'threads'));

create table if not exists threads_posts (
  id          uuid primary key default gen_random_uuid(),
  text        text not null,
  pain        text not null default '',
  external_id text,
  posted_at   timestamptz not null default now()
);

create index if not exists threads_posts_fresh_idx
  on threads_posts (posted_at desc);

create table if not exists threads_replies (
  comment_id text primary key,
  author     text not null default '',
  post_id    text not null default '',
  answered   boolean not null default false,
  reason     text not null default '',
  seen_at    timestamptz not null default now()
);

alter table threads_posts enable row level security;
alter table threads_replies enable row level security;

drop policy if exists threads_posts_service on threads_posts;
create policy threads_posts_service on threads_posts
  for all to service_role using (true) with check (true);

drop policy if exists threads_replies_service on threads_replies;
create policy threads_replies_service on threads_replies
  for all to service_role using (true) with check (true);
