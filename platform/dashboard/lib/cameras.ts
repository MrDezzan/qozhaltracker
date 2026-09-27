import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Расположение камеры.
 *
 * Это не косметика: от того, как повешена камера, зависит, что с неё вообще
 * можно снять. Сверху видно спину целиком — отсюда обмер силуэта и честный
 * подсчёт голов. Сбоку животные перекрывают друг друга, зато видно морду и
 * позу — отсюда зоны и распознавание особей. Обзорная камера смотрит на
 * территорию и годится только для охраны.
 */
export const PLACEMENTS = ["overhead", "side", "wide"] as const;
export type Placement = (typeof PLACEMENTS)[number];

export const DEFAULT_PLACEMENT: Placement = "side";

export const PLACEMENT_INFO: Record<
  Placement,
  { name: string; where: string; gives: string }
> = {
  overhead: {
    name: "Над животными",
    where: "На высоте 3–4 м, объектив вниз: над проходом, кормовым столом, в загоне",
    gives: "Оценка веса по силуэту, точный подсчёт голов, разметка загонов",
  },
  side: {
    name: "Сбоку",
    where: "На уровне 2–2,5 м, объектив вдоль кормушки или поилки",
    gives: "Время у кормушки и поилки, распознавание отдельных животных",
  },
  wide: {
    name: "Общий обзор",
    where: "На столбе или углу здания, вид на территорию",
    gives: "Охрана периметра, движение техники. Для учёта животных не годится",
  },
};

export function isPlacement(value: unknown): value is Placement {
  return PLACEMENTS.includes(value as Placement);
}

export function placementName(value: unknown): string {
  return isPlacement(value) ? PLACEMENT_INFO[value].name : "не указано";
}

/** Только с камеры над животными снимается силуэт для оценки веса. */
export function measuresWeight(placement: unknown): boolean {
  return placement === "overhead";
}

export type CameraRow = {
  id: string;
  name: string;
  source_uri: string;
  placement: Placement;
  stream_url: string | null;
  cm_per_pixel: number | null;
  calibration_length_cm: number | null;
  calibration_pixels: number | null;
  calibrated_at: string | null;
};

export async function getFarmCameras(
  client: SupabaseClient,
  farmId: string
): Promise<CameraRow[]> {
  const { data, error } = await client
    .from("cameras")
    // Одной строкой, без склейки: supabase-js выводит тип результата из
    // литерала, и склеенная строка превращает его в «неизвестно что»
    .select("id, name, source_uri, placement, stream_url, cm_per_pixel, calibration_length_cm, calibration_pixels, calibrated_at")
    .eq("farm_id", farmId)
    .order("name");

  if (error) throw new Error(`Не удалось загрузить камеры: ${error.message}`);
  return (data as CameraRow[]) ?? [];
}
