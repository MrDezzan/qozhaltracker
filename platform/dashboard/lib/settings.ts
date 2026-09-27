import { времяСуток } from "./validate";
import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Настройки фермы, которые раньше правились запросами в базу.
 *
 * Клиент до базы не дойдёт. Значит, всё, что не вынесено в интерфейс,
 * навсегда останется в значениях по умолчанию — а они заданы «на глаз»
 * и под конкретное хозяйство почти наверняка не подходят.
 */

/**
 * Настройки тревог.
 *
 * Раньше здесь были пороги по температуре, активности и заряду батареи —
 * всё это считалось по носимым датчикам, от которых отказались. Осталась
 * охрана: она работает по камерам.
 */
export type AlertSettings = {
  guard_from: string;
  guard_to: string;
  guard_day_severity: string;
};

export type RetentionPolicy = {
  events_days: number;
  sightings_days: number;
  snapshots_days: number;
};

export const DEFAULT_ALERT_SETTINGS: AlertSettings = {
  guard_from: "22:00",
  guard_to: "06:00",
  guard_day_severity: "warning",
};

export const DEFAULT_RETENTION: RetentionPolicy = {
  events_days: 400,
  sightings_days: 30,
  snapshots_days: 7,
};

/** Часовые пояса Казахстана и соседей, где могут стоять фермы клиентов. */
export const TIMEZONES: { value: string; label: string }[] = [
  { value: "Asia/Almaty", label: "Алматы, Астана, Караганда (UTC+5)" },
  { value: "Asia/Aqtobe", label: "Актобе, Костанай (UTC+5)" },
  { value: "Asia/Aqtau", label: "Актау, Атырау, Уральск (UTC+5)" },
  { value: "Asia/Bishkek", label: "Бишкек (UTC+6)" },
  { value: "Asia/Tashkent", label: "Ташкент (UTC+5)" },
  { value: "Europe/Moscow", label: "Москва (UTC+3)" },
  { value: "UTC", label: "UTC" },
];

export async function getAlertSettings(
  client: SupabaseClient,
  farmId: string
): Promise<AlertSettings> {
  const { data } = await client
    .from("alert_settings")
    .select(
      "guard_from, guard_to, guard_day_severity"
    )
    .eq("farm_id", farmId)
    .maybeSingle();

  return (data as AlertSettings | null) ?? DEFAULT_ALERT_SETTINGS;
}

export async function getRetentionPolicy(
  client: SupabaseClient,
  farmId: string
): Promise<RetentionPolicy> {
  const { data } = await client
    .from("retention_policy")
    .select("events_days, sightings_days, snapshots_days")
    .eq("farm_id", farmId)
    .maybeSingle();

  return (data as RetentionPolicy | null) ?? DEFAULT_RETENTION;
}

/** Дни в человеческую фразу: «месяц» читается быстрее, чем «30». */
export function describeDays(days: number): string {
  if (days >= 365) {
    const years = Math.round(days / 365);
    return years === 1 ? "около года" : `около ${years} лет`;
  }
  if (days >= 30) {
    const months = Math.round(days / 30);
    return months === 1 ? "месяц" : `${months} мес.`;
  }
  if (days === 7) return "неделя";
  return `${days} дн.`;
}

/**
 * Время из базы приходит как «22:00:00», а полю формы нужно «22:00».
 *
 * Без обрезки браузер молча показывает пустое поле: значение не проходит
 * его проверку формата, и хозяин видит настройку незаполненной, хотя она
 * задана.
 */
export function toTimeInput(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback;
  const match = String(raw).match(/^(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : fallback;
}

/**
 * Охранное окно человеческой фразой.
 *
 * Окно через полночь надо называть вслух: «с 22:00 до 06:00» без пояснения
 * читается как «шесть утра сегодняшнего дня», то есть как пустой промежуток.
 */
export function describeGuardWindow(from: string, to: string): string {
  const start = toTimeInput(from, "22:00");
  const end = toTimeInput(to, "06:00");
  if (start === end) return "круглосуточно";
  const throughMidnight = start > end ? ", то есть ночью, через полночь" : "";
  return `с ${start} до ${end}${throughMidnight}`;
}

/**
 * Что делать с людьми в кадре вне охранных часов.
 *
 * Охрана работает круглосуточно, и это не настройка «вкл/выкл», а выбор
 * громкости. Совсем выключать день стоит только на проходном дворе с
 * постоянным движением — там иначе один шум.
 */
export const DAY_GUARD_OPTIONS = [
  {
    value: "warning",
    name: "Внимание",
    note: "Тревога появится в ленте, но не как срочная. Подходит большинству.",
  },
  {
    value: "danger",
    name: "Так же срочно, как ночью",
    note: "Для хозяйств, где днём посторонних быть не должно совсем.",
  },
  {
    value: "info",
    name: "Просто отметить",
    note: "Запишется в ленту тихо, без выделения.",
  },
  {
    value: "off",
    name: "Днём не тревожить",
    note: "Ночная охрана продолжит работать. Для проходного двора.",
  },
] as const;

/**
 * Разумно ли выглядит охранное окно. Пустая строка — всё в порядке.
 *
 * Проверялась только форма записи, поэтому «99:99» проходило насквозь и
 * падало уже в Postgres на колонке типа `time` — с сырым текстом ошибки
 * наружу. Диапазоны проверяются здесь, до запроса.
 */
export function validateGuardWindow(from: string, to: string): string {
  if (времяСуток(from) === null || времяСуток(to) === null) {
    return "Время указывается как 22:00";
  }
  return "";
}
