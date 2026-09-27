import { EventRow } from "./formatters";
import { DEFAULT_TIMEZONE, hourInZone } from "./time";

export type HourlyPoint = {
  hour: number;
  visits: number;
  seconds: number;
};

/**
 * Загрузка зон по часам суток — видно, когда стадо подходит к кормушке.
 *
 * Час считается по времени фермы. Раньше брался час сервера: на Vercel это
 * UTC, и весь график уезжал на пять часов — выходило, что стадо кормится
 * ночью.
 */
export function activityByHour(
  events: EventRow[],
  timeZone: string = DEFAULT_TIMEZONE
): HourlyPoint[] {
  const buckets = new Map<number, { visits: number; seconds: number }>();

  for (const event of events) {
    if (event.event_type !== "zone_exit") continue;
    const hour = hourInZone(event.occurred_at, timeZone);
    if (hour === null) continue;
    const seconds = Number(event.payload["duration_s"] ?? 0);
    if (!Number.isFinite(seconds) || seconds < 0) continue;

    const existing = buckets.get(hour);
    if (existing) {
      existing.visits += 1;
      existing.seconds += seconds;
    } else {
      buckets.set(hour, { visits: 1, seconds });
    }
  }

  return Array.from({ length: 24 }, (_, hour) => ({
    hour,
    visits: buckets.get(hour)?.visits ?? 0,
    seconds: buckets.get(hour)?.seconds ?? 0,
  }));
}

export type PeriodComparison = {
  today: number;
  previous: number;
  changePercent: number | null;
};

/**
 * Сравнение суток с предыдущими. Именно отклонение от привычного,
 * а не абсолютное число, первым сигналит о проблеме в стаде.
 */
export function compareWithPreviousDay(
  events: EventRow[],
  now: Date = new Date()
): PeriodComparison {
  const dayMs = 24 * 60 * 60 * 1000;
  const todayStart = now.getTime() - dayMs;
  const previousStart = now.getTime() - 2 * dayMs;

  let today = 0;
  let previous = 0;

  for (const event of events) {
    if (event.event_type !== "zone_exit") continue;
    const seconds = Number(event.payload["duration_s"] ?? 0);
    if (!Number.isFinite(seconds) || seconds < 0) continue;

    const moment = new Date(event.occurred_at).getTime();
    if (moment >= todayStart) today += seconds;
    else if (moment >= previousStart) previous += seconds;
  }

  const changePercent =
    previous > 0 ? Math.round(((today - previous) / previous) * 100) : null;

  return { today, previous, changePercent };
}

/**
 * Из-за чего на ферме не «всё спокойно».
 *
 * Вид причины — не украшение, а способ подобрать к ней кнопку. Сначала
 * причины были просто строками, и кнопка под ними стояла одна на все
 * случаи: «Проверить камеры». Но человеку, у которого не отмечены
 * кормушки, надо в разметку, а тому, у кого пропала связь с фермой,
 * вообще некуда идти — ему надо позвонить нам. Одна кнопка на все
 * случаи в двух из трёх ведёт не туда, а это хуже, чем её отсутствие.
 *
 * Подбирать кнопку по тексту причины («если строка содержит слово
 * кормушки…») нельзя: текст правят, а поиск по слову молча перестаёт
 * совпадать. Поэтому вид отдельно, текст отдельно.
 */
export type ReasonKind =
  | "нет-связи"
  | "нет-камер"
  | "нет-зон"
  | "тишина"
  | "мало-корма";

export type Reason = { kind: ReasonKind; text: string };

/** Куда вести человека с этой причиной. */
export type NextStep = { href: string; label: string };

/**
 * Таблица полная по видам причин: добавив вид, вы обязаны решить, куда
 * с ним идти. Компилятор не даст забыть. Где идти некуда (связь с
 * фермой чинит не фермер) — там null, и кнопка просто не появится.
 */
const ШАГ: Record<ReasonKind, NextStep | null> = {
  "нет-связи": null,
  "нет-камер": null,
  "нет-зон": { href: "/zones", label: "Разметить кормушки" },
  тишина: { href: "/zones", label: "Проверить камеры" },
  "мало-корма": { href: "/animals", label: "Открыть поголовье" },
};

/** Что делать прямо сейчас. Берём первую причину: она же самая тяжёлая. */
export function nextStep(reasons: Reason[]): NextStep | null {
  for (const reason of reasons) {
    const шаг = ШАГ[reason.kind];
    if (шаг) return шаг;
  }
  return null;
}

export type FarmCondition = {
  score: number;
  label: string;
  reasons: Reason[];
};

/**
 * Сводный показатель состояния фермы.
 *
 * Это не медицинская оценка, а показатель работы системы и стада:
 * складывается из того, на связи ли устройство, приходят ли события
 * и не просело ли кормление против вчерашнего.
 */
export function assessFarmCondition(params: {
  deviceOnline: boolean;
  camerasCount: number;
  zonesConfigured: boolean;
  eventsToday: number;
  feeding: PeriodComparison;
}): FarmCondition {
  let score = 100;
  const reasons: Reason[] = [];

  if (!params.deviceOnline) {
    score -= 45;
    reasons.push({ kind: "нет-связи", text: "нет связи с оборудованием" });
  }

  if (params.camerasCount === 0) {
    score -= 25;
    reasons.push({ kind: "нет-камер", text: "камеры не подключены" });
  }

  if (!params.zonesConfigured) {
    score -= 15;
    reasons.push({ kind: "нет-зон", text: "зоны кормления не заданы" });
  }

  if (params.eventsToday === 0 && params.deviceOnline) {
    score -= 20;
    reasons.push({ kind: "тишина", text: "за сутки нет событий" });
  }

  const change = params.feeding.changePercent;
  if (change !== null && change <= -30) {
    score -= 20;
    reasons.push({
      kind: "мало-корма",
      text: `время у кормушек ниже вчерашнего на ${Math.abs(change)}%`,
    });
  }

  score = Math.max(0, Math.min(100, score));

  const label =
    score >= 85
      ? "Отклонений нет"
      : score >= 60
        ? "Требует внимания"
        : "Требуется вмешательство";

  return { score, label, reasons };
}

/**
 * События за последние N часов.
 *
 * Нужна там, где на экране написано «за сутки». Раньше то же место
 * считалось по последним двумстам событиям, и подпись врала тем сильнее,
 * чем больше на ферме камер.
 */
export function withinHours(
  events: EventRow[],
  now: Date,
  hours: number
): EventRow[] {
  const граница = now.getTime() - hours * 3600_000;
  return events.filter((e) => new Date(e.occurred_at).getTime() >= граница);
}
