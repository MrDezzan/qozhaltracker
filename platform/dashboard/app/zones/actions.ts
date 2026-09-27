"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { isValidPolygon, polygonArea, ZONE_KIND_LABELS, ZoneKind } from "../../lib/zones";
import { describeError } from "../../lib/retry";
import { validateCalibration } from "../../lib/calibration";

export type ZoneActionState = { status: "idle" } | { status: "error"; message: string };

/**
 * Зоны, которые размечает само хозяйство.
 *
 * Отдельно от админского варианта в `app/admin/farms/[id]/zoneActions.ts`,
 * и это не дублирование ради дублирования: там проверяется право
 * администратора, здесь — принадлежность фермы. Свести их в одну функцию
 * с флагом «кто вызвал» — верный способ однажды пропустить проверку.
 */

// Отсекает случайные тычки: зона меньше половины процента кадра
// почти наверняка промах, а не кормушка.
const MIN_AREA = 0.005;

function refresh() {
  revalidatePath("/zones");
  revalidatePath("/");
}

export async function createFarmZoneAction(
  _prev: ZoneActionState,
  formData: FormData
): Promise<ZoneActionState> {
  const cameraId = String(formData.get("cameraId") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const kind = String(formData.get("kind") ?? "feeder");
  const rawPolygon = String(formData.get("polygon") ?? "");

  if (!name) return { status: "error", message: "Укажите название зоны" };
  if (!(kind in ZONE_KIND_LABELS)) {
    return { status: "error", message: "Выберите тип зоны" };
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
    return {
      status: "error",
      message: "Зона слишком мелкая, обведите побольше",
    };
  }

  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    // Камера должна принадлежать этой же ферме. Политики базы это и так
    // не пропустят, но сообщение от них человеку ничего не скажет
    const { data: camera } = await supabase
      .from("cameras")
      .select("id")
      .eq("id", cameraId)
      .eq("farm_id", farmId)
      .maybeSingle();

    if (!camera) {
      return { status: "error", message: "Камера не найдена" };
    }

    const { error } = await supabase.from("zones").insert({
      farm_id: farmId,
      camera_id: cameraId,
      name,
      kind: kind as ZoneKind,
      polygon,
    });

    if (error) {
      console.error("[zones] save", error);
      return { status: "error", message: "Не удалось сохранить зону" };
    }

    refresh();
    return { status: "idle" };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

/**
 * Удаление зоны.
 *
 * Накопленные визиты при этом остаются: они записаны в события со своими
 * названием и типом зоны на момент визита. Стирать историю кормлений
 * из-за того, что кормушку переставили, было бы неверно.
 */
export async function deleteFarmZoneAction(formData: FormData): Promise<void> {
  const zoneId = String(formData.get("zoneId") ?? "");

  const supabase = await getServerSupabase();
  const farmId = await requireFarmId(supabase);

  await supabase.from("zones").delete().eq("id", zoneId).eq("farm_id", farmId);
  refresh();
}

export type CalibrationState =
  | { status: "ok"; scale: number }
  | { status: "error"; message: string };

/**
 * Калибровка камеры: сколько сантиметров в пикселе.
 *
 * Через функцию базы, а не прямым update: она проверяет правдоподобие
 * масштаба. Перепутанные местами сантиметры и пиксели дают корову
 * длиной четыре метра, и такое лучше отбить сразу.
 */
export async function calibrateCameraAction(
  cameraId: string,
  realLengthCm: number,
  pixelLength: number
): Promise<CalibrationState> {
  const problem = validateCalibration(realLengthCm, pixelLength);
  if (problem) return { status: "error", message: problem };

  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { data: camera } = await supabase
      .from("cameras")
      .select("id")
      .eq("id", cameraId)
      .eq("farm_id", farmId)
      .maybeSingle();

    if (!camera) return { status: "error", message: "Камера не найдена" };

    const { data, error } = await supabase.rpc("calibrate_camera", {
      target_camera_id: cameraId,
      real_length_cm: realLengthCm,
      pixel_length: pixelLength,
    });

    if (error) {
      console.error("[zones] сохранение", error);
      return { status: "error", message: "Не удалось сохранить" };
    }

    refresh();
    return { status: "ok", scale: Number(data) };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}
