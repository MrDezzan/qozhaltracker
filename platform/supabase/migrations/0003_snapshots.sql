-- Снимки с камер для предпросмотра в интерфейсе.
-- Применять ПОСЛЕ 0002_roles_and_devices.sql.
--
-- Видеопоток в облако не идёт принципиально: одна камера — это ~2 Мбит/с
-- круглосуточно, чего сельский интернет не выдержит. Вместо этого
-- устройство раз в N секунд кладёт один кадр с нарисованными рамками.
-- Файл перезаписывается по фиксированному пути, поэтому объём хранилища
-- не растёт со временем: одна камера — один файл.

insert into storage.buckets (id, name, public)
values ('snapshots', 'snapshots', false)
on conflict (id) do nothing;

-- Путь снимка: {farm_id}/{camera_id}.jpg
-- Функции вызываются с указанием схемы: политики на storage.objects
-- выполняются в контексте схемы storage, где public в пути поиска нет.
-- storage.foldername(name) разбивает путь, первый элемент — id фермы.

drop policy if exists "snapshots_device_write" on storage.objects;
create policy "snapshots_device_write" on storage.objects
  for insert with check (
    bucket_id = 'snapshots'
    and (storage.foldername(name))[1]::uuid = public.current_device_farm()
  );

drop policy if exists "snapshots_device_update" on storage.objects;
create policy "snapshots_device_update" on storage.objects
  for update using (
    bucket_id = 'snapshots'
    and (storage.foldername(name))[1]::uuid = public.current_device_farm()
  );

drop policy if exists "snapshots_read" on storage.objects;
create policy "snapshots_read" on storage.objects
  for select using (
    bucket_id = 'snapshots'
    and (
      public.is_admin()
      or (storage.foldername(name))[1]::uuid = public.current_device_farm()
      or (storage.foldername(name))[1]::uuid in (
        select id from public.farms where owner_user_id = auth.uid()
      )
    )
  );

drop policy if exists "snapshots_admin_delete" on storage.objects;
create policy "snapshots_admin_delete" on storage.objects
  for delete using (bucket_id = 'snapshots' and public.is_admin());
