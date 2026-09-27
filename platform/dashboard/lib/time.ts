/**
 * Время фермы.
 *
 * База хранит всё в UTC — это правильно и менять не нужно. Но интерфейс
 * рендерится на сервере, а сервер живёт по UTC. Без явного пояса график
 * «по часам суток» показывал бы, что стадо подходит к кормушке в три часа
 * ночи. Фермер такому не поверит, и правильно сделает.
 *
 * Пояс принадлежит ферме, а не пользователю: работники одного хозяйства
 * живут по одним часам, даже если владелец смотрит дашборд из Астаны.
 */

export const DEFAULT_TIMEZONE = "Asia/Almaty";

/** Проверка на существование пояса: битое значение в базе не должно ронять страницу. */
export function safeTimeZone(timeZone: string | null | undefined): string {
  if (!timeZone) return DEFAULT_TIMEZONE;
  try {
    new Intl.DateTimeFormat("ru-RU", { timeZone });
    return timeZone;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

/** Час суток по часам фермы, 0–23. */
export function hourInZone(iso: string, timeZone: string = DEFAULT_TIMEZONE): number | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;

  const formatted = new Intl.DateTimeFormat("ru-RU", {
    timeZone: safeTimeZone(timeZone),
    hour: "2-digit",
    hour12: false,
  }).format(date);

  // «24» в некоторых окружениях означает полночь
  const hour = Number(formatted.replace(/\D/g, "")) % 24;
  return Number.isFinite(hour) ? hour : null;
}

export function formatTimeInZone(iso: string, timeZone: string = DEFAULT_TIMEZONE): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: safeTimeZone(timeZone),
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/**
 * Часы и минуты по времени фермы: «19:42».
 *
 * Отдельно от formatTimeInZone, потому что там есть секунды: на подписях
 * графика они лишние, а сокращать срезом строки нельзя — именно так
 * график по минутам и оказался подписан по UTC.
 */
export function timeInZone(iso: string, timeZone: string = DEFAULT_TIMEZONE): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: safeTimeZone(timeZone),
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDateTimeInZone(
  iso: string,
  timeZone: string = DEFAULT_TIMEZONE
): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: safeTimeZone(timeZone),
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/**
 * Насколько пояс фермы сдвинут относительно UTC, в часах.
 * Нужно, чтобы подписать график и снять вопрос «а по чьему времени?».
 */
export function zoneOffsetLabel(
  timeZone: string = DEFAULT_TIMEZONE,
  now: Date = new Date()
): string {
  const zone = safeTimeZone(timeZone);
  const asUtc = new Date(now.toLocaleString("en-US", { timeZone: "UTC" }));
  const asZone = new Date(now.toLocaleString("en-US", { timeZone: zone }));
  const hours = Math.round((asZone.getTime() - asUtc.getTime()) / 3_600_000);
  if (hours === 0) return "UTC";
  return `UTC${hours > 0 ? "+" : ""}${hours}`;
}
