-- Исправление политик доступа к снимкам.
-- Применять ПОСЛЕ 0004_zones.sql.
--
-- В 0003 функции вызывались без указания схемы: is_admin(), current_device_farm().
-- Политики на storage.objects выполняются в контексте схемы storage, где эти
-- имена не разрешаются, и загрузка снимка падала с отказом в доступе.
-- Ниже те же политики, но с полными именами public.*

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
  )
  with check (
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

-- Функции должны быть доступны роли, под которой работает устройство
grant execute on function public.current_device_farm() to authenticated;
grant execute on function public.is_admin() to authenticated;
