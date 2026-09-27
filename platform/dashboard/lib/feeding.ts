import { EventRow } from "./formatters";

export type ZoneSummary = {
  zoneId: string;
  zoneName: string;
  zoneKind: string;
  visits: number;
  totalSeconds: number;
  averageSeconds: number;
};

/**
 * Сводка по зонам из событий выхода.
 *
 * Пока без разбивки по животным: track_id живёт только внутри сессии,
 * поэтому «корова №7 ела 40 минут» станет возможно лишь с распознаванием
 * особей. Сейчас считаем по стаду в целом.
 */
export function summariseZoneVisits(events: EventRow[]): ZoneSummary[] {
  const byZone = new Map<string, ZoneSummary>();

  for (const event of events) {
    if (event.event_type !== "zone_exit") continue;

    const zoneId = String(event.payload["zone_id"] ?? "");
    if (!zoneId) continue;

    const seconds = Number(event.payload["duration_s"] ?? 0);
    if (!Number.isFinite(seconds) || seconds < 0) continue;

    const existing = byZone.get(zoneId);
    if (existing) {
      existing.visits += 1;
      existing.totalSeconds += seconds;
      existing.averageSeconds = existing.totalSeconds / existing.visits;
    } else {
      byZone.set(zoneId, {
        zoneId,
        zoneName: String(event.payload["zone_name"] ?? "Без названия"),
        zoneKind: String(event.payload["zone_kind"] ?? "other"),
        visits: 1,
        totalSeconds: seconds,
        averageSeconds: seconds,
      });
    }
  }

  return Array.from(byZone.values()).sort((a, b) => b.totalSeconds - a.totalSeconds);
}

/** «1 ч 05 мин» — минуты и секунды читаются хуже, чем часы с минутами. */
export function formatDuration(seconds: number): string {
  const rounded = Math.max(0, Math.round(seconds));
  if (rounded < 60) return `${rounded} с`;

  const minutes = Math.floor(rounded / 60);
  if (minutes < 60) return `${minutes} мин`;

  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0 ? `${hours} ч` : `${hours} ч ${String(restMinutes).padStart(2, "0")} мин`;
}
