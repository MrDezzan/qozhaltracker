"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { requireAdmin } from "../../../../lib/adminGuard";
import { isValidPolygon, polygonArea, ZONE_KIND_LABELS, ZoneKind } from "../../../../lib/zones";
import { этоUuid, изСписка } from "../../../../lib/validate";
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
  const rawPolygon = String(formData.get("polygon") ?? "");

  /*
    Вид зоны — по списку, а не как пришло.

    В соседнем файле app/zones/actions.ts проверка по списку есть, а
    здесь её не было: значение из формы уходило в базу как есть. Вид
    зоны решает, как считается визит (пауза 60 с у кормушки против 10 с
    у прохода), поэтому произвольная строка здесь не опечатка, а
    неверный учёт кормления.
  */
  const kind = изСписка<ZoneKind>(
    formData.get("kind"),
    Object.keys(ZONE_KIND_LABELS) as ZoneKind[]
  );

  if (!name || name.length > 120) {
    return { status: "error", message: "Укажите название зоны" };
  }
  if (!kind) {
    return { status: "error", message: "Выберите вид зоны" };
  }
  if (!этоUuid(farmId) || !этоUuid(cameraId)) {
    return { status: "error", message: "Камера указана неверно" };
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
      console.error("[zones] insert", error);
      return { status: "error", message: "Не удалось сохранить зону" };
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

  if (!этоUuid(farmId) || !этоUuid(zoneId)) return;

  const supabase = await getServerSupabase();
  await requireAdmin(supabase);
  await supabase.from("zones").delete().eq("id", zoneId).eq("farm_id", farmId);
  revalidatePath(`/admin/farms/${farmId}`);
}
