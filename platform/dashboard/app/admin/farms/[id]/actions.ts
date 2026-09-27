"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { requireAdmin } from "../../../../lib/adminGuard";
import { DEFAULT_PLACEMENT, isPlacement } from "../../../../lib/cameras";

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
      return { status: "error", message: `Не удалось добавить камеру: ${error.message}` };
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

  try {
    const supabase = await getServerSupabase();
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
      return { status: "error", message: `Не удалось сохранить: ${error.message}` };
    }

    revalidatePath(`/admin/farms/${farmId}`);
    revalidatePath("/");
    return { status: "idle" };
  } catch (e) {
    return { status: "error", message: e instanceof Error ? e.message : String(e) };
  }
}
