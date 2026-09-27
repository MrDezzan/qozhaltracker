-- Устройство само прописывает адрес своего видеопотока.
-- Применять ПОСЛЕ 0011_camera_placement.sql.
--
-- Живое видео у нас работало, но не включалось. Чтобы его получить, надо
-- было узнать адрес мини-ПК в сети, собрать руками ссылку с паролем и
-- вставить её в карточку камеры. Ни один клиент этого не сделает, да и
-- мы сами забывали — и живой просмотр оставался на одном кадре в секунду,
-- хотя весь тракт для настоящего видео был готов.
--
-- Устройство знает и свой адрес, и свой пароль. Пусть прописывает само.

create or replace function register_camera_stream(
  target_camera_id uuid,
  new_url text
)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_farm uuid;
begin
  select farm_id into v_farm from cameras where id = target_camera_id;

  if v_farm is null then
    raise exception 'Камера не найдена';
  end if;

  -- SECURITY DEFINER здесь обязателен: у устройства нет права на update
  -- камер, и давать его целиком не хочется — оно смогло бы переписать
  -- имя, расположение и адрес источника. Функция меняет ровно одно поле
  -- и только у камер своей фермы.
  if not (
    public.is_admin()
    or v_farm = public.current_device_farm()
  ) then
    raise exception 'Нет доступа к этой камере';
  end if;

  update cameras set stream_url = new_url where id = target_camera_id;
  return new_url;
end;
$$;

grant execute on function register_camera_stream(uuid, text) to authenticated;

comment on function register_camera_stream(uuid, text) is
  'Устройство фермы прописывает адрес своего потока. Адрес содержит '
  'пароль и наружу не отдаётся: дашборд проксирует поток через себя.';
