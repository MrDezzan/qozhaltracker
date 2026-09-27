-- Вырезанные кадры животных и векторы для распознавания особей.
-- Применять ПОСЛЕ 0005_fix_snapshot_policies.sql.

create extension if not exists vector;

-- Животные фермы получают кличку и связь с векторами
alter table animals add column if not exists notes text;
alter table animals add column if not exists photo_path text;

-- Один «след»: лучший кадр одного трека с вектором признаков.
-- Пока animal_id пуст — животное не опознано и ждёт имени от фермера.
create table if not exists sightings (
  id uuid primary key default gen_random_uuid(),
  farm_id uuid not null references farms(id) on delete cascade,
  camera_id uuid not null references cameras(id) on delete cascade,
  animal_id uuid references animals(id) on delete set null,
  track_id integer not null,
  crop_path text not null,
  -- MegaDescriptor-L отдаёт 1024 числа; для другой модели поменяется размерность
  embedding vector(1024),
  confidence real,
  occurred_at timestamptz not null default now()
);

create index if not exists sightings_farm_idx on sightings(farm_id);
create index if not exists sightings_animal_idx on sightings(animal_id);
create index if not exists sightings_occurred_idx on sightings(occurred_at desc);

-- Поиск ближайшего вектора по косинусному расстоянию
create index if not exists sightings_embedding_idx
  on sightings using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table sightings enable row level security;

create policy "sightings_read" on sightings
  for select using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
    or farm_id = public.current_device_farm()
  );

create policy "sightings_device_insert" on sightings
  for insert with check (
    farm_id = public.current_device_farm() or public.is_admin()
  );

-- Имя животному ставит владелец фермы или админ
create policy "sightings_name_update" on sightings
  for update using (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  )
  with check (
    farm_id in (select id from farms where owner_user_id = auth.uid())
    or public.is_admin()
  );

-- Владелец фермы должен уметь заводить животных, не только админ
drop policy if exists "animals_write" on animals;
create policy "animals_write" on animals
  for all using (
    public.is_admin()
    or farm_id = public.current_device_farm()
    or farm_id in (select id from farms where owner_user_id = auth.uid())
  )
  with check (
    public.is_admin()
    or farm_id = public.current_device_farm()
    or farm_id in (select id from farms where owner_user_id = auth.uid())
  );

-- Хранилище вырезанных кадров
insert into storage.buckets (id, name, public)
values ('crops', 'crops', false)
on conflict (id) do nothing;

drop policy if exists "crops_device_write" on storage.objects;
create policy "crops_device_write" on storage.objects
  for insert with check (
    bucket_id = 'crops'
    and (storage.foldername(name))[1]::uuid = public.current_device_farm()
  );

drop policy if exists "crops_read" on storage.objects;
create policy "crops_read" on storage.objects
  for select using (
    bucket_id = 'crops'
    and (
      public.is_admin()
      or (storage.foldername(name))[1]::uuid = public.current_device_farm()
      or (storage.foldername(name))[1]::uuid in (
        select id from public.farms where owner_user_id = auth.uid()
      )
    )
  );

drop policy if exists "crops_admin_delete" on storage.objects;
create policy "crops_admin_delete" on storage.objects
  for delete using (bucket_id = 'crops' and public.is_admin());

-- Поиск похожего животного среди уже названных.
-- SECURITY DEFINER не нужен: вызывающий и так видит только свою ферму.
create or replace function match_animal(
  query_embedding vector(1024),
  target_farm_id uuid,
  match_threshold real default 0.35,
  match_count integer default 5
)
returns table (animal_id uuid, label text, distance real)
language sql
stable
as $$
  select
    s.animal_id,
    a.label,
    (s.embedding <=> query_embedding)::real as distance
  from sightings s
  join animals a on a.id = s.animal_id
  where s.farm_id = target_farm_id
    and s.animal_id is not null
    and s.embedding is not null
    and (s.embedding <=> query_embedding) < match_threshold
  order by s.embedding <=> query_embedding
  limit match_count;
$$;
