import { SupabaseClient } from "@supabase/supabase-js";

export type ZoneKind = "feeder" | "water" | "gate" | "perimeter" | "other";

export const ZONE_KIND_LABELS: Record<ZoneKind, string> = {
  feeder: "Кормушка",
  water: "Поилка",
  gate: "Проход",
  perimeter: "Периметр охраны",
  other: "Другое",
};

/**
 * Что система делает с зоной каждого типа и как её обводить.
 *
 * Подсказка нужна прямо в форме, а не в отдельной инструкции: человек
 * рисует зону раз в несколько месяцев и к моменту второй кормушки уже
 * не помнит, обводить край или всю площадь.
 */
export const ZONE_KIND_GUIDE: Record<ZoneKind, { what: string; how: string }> = {
  feeder: {
    what: "Считается время у кормушки: сколько минут в сутки животное здесь провело.",
    how:
      "Обводите саму кормушку и полосу земли перед ней шириной примерно в полкоровы: " +
      "система смотрит, где животное СТОИТ, а не куда тянется головой.",
  },
  water: {
    what: "Считается время у поилки. Резкое падение: один из первых признаков болезни.",
    how: "Обводите поилку и подход к ней. Зона маленькая, обводите точнее.",
  },
  gate: {
    what: "Проходы через ворота. Пригодится для сверки поголовья при перегоне.",
    how: "Обводите створ ворот целиком, от косяка до косяка.",
  },
  perimeter: {
    what:
      "Охрана. Тревога о постороннем поднимается, только если человек внутри этой зоны.",
    how:
      "Обводите свою территорию, НЕ захватывая дорогу и соседние участки: " +
      "иначе тревога будет срабатывать на каждого прохожего.",
  },
  other: {
    what: "Время в произвольной области. Просто счётчик, без особого смысла для системы.",
    how: "Обводите как удобно.",
  },
};

export type ZoneRow = {
  id: string;
  camera_id: string;
  name: string;
  kind: ZoneKind;
  polygon: [number, number][];
};

export async function getZones(
  client: SupabaseClient,
  cameraId: string
): Promise<ZoneRow[]> {
  const { data, error } = await client
    .from("zones")
    .select("id, camera_id, name, kind, polygon")
    .eq("camera_id", cameraId)
    .order("created_at", { ascending: true });

  if (error) {
    throw new Error(`Не удалось загрузить зоны: ${error.message}`);
  }
  return (data as ZoneRow[]) ?? [];
}

/**
 * Многоугольник хранится в долях 0..1, а не в пикселях: так зона
 * переживает смену разрешения камеры и одинаково ложится на снимок
 * любого размера.
 */
export function isValidPolygon(polygon: unknown): polygon is [number, number][] {
  if (!Array.isArray(polygon) || polygon.length < 3) return false;
  return polygon.every(
    (point) =>
      Array.isArray(point) &&
      point.length === 2 &&
      point.every((n) => typeof n === "number" && n >= 0 && n <= 1 && Number.isFinite(n))
  );
}

/** Точки в атрибут points для SVG. */
export function polygonToSvgPoints(
  polygon: [number, number][],
  width: number,
  height: number
): string {
  return polygon.map(([x, y]) => `${x * width},${y * height}`).join(" ");
}

/** Площадь многоугольника — чтобы отсечь случайные тычки в двух точках. */
export function polygonArea(polygon: [number, number][]): number {
  let area = 0;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    area += (polygon[j][0] + polygon[i][0]) * (polygon[j][1] - polygon[i][1]);
  }
  return Math.abs(area / 2);
}
