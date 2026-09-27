import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Калибровка камеры: сколько сантиметров в пикселе.
 *
 * Без неё все промеры остаются в пикселях, а пиксель ничего не значит:
 * одна и та же корова на камере в трёх метрах и в шести даёт вдвое
 * разную длину. Поэтому вес считался по площади силуэта — величине,
 * которая хотя бы стабильна для одной камеры.
 *
 * Способ простой и не требует оборудования: человек кладёт в кадр
 * предмет известной длины, проводит по нему линию на снимке и пишет,
 * сколько это в сантиметрах.
 */

export type Calibration = {
  cm_per_pixel: number | null;
  calibration_length_cm: number | null;
  calibration_pixels: number | null;
  calibrated_at: string | null;
};

/**
 * Правдоподобные значения масштаба.
 *
 * Камера над проходом на трёх метрах даёт порядка 0,2–1,5 см на пиксель.
 * Значение вне широких границ — почти наверняка перепутанные местами
 * сантиметры и пиксели, и принять его молча значит получить корову
 * длиной четыре метра.
 */
export const MIN_SCALE = 0.01;
export const MAX_SCALE = 20;

/** Длина отрезка в пикселях кадра. Точки приходят в долях от 0 до 1. */
export function pixelLength(
  from: [number, number],
  to: [number, number],
  frameWidth: number,
  frameHeight: number
): number {
  const dx = (to[0] - from[0]) * frameWidth;
  const dy = (to[1] - from[1]) * frameHeight;
  return Math.sqrt(dx * dx + dy * dy);
}

export function scaleFrom(realCm: number, pixels: number): number | null {
  if (!(realCm > 0) || !(pixels > 0)) return null;
  return realCm / pixels;
}

/** Пустая строка — всё в порядке. */
export function validateCalibration(realCm: number, pixels: number): string {
  if (!(realCm > 0)) return "Впишите длину в сантиметрах";
  if (!(pixels > 0)) return "Отметьте на снимке два конца";

  const scale = realCm / pixels;
  if (scale < MIN_SCALE || scale > MAX_SCALE) {
    return (
      "Что-то не сходится. Проверьте, что линия проведена по самой доске, " +
      "а длина написана в сантиметрах, а не в метрах"
    );
  }
  return "";
}

/**
 * Что даст эта калибровка на практике.
 *
 * Человеку полезнее увидеть, какой длины выйдет корова, чем число
 * «0,42 см на пиксель». Ошибку в десять раз так видно сразу.
 */
export function previewLength(scale: number, pixels: number): string {
  const cm = scale * pixels;
  if (cm >= 100) return `${(cm / 100).toFixed(2)} м`;
  return `${cm.toFixed(0)} см`;
}

export function describeScale(calibration: Calibration | null): string {
  if (!calibration?.cm_per_pixel) {
    return "Масштаб не задан: размеры и метры по этой камере не считаются";
  }
  const scale = calibration.cm_per_pixel;
  return `Кадр в ширину: ${((scale * 1920) / 100).toFixed(1)} м`;
}

export async function getCalibration(
  client: SupabaseClient,
  cameraId: string
): Promise<Calibration | null> {
  const { data } = await client
    .from("cameras")
    .select("cm_per_pixel, calibration_length_cm, calibration_pixels, calibrated_at")
    .eq("id", cameraId)
    .maybeSingle();

  return (data as Calibration | null) ?? null;
}
