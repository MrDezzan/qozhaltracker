"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { requireAdmin } from "../../../../lib/adminGuard";
import { isValidPolygon, polygonArea } from "../../../../lib/zones";
import { describeError } from "../../../../lib/retry";

export type ZoneActionState = { status: "idle" } | { status: "error"; message: string };

// Отсекает случайные тычки: зона меньше половины процента кадра
// почти наверняка промах, а не кормушка.
const MIN_AREA = 0.005;

export async function createZoneAction(
  _prev: ZoneActionState,
  formData: FormData
): Promise<ZoneActionState> {
  const farmId = String(formData.get("farmId") ?? "");
  const cameraId = String(formData.get("cameraId") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const kind = String(formData.get("kind") ?? "other");
  const rawPolygon = String(formData.get("polygon") ?? "");

  if (!name) {
    return { status: "error", message: "Укажите название зоны" };
  }

  let polygon: unknown;
  try {
    polygon = JSON.parse(rawPolygon);
  } catch {
    return { status: "error", message: "Обведите зону на снимке" };
  }

  if (!isValidPolygon(polygon)) {
    return { status: "error", message: "Нужно не меньше трёх точек внутри кадра" };
  }

  if (polygonArea(polygon) < MIN_AREA) {
    return { status: "error", message: "Зона слишком мелкая, обведите побольше" };
  }

  try {
    const supabase = await getServerSupabase();
    await requireAdmin(supabase);

    const { error } = await supabase
      .from("zones")
      .insert({ farm_id: farmId, camera_id: cameraId, name, kind, polygon });

    if (error) {
      return { status: "error", message: `Не удалось сохранить зону: ${error.message}` };
    }

    revalidatePath(`/admin/farms/${farmId}`);
    return { status: "idle" };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

export async function deleteZoneAction(formData: FormData): Promise<void> {
  const farmId = String(formData.get("farmId") ?? "");
  const zoneId = String(formData.get("zoneId") ?? "");

  const supabase = await getServerSupabase();
  await requireAdmin(supabase);
  await supabase.from("zones").delete().eq("id", zoneId);
  revalidatePath(`/admin/farms/${farmId}`);
}
