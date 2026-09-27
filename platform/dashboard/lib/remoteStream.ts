import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Живое видео через интернет.
 *
 * Локальный поток остаётся и работает лучше: в сети фермы кадры идут прямо
 * с мини-ПК, без облака и без задержки. Но снаружи до фермы не достучаться —
 * у неё нет белого адреса, — и поток картинками туда всё равно не влез бы:
 * пятнадцать кадров это больше восьми мегабит в секунду.
 *
 * Поэтому наружу ферма отдаёт сама: подключается к серверу ретрансляции и
 * шлёт готовый H.264 прямо с камеры. Около 400 кбит/с — в двадцать раз
 * меньше, и никакого перекодирования.
 */

export type StreamSession = {
  id: string;
  cameraId: string;
  /** Случайный путь на сервере ретрансляции — не идентификатор камеры */
  path: string;
  expiresAt: string;
};

/** Адрес сервера ретрансляции для браузера. Пусто — режим выключен. */
export function relayPublicUrl(): string {
  return (process.env.NEXT_PUBLIC_RELAY_URL ?? "").trim().replace(/\/$/, "");
}

export function remoteStreamEnabled(): boolean {
  return relayPublicUrl().length > 0;
}

/** Куда браузер идёт за видео по WebRTC. */
export function whepUrl(path: string): string {
  return `${relayPublicUrl()}/${path}/whep`;
}

/**
 * Запасной путь, когда WebRTC не проходит.
 *
 * WebRTC работает по UDP, а в части корпоративных и мобильных сетей UDP
 * закрыт наглухо. LL-HLS идёт по обычному HTTPS и работает везде; задержка
 * 2–4 секунды вместо секунды. Хуже, но лучше чёрного экрана.
 */
export function hlsUrl(path: string): string {
  return `${relayPublicUrl()}/${path}/index.m3u8`;
}

type SessionRow = {
  id: string;
  camera_id: string;
  path: string;
  expires_at: string;
};

function toSession(row: SessionRow): StreamSession {
  return {
    id: row.id,
    cameraId: row.camera_id,
    path: row.path,
    expiresAt: row.expires_at,
  };
}

/**
 * Открывает сессию просмотра.
 *
 * Длительность ограничена сверху в самой базе: вкладку забывают открытой,
 * и без потолка ферма отдавала бы поток сутками ради картинки, на которую
 * никто не смотрит.
 */
export async function startRemoteStream(
  client: SupabaseClient,
  cameraId: string,
  seconds = 600
): Promise<StreamSession | null> {
  const { data, error } = await client.rpc("start_remote_stream", {
    target_camera_id: cameraId,
    seconds,
  });

  if (error || !data) return null;
  const row = (Array.isArray(data) ? data[0] : data) as SessionRow | undefined;
  return row ? toSession(row) : null;
}

/** Закрывает сессию досрочно: вкладку закрыли — незачем держать поток. */
export async function stopRemoteStream(
  client: SupabaseClient,
  sessionId: string
): Promise<void> {
  await client.rpc("stop_remote_stream", { target_session_id: sessionId });
}

/** Сколько секунд осталось. Ноль означает, что поток уже погас. */
export function secondsLeft(session: StreamSession, now: Date = new Date()): number {
  const left = (new Date(session.expiresAt).getTime() - now.getTime()) / 1000;
  return left > 0 ? Math.floor(left) : 0;
}

/**
 * Пора ли предупредить, что просмотр вот-вот закончится.
 *
 * Видео, погасшее без предупреждения, читается как поломка. Предупреждённое
 * за минуту — как правило работы.
 */
export function isEndingSoon(
  session: StreamSession,
  now: Date = new Date(),
  warnSeconds = 60
): boolean {
  const left = secondsLeft(session, now);
  return left > 0 && left <= warnSeconds;
}

/**
 * Разбор пути из адреса подключения, который прислал сервер ретрансляции.
 *
 * Он приходит в виде `/<путь>/whip` или `/<путь>/whep`, иногда с завершающим
 * слэшем и параметрами запроса. Разбирать это на месте в обработчике —
 * верный способ однажды пропустить чужой путь.
 */
export function pathFromRelayRequest(rawPath: string): string | null {
  const withoutQuery = rawPath.split("?")[0];
  const parts = withoutQuery.split("/").filter((part) => part.length > 0);
  if (parts.length === 0) return null;

  const last = parts[parts.length - 1];
  const candidate =
    last === "whip" || last === "whep" || last.endsWith(".m3u8") || last.endsWith(".mp4")
      ? parts[parts.length - 2]
      : last;

  if (!candidate) return null;
  // Путь сессии — 32 шестнадцатеричных знака из gen_random_bytes(16).
  // Проверка формата отсекает и опечатки, и попытки подставить своё.
  return /^[0-9a-f]{32}$/.test(candidate) ? candidate : null;
}
