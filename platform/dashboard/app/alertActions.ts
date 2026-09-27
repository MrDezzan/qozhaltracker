"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../lib/supabaseServer";
import { requireFarmId } from "../lib/auth";
import { describeError } from "../lib/retry";
import { этоUuid } from "../lib/validate";
import { проверитьЧастоту } from "../lib/rateLimit";

export type ActionState =
  | { status: "idle" }
  | { status: "ok"; message: string }
  | { status: "error"; message: string };

/** «Видел, разбираюсь» — тревога остаётся открытой, но уходит вниз списка. */
export async function acknowledgeAlertAction(formData: FormData): Promise<void> {
  const alertId = String(formData.get("alertId") ?? "");
  if (!этоUuid(alertId)) return;

  const supabase = await getServerSupabase();
  const { data: sessionData } = await supabase.auth.getUser();
  if (!sessionData.user) return;

  /*
    Ферма проверяется здесь, а не только политикой в базе.

    Раньше опора была целиком на RLS: передай чужой alertId — обновится
    ноль строк, но действие вернёт «успех», и человек уйдёт с экрана в
    уверенности, что тревогу отработал. Ошибка тихая и потому неприятная.
  */
  const farmId = await requireFarmId(supabase);

  await supabase
    .from("alerts")
    .update({
      acknowledged_at: new Date().toISOString(),
      acknowledged_by: sessionData.user.id,
    })
    .eq("id", alertId)
    .eq("farm_id", farmId);

  revalidatePath("/");
  revalidatePath("/alerts");
}

/**
 * Ручной пересчёт отклонений.
 *
 * Обычно это делает расписание раз в десять минут. Кнопка нужна, когда
 * хозяин только что разобрался с происшествием и хочет сразу увидеть,
 * закрылась ли тревога, а не ждать очередного круга.
 */
export async function runDetectionAction(
  _prev: ActionState,
  _formData: FormData
): Promise<ActionState> {
  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    // Пересчёт отклонений — тяжёлый запрос. Кнопка нужна раз в несколько
    // минут, а не в цикле
    const лимит = проверитьЧастоту(`detect:${farmId}`, 5, 60_000);
    if (!лимит.можно) {
      return {
        status: "error",
        message: `Пересчёт уже шёл только что. Повторите через ${лимит.черезСекунд} с`,
      };
    }

    const { data, error } = await supabase.rpc("detect_farm_alerts", {
      target_farm_id: farmId,
    });
    if (error) {
      console.error("[alerts] detect_farm_alerts", error);
      return { status: "error", message: "Не удалось пересчитать отклонения" };
    }

    const row = Array.isArray(data) ? data[0] : data;
    const opened = row?.opened ?? 0;
    const resolved = row?.resolved ?? 0;

    revalidatePath("/");
    revalidatePath("/alerts");

    if (opened === 0 && resolved === 0) {
      return { status: "ok", message: "Ничего не изменилось" };
    }
    return {
      status: "ok",
      message: `Новых тревог: ${opened}, закрыто: ${resolved}`,
    };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

/**
 * Просьба к ферме отдавать кадры чаще.
 *
 * Живой просмотр включается по требованию, а не постоянно: канал на ферме
 * один на всё хозяйство, и держать ускоренный режим круглосуточно ради
 * пустого загона незачем.
 */
export async function requestLiveViewAction(
  cameraId: string,
  seconds = 60
): Promise<{ until: string } | { error: string }> {
  try {
    const supabase = await getServerSupabase();

    // Проверку «есть ли у вас своя ферма» здесь делать нельзя: администратор
    // смотрит чужие фермы и своей не имеет — запрос отбивался бы всегда.
    // Права проверяет сама база: изменить камеру может владелец или админ.
    const { data, error } = await supabase.rpc("request_live_view", {
      target_camera_id: cameraId,
      seconds,
    });
    if (error) {
      console.error("[alerts] live view", error);
      return { error: "Не удалось запросить просмотр" };
    }
    return { until: String(data) };
  } catch (e) {
    return { error: describeError(e) };
  }
}
