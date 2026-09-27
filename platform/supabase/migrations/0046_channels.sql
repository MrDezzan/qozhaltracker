-- 0046: подключённые каналы менеджера
--
-- Панель в Телеграме подключает каналы: свой Телеграм-бот, WhatsApp,
-- Instagram. Здесь хранится, что подключено и чем оно авторизуется.
--
-- Три решения, зафиксированные тут.
--
-- 1. СЕКРЕТ ЛЕЖИТ ШИФРОТЕКСТОМ. Ключ живёт в переменной окружения на том
--    же сервере, так что от человека с доступом к серверу это не спасает,
--    и делать вид, что спасает, нельзя. Спасает от резервных копий,
--    дампов базы, случайного коммита и скриншота таблицы — то есть от
--    того, как секреты утекают на самом деле.
--
-- 2. РЯДОМ ЛЕЖИТ ОТПЕЧАТОК И МАСКА. По ним панель показывает «тот же
--    токен или уже другой», не расшифровывая. Расшифровка нужна только
--    мосту в момент подключения.
--
-- 3. ОДИН КАНАЛ ОДНОГО ВИДА. Два Телеграм-менеджера на одну ферму — это
--    два бота, отвечающих одному клиенту, то есть удвоенные ответы.
--    Уникальность по виду канала, а не по строке.

create table if not exists channels (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null check (kind in ('telegram', 'whatsapp', 'instagram')),

  -- Как показывать человеку: @имя_бота или +7700…. Не секрет
  display       text not null default '',

  -- Токен, ключ доступа или что канал требует. ШИФРОТЕКСТ, не открытый
  -- текст. Кладётся только через qozhal_manager.secrets_box.seal()
  secret_sealed text,

  -- Первые 12 знаков sha256 от секрета. По ним видно, сменился ли он,
  -- без расшифровки и без показа
  secret_mark   text,

  -- Живой ли канал. Выключение не удаляет секрет: канал часто выключают
  -- на день, а вводить токен заново каждый раз — повод не выключать
  -- вовсе, когда надо
  active        boolean not null default false,

  -- Что канал сам о себе сообщил при подключении: имя бота, номер,
  -- id страницы. Без секретов
  meta          jsonb not null default '{}'::jsonb,

  last_error    text,
  connected_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  unique (kind)
);

-- Кто имеет право открывать панель. Пустая таблица означает ЗАКРЫТО, а
-- не «пускать всех»: при опечатке в настройках «пускать всех» отдаёт
-- панель первому встречному, а «закрыто» просто перестаёт работать, и об
-- этом сразу узнают
create table if not exists panel_admins (
  chat_id    text primary key,
  note       text not null default '',
  added_at   timestamptz not null default now()
);

alter table channels enable row level security;
alter table panel_admins enable row level security;

drop policy if exists channels_admin_all on channels;
drop policy if exists panel_admins_admin_all on panel_admins;

create policy channels_admin_all on channels
  for all using (is_admin()) with check (is_admin());

create policy panel_admins_admin_all on panel_admins
  for all using (is_admin()) with check (is_admin());

drop trigger if exists channels_touch on channels;
create trigger channels_touch
  before update on channels
  for each row execute function touch_lead_updated_at();
