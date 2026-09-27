import { NextRequest } from "next/server";
import "server-only";
import { getAdminSupabase } from "../../../lib/supabaseAdmin";
import { pathFromRelayRequest } from "../../../lib/remoteStream";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * Разрешение на подключение к серверу ретрансляции.
 *
 * Сервер ретрансляции своих списков доступа не ведёт — он на каждое
 * подключение спрашивает здесь. Так право смотреть камеры остаётся там, где
 * ему место: в основной базе с её политиками. Заведи мы второй список в
 * настройках медиа-сервера, он однажды разъехался бы с первым, и разъехался
 * бы не в ту сторону.
 *
 * Отвечаем строго: 200 — можно, 401 — нельзя. Никаких подробностей в теле:
 * по разнице ответов подбирают пути.
 */
export async function POST(request: NextRequest) {
  // Свой ли это сервер. Без проверки на этот обработчик мог бы стучаться
  // кто угодно и перебирать пути
  const expected = process.env.RELAY_AUTH_SECRET ?? "";
  if (!expected) {
    console.error("RELAY_AUTH_SECRET не задан: проверка доступа отключена бы");
    return new Response("Не настроено", { status: 500 });
  }
  if (request.headers.get("x-relay-secret") !== expected) {
    return new Response("Нельзя", { status: 401 });
  }

  let body: { path?: string; action?: string };
  try {
    body = await request.json();
  } catch {
    return new Response("Нельзя", { status: 401 });
  }

  const path = pathFromRelayRequest(String(body.path ?? ""));
  if (!path) {
    return new Response("Нельзя", { status: 401 });
  }

  // Сервисным ключом: у сервера ретрансляции нет и не может быть
  // пользовательской сессии. Знание случайного пути и есть пропуск,
  // а живёт он минуты.
  const admin = getAdminSupabase();
  const { data, error } = await admin.rpc("stream_path_is_live", {
    check_path: path,
  });

  if (error || data !== true) {
    return new Response("Нельзя", { status: 401 });
  }

  return new Response("ok", { status: 200 });
}
