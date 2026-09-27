export type EventRow = {
  id: string;
  camera_id: string;
  animal_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type HeadcountPoint = {
  bucketStart: string;
  count: number;
};

/**
 * Точки графика поголовья.
 *
 * Устройство присылает сводку `counted` раз в минуту — её и берём.
 * Поддержка старых поштучных `detected` оставлена, чтобы уже накопленные
 * данные не пропали с графика.
 */
/**
 * Начало минуты, в которую попало событие, — полной меткой времени.
 *
 * Раньше здесь стоял срез строки до шестнадцати знаков. Он отрезал не
 * только секунды, но и пояс: «2026-09-27T15:40:12Z» превращалось в
 * «2026-09-27T15:40», и дальше такую строку разбирали как местное время
 * сервера. На сервере в UTC совпадало случайно, а подпись на графике
 * считалась от неё же и уезжала на пять часов относительно соседнего
 * графика по часам.
 */
function началоМинуты(iso: string): string {
  const мс = new Date(iso).getTime();
  if (Number.isNaN(мс)) return iso;
  return new Date(Math.floor(мс / 60_000) * 60_000).toISOString();
}

export function bucketHeadcountByMinute(events: EventRow[]): HeadcountPoint[] {
  const counted = new Map<string, number>();
  const detected = new Map<string, Set<string | number>>();

  for (const event of events) {
    const bucketStart = началоМинуты(event.occurred_at);

    if (event.event_type === "counted") {
      const value = Number(event.payload["unique_count"] ?? 0);
      if (!Number.isFinite(value)) continue;
      // В минуту может прийти несколько камер — берём наибольшее
      counted.set(bucketStart, Math.max(counted.get(bucketStart) ?? 0, value));
      continue;
    }

    if (event.event_type === "detected") {
      const trackKey = (event.payload["track_id"] as string | number) ?? event.id;
      if (!detected.has(bucketStart)) detected.set(bucketStart, new Set());
      detected.get(bucketStart)!.add(trackKey);
    }
  }

  const merged = new Map(counted);
  for (const [bucket, ids] of detected) {
    if (!merged.has(bucket)) merged.set(bucket, ids.size);
  }

  return Array.from(merged.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucketStart, count]) => ({ bucketStart, count }));
}
