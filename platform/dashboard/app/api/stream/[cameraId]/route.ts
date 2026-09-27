import { NextRequest } from "next/server";
import { getServerSupabase } from "../../../../lib/supabaseServer";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * Видео с камеры фермы — настоящее, а не по кадру в секунду.
 *
 * Кадры через хранилище упираются в физику: пятнадцать кадров в секунду
 * это около семи мегабит с одной камеры, и каждый кадр пришлось бы
 * записать в хранилище и оттуда прочитать. Для просмотра это бессмысленный
 * крюк.
 *
 * Поэтому здесь мы просто пробрасываем поток с самого устройства. Наш
 * сервер держит одно соединение с фермой и раздаёт его браузеру. Работает,
 * пока сервер видит устройство: на одной машине, в одной сети, через
 * туннель. Если не видит — интерфейс сам вернётся к отдельным кадрам.
 *
 * Пароль к потоку остаётся на сервере и в браузер не попадает.
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ cameraId: string }> }
) {
  const { cameraId } = await context.params;

  const supabase = await getServerSupabase();
  const { data: sessionData } = await supabase.auth.getSession();
  if (!sessionData.session) {
    return new Response("Не авторизован", { status: 401 });
  }

  // Права проверяет база: чужая камера сюда не вернётся
  const { data: camera } = await supabase
    .from("cameras")
    .select("id, stream_url")
    .eq("id", cameraId)
    .maybeSingle();

  if (!camera) {
    return new Response("Камера не найдена", { status: 404 });
  }
  if (!camera.stream_url) {
    return new Response("Поток для этой камеры не настроен", { status: 404 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(camera.stream_url, {
      cache: "no-store",
      // Браузер закрыл вкладку — отпускаем и соединение с фермой,
      // иначе устройство продолжало бы кодировать кадры в никуда
      signal: request.signal,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return new Response(`Устройство недоступно: ${message}`, { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response("Устройство отказало в потоке", { status: 502 });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ??
        "multipart/x-mixed-replace; boundary=frame",
      "Cache-Control": "no-store, no-cache, must-revalidate",
      // Соединение живёт минутами; посредники не должны его буферизовать
      "X-Accel-Buffering": "no",
    },
  });
}
