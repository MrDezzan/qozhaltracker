"use server";

import { getServerSupabase } from "../lib/supabaseServer";
import {
  remoteStreamEnabled,
  startRemoteStream,
  stopRemoteStream,
  type StreamSession,
} from "../lib/remoteStream";

/**
 * Открыть просмотр через интернет.
 *
 * Проверку прав делает база: `start_remote_stream` сама смотрит, чья это
 * камера. Дублировать её здесь не надо — второе место с правами однажды
 * разойдётся с первым.
 */
export async function startRemoteStreamAction(
  cameraId: string,
  seconds = 600
): Promise<{ session: StreamSession } | { error: string }> {
  if (!remoteStreamEnabled()) {
    return {
      error:
        "Просмотр через интернет не настроен: не задан адрес сервера видео.",
    };
  }

  const supabase = await getServerSupabase();
  const { data } = await supabase.auth.getSession();
  if (!data.session) {
    return { error: "Войдите заново" };
  }

  const session = await startRemoteStream(supabase, cameraId, seconds);
  if (!session) {
    return {
      error:
        "Ферма не открыла просмотр. Чаще всего это значит, что не применена " +
        "миграция 0013: без неё в базе нет самой таблицы сессий.",
    };
  }

  return { session };
}

/**
 * Закрыть досрочно.
 *
 * Вызывается, когда зритель закрыл окно. Без этого ферма продолжала бы
 * гнать поток до конца срока — то есть до десяти минут в никуда.
 */
export async function stopRemoteStreamAction(sessionId: string): Promise<void> {
  const supabase = await getServerSupabase();
  const { data } = await supabase.auth.getSession();
  if (!data.session) return;

  await stopRemoteStream(supabase, sessionId);
}
