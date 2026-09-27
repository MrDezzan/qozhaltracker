-- Починка прав на загрузку эталонных фото.
-- Применять ПОСЛЕ 0018_drop_auto_crops.sql.
--
-- В 0017 политика на запись в хранилище была написана как
-- `for all using (...)` без `with check (...)`. Это не работает: USING
-- проверяет уже существующие строки (select, update, delete), а новые —
-- WITH CHECK. Без него загрузка файла отбивается по правам.
--
-- Тихо: браузер показывает отказ хранилища, по которому невозможно
-- догадаться, что дело в отсутствующем `with check`.
--
-- Файл нужен тем, кто уже применил 0017. На чистой базе исправление
-- уже внутри 0017, и эта миграция просто перезапишет то же самое.

drop policy if exists "animal_photos_storage_write" on storage.objects;
create policy "animal_photos_storage_write" on storage.objects
  for all using (
    bucket_id = 'animal-photos'
    and (
      (storage.foldername(name))[1] in (
        select id::text from farms where owner_user_id = auth.uid()
      )
      or public.is_admin()
    )
  )
  with check (
    bucket_id = 'animal-photos'
    and (
      (storage.foldername(name))[1] in (
        select id::text from farms where owner_user_id = auth.uid()
      )
      or public.is_admin()
    )
  );
