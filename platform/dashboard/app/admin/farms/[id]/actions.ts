"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { requireAdmin } from "../../../../lib/adminGuard";
import { DEFAULT_PLACEMENT, isPlacement } from "../../../../lib/cameras";
import { проверитьАдрес } from "../../../../lib/safeFetchUrl";
import { этоUuid } from "../../../../lib/validate";

/**
 * Текст ошибки базы наружу не отдаётся.
 *
 * В сообщении Postgres приезжают имена таблиц, колонок и ограничений —
 * готовая схема для того, кто её собирает. Человеку от этого текста
 * пользы нет, а разобраться нужно нам, поэтому подробности идут в
 * серверный журнал.
 */
function скрытьОшибку(где: string, ошибка: unknown, дляЧеловека: string): CameraActionState {
  console.error(`[admin/cameras] ${где}`, ошибка);
  return { status: "error", message: дляЧеловека };
}

export type CameraActionState = { status: "idle" } | { status: "error"; message: string };

export async function addCameraAction(
  _prev: CameraActionState,
  formData: FormData
): Promise<CameraActionState> {
  const farmId = String(formData.get("farmId") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const sourceUri = String(formData.get("sourceUri") ?? "").trim();
  const placementRaw = formData.get("placement");
  const placement = isPlacement(placementRaw) ? placementRaw : DEFAULT_PLACEMENT;
  const streamUrl = String(formData.get("streamUrl") ?? "").trim();

  if (!name || !sourceUri) {
    return { status: "error", message: "Заполните название и адрес потока" };
  }
  if (!этоUuid(farmId)) {
    return { status: "error", message: "Ферма указана неверно" };
  }
  if (name.length > 120 || sourceUri.length > 500 || streamUrl.length > 500) {
    return { status: "error", message: "Слишком длинное значение" };
  }
  if (streamUrl) {
    const проверка = await проверитьАдрес(streamUrl);
    if (!проверка.ok) {
      return { status: "error", message: `Адрес потока отклонён: ${проверка.причина}` };
    }
  }

  try {
    // Пишем клиентом пользователя: RLS сама проверит, что он админ.
    const supabase = await getServerSupabase();
    await requireAdmin(supabase);

    const { error } = await supabase
      .from("cameras")
      .insert({
        farm_id: farmId,
        name,
        source_uri: sourceUri,
        placement,
        stream_url: streamUrl || null,
      });

    if (error) {
      return скрытьОшибку("insert", error, "Не удалось добавить камеру");
    }

    revalidatePath(`/admin/farms/${farmId}`);
    return { status: "idle" };
  } catch (e) {
    return { status: "error", message: e instanceof Error ? e.message : String(e) };
  }
}

export async function deleteCameraAction(formData: FormData): Promise<void> {
  const farmId = String(formData.get("farmId") ?? "");
  const cameraId = String(formData.get("cameraId") ?? "");
  if (!этоUuid(farmId) || !этоUuid(cameraId)) return;

  const supabase = await getServerSupabase();
  await requireAdmin(supabase);
  await supabase.from("cameras").delete().eq("id", cameraId);
  revalidatePath(`/admin/farms/${farmId}`);
}


/**
 * Правка уже заведённой камеры.
 *
 * Камеры переставляют: перевесили с бока наверх — и обмер силуэта должен
 * включиться сам, без выезда и без запроса в базу.
 */
export async function updateCameraAction(
  _prev: CameraActionState,
  formData: FormData
): Promise<CameraActionState> {
  const farmId = String(formData.get("farmId") ?? "");
  const cameraId = String(formData.get("cameraId") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const placementRaw = formData.get("placement");
  const placement = isPlacement(placementRaw) ? placementRaw : DEFAULT_PLACEMENT;
  const streamUrl = String(formData.get("streamUrl") ?? "").trim();
  const securityEnabled = formData.get("securityEnabled") === "on";

  if (!name) {
    return { status: "error", message: "Название не может быть пустым" };
  }
  if (!этоUuid(farmId) || !этоUuid(cameraId)) {
    return { status: "error", message: "Камера указана неверно" };
  }
  if (name.length > 120 || streamUrl.length > 500) {
    return { status: "error", message: "Слишком длинное значение" };
  }
  if (streamUrl) {
    const проверка = await проверитьАдрес(streamUrl);
    if (!проверка.ok) {
      return { status: "error", message: `Адрес потока отклонён: ${проверка.причина}` };
    }
  }

  try {
    const supabase = await getServerSupabase();
    /*
      requireAdmin здесь не для красоты симметрии с соседними действиями.

      Серверное действие вызывается по собственному адресу и через
      app/admin/layout.tsx не проходит — проверка в разметке админки его
      не прикрывает. Без этой строки владелец фермы мог сам себе
      переписать stream_url (вход для SSRF) и выключить security_enabled,
      то есть снять охрану со своей камеры.
    */
    await requireAdmin(supabase);

    const { error } = await supabase
      .from("cameras")
      .update({
        name,
        placement,
        stream_url: streamUrl || null,
        security_enabled: securityEnabled,
      })
      .eq("id", cameraId);

    if (error) {
      return скрытьОшибку("update", error, "Не удалось сохранить");
    }

    revalidatePath(`/admin/farms/${farmId}`);
    revalidatePath("/");
    return { status: "idle" };
  } catch (e) {
    return { status: "error", message: e instanceof Error ? e.message : String(e) };
  }
}
