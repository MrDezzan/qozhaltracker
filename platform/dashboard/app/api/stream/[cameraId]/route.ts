import { NextRequest } from "next/server";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { проверитьАдрес } from "../../../../lib/safeFetchUrl";
import { проверитьЧастоту, слишкомЧасто } from "../../../../lib/rateLimit";

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
  // getUser, а не getSession: getSession только читает cookie и подпись не
  // проверяет, то есть «вошёл» подделывается самодельным токеном
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) {
    return new Response("Не авторизован", { status: 401 });
  }

  /*
    Лимит здесь важнее, чем кажется: каждый запрос открывает новое
    исходящее соединение. Без ограничения один вошедший пользователь
    превращает наш сервер в сканер портов чужой сети и заодно исчерпывает
    сокеты. Двадцать просмотров в минуту с запасом покрывают живую работу.
  */
  const лимит = проверитьЧастоту(`stream:${userData.user.id}`, 20, 60_000);
  if (!лимит.можно) return слишкомЧасто(лимит.черезСекунд);

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

  /*
    Адрес проверяется ещё раз, хотя он уже проверен при записи в базу.

    Между записью и этим запросом запись в DNS могла поменяться: имя,
    которое вчера вело наружу, сегодня ведёт на 169.254.169.254. Это
    называется DNS rebinding, и единственная защита от него — проверять
    в момент обращения, а не в момент сохранения.
  */
  const проверка = await проверитьАдрес(camera.stream_url);
  if (!проверка.ok) {
    console.error("[stream] адрес камеры отклонён", {
      cameraId,
      причина: проверка.причина,
    });
    return new Response("Адрес потока недопустим", { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(проверка.url, {
      cache: "no-store",
      // Перенаправления не выполняем: 302 на внутренний адрес обошёл бы
      // всю проверку выше
      redirect: "manual",
      // Браузер закрыл вкладку — отпускаем и соединение с фермой,
      // иначе устройство продолжало бы кодировать кадры в никуда
      signal: request.signal,
    });
  } catch (e) {
    // Текст ошибки наружу не отдаём: «ECONNREFUSED 10.0.0.5:8080» — это
    // готовый ответ сканеру портов
    console.error("[stream] устройство недоступно", {
      cameraId,
      ошибка: e instanceof Error ? e.message : String(e),
    });
    return new Response("Устройство недоступно", { status: 502 });
  }

  if (upstream.status >= 300 && upstream.status < 400) {
    return new Response("Устройство отказало в потоке", { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response("Устройство отказало в потоке", { status: 502 });
  }

  /*
    Тип содержимого ставим свой, а не берём у устройства.

    Ответ отдаётся с нашего домена. Если устройство (а его адрес задаёт
    владелец фермы) вернёт text/html со скриптом, скрипт выполнится в
    нашем источнике и получит доступ к сессии того, кто открыл ссылку.
  */
  const типУстройства = upstream.headers.get("content-type") ?? "";
  const безопасныйТип = /^(image\/|video\/|multipart\/)/i.test(типУстройства)
    ? типУстройства
    : "multipart/x-mixed-replace; boundary=frame";

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": безопасныйТип,
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox; default-src 'none'",
      "Cache-Control": "no-store, no-cache, must-revalidate",
      // Соединение живёт минутами; посредники не должны его буферизовать
      "X-Accel-Buffering": "no",
    },
  });
}
