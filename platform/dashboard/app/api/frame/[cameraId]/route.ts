import { NextRequest } from "next/server";
import { проверитьЧастоту, слишкомЧасто } from "../../../../lib/rateLimit";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { SNAPSHOT_BUCKET, snapshotPath } from "../../../../lib/snapshots";

export const dynamic = "force-dynamic";

/**
 * Кадр с камеры через наш сервер, а не по прямой ссылке в хранилище.
 *
 * Так было не сразу. Сначала браузер ходил в хранилище сам по подписанной
 * ссылке — и получал не свежий кадр, а копию из сети доставки. Путь снимка
 * постоянный, файл перезаписывается раз в секунду, а сеть доставки об этом
 * не знает и держит своё. Ни метка в адресе, ни запрет кэша со стороны
 * браузера до неё не доходили.
 *
 * Здесь заголовками распоряжаемся мы: браузеру уходит явный запрет
 * кэширования, а до хранилища мы ходим сами, минуя его кэш меткой времени.
 *
 * Побочная выгода: наружу больше не уезжает долгоживущая подписанная
 * ссылка на файл — доступ проверяется на каждый кадр.
 */
export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ cameraId: string }> }
) {
  const { cameraId } = await context.params;

  const supabase = await getServerSupabase();
  /*
    getUser, а не getSession.

    getSession только читает cookie и разбирает JWT — подпись он на
    сервере не проверяет. То есть на вопрос «вошёл ли человек» он
    отвечает по содержимому cookie, а cookie пишет кто угодно.
    getUser спрашивает Supabase и получает ответ, которому можно верить.
  */
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) {
    return new Response("Не авторизован", { status: 401 });
  }

  /*
    Токен берём отдельно и только после проверки выше.

    Сам по себе он здесь не пропуск: хранилище всё равно проверит его и
    политики. Но решение «пускать или нет» принято по getUser, а не по
    содержимому cookie.
  */
  /*
    Интерфейс сам тянет кадр примерно раз в секунду на камеру, поэтому
    предел щедрый. Он не про обычную работу, а про цикл в скрипте:
    каждый кадр — это проксирование в хранилище за наш счёт.
  */
  const лимит = проверитьЧастоту(`frame:${userData.user.id}`, 180, 60_000);
  if (!лимит.можно) return слишкомЧасто(лимит.черезСекунд);

  const { data: sessionData } = await supabase.auth.getSession();
  const accessToken = sessionData.session?.access_token;
  if (!accessToken) {
    return new Response("Не авторизован", { status: 401 });
  }

  // Права проверяет база: чужая камера сюда просто не вернётся
  const { data: camera } = await supabase
    .from("cameras")
    .select("id, farm_id")
    .eq("id", cameraId)
    .maybeSingle();

  if (!camera) {
    return new Response("Камера не найдена", { status: 404 });
  }

  const path = snapshotPath(camera.farm_id, camera.id);
  const base = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!base || !key) {
    return new Response("Хранилище не настроено", { status: 500 });
  }

  // Метка времени в адресе обходит кэш на пути к хранилищу
  const target =
    `${base}/storage/v1/object/${SNAPSHOT_BUCKET}/${path}` + `?_=${Date.now()}`;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        apikey: key,
      },
      cache: "no-store",
    });
  } catch (e) {
    // Подробности — в журнал, наружу только факт. Текст сетевой ошибки
    // содержит адрес и порт хранилища
    console.error("[frame] хранилище недоступно", e);
    return new Response("Хранилище недоступно", { status: 502 });
  }

  if (!upstream.ok) {
    return new Response(
      upstream.status === 404 ? "Кадра ещё нет" : "Кадр не получен",
      { status: upstream.status === 404 ? 404 : 502 }
    );
  }

  const body = await upstream.arrayBuffer();

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "image/jpeg",
      // Запрет полный: путь постоянный, а содержимое меняется ежесекундно
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      // Возраст кадра нужен интерфейсу, чтобы отличить живой режим
      // от обычного — и сказать об этом человеку
      "Last-Modified":
        upstream.headers.get("last-modified") ?? new Date().toUTCString(),
      Date: new Date().toUTCString(),
    },
  });
}
