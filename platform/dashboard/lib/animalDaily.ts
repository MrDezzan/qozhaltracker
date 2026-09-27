import { SupabaseClient } from "@supabase/supabase-js";

/** Сутки одного животного: сколько ело, сколько ходило, какого размера. */
export type AnimalDay = {
  day: string;
  meters: number;
  seconds_visible: number;
  feeder_seconds: number;
  feeder_visits: number;
  water_visits: number;
  /** Медиана площади силуэта за день. null — в этот день не измеряли */
  area_px: number | null;
  length_cm: number | null;
  width_cm: number | null;
  measurements: number;
};

export type WeekChange = {
  feeder_visits_now: number | null;
  feeder_visits_before: number | null;
  feeder_seconds_now: number | null;
  feeder_seconds_before: number | null;
  meters_now: number | null;
  meters_before: number | null;
  area_now: number | null;
  area_before: number | null;
  /** На сколько процентов изменился силуэт. null — сравнивать не с чем */
  area_change_pct: number | null;
  days_with_size: number;
};

export async function getAnimalDaily(
  client: SupabaseClient,
  animalId: string,
  days = 30
): Promise<AnimalDay[]> {
  const { data, error } = await client.rpc("animal_daily", {
    target_animal_id: animalId,
    days,
  });
  if (error || !data) return [];
  return data as AnimalDay[];
}

export async function getWeekChange(
  client: SupabaseClient,
  animalId: string
): Promise<WeekChange | null> {
  const { data, error } = await client.rpc("animal_week_change", {
    target_animal_id: animalId,
  });
  if (error || !data || data.length === 0) return null;
  return data[0] as WeekChange;
}

/**
 * Сколько дней подряд с конца животное не подходило к корму.
 *
 * Считается с последнего дня назад: три пропуска неделю назад и порядок
 * со вчерашнего дня — это выздоровление, а не тревога.
 */
export function missedFeedingStreak(rows: AnimalDay[]): number {
  let streak = 0;
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i].feeder_visits > 0) break;
    streak += 1;
  }
  return streak;
}

/** Среднее число подходов за период. null — данных нет вовсе. */
export function averageMeals(rows: AnimalDay[]): number | null {
  if (rows.length === 0) return null;
  const total = rows.reduce((sum, row) => sum + row.feeder_visits, 0);
  return total / rows.length;
}

/**
 * Изменение силуэта в процентах, словами.
 *
 * Проценты, а не килограммы, и это не заглушка. Вес в килограммах
 * требует формулы, подобранной по контрольным взвешиваниям; пока их нет,
 * нет и формулы. А площадь силуэта копится с первого дня, и
 * относительный рост по ней — честное число, полученное без весов.
 */
export function describeGrowth(change: WeekChange | null): string {
  if (!change) return "Данных пока нет";

  // Порог в один процент, а не ноль: силуэт колеблется от позы животного
  // и от того, как оно повернулось. Называть полупроцентную рябь ростом
  // значит приучить человека не верить этой строке
  if (change.area_change_pct === null) {
    return change.days_with_size > 0
      ? "Мало замеров, чтобы сравнить недели"
      : "Размер ещё не измеряли";
  }
  if (Math.abs(change.area_change_pct) < 1) return "Размер без изменений";

  const sign = change.area_change_pct > 0 ? "+" : "";
  const word = change.area_change_pct > 0 ? "больше" : "меньше";
  return `${sign}${change.area_change_pct}% к прошлой неделе, стал ${word}`;
}

/** Изменение числа подходов к корму, словами. */
export function describeMeals(change: WeekChange | null): string {
  if (!change || change.feeder_visits_now === null) return "Данных пока нет";

  const now = change.feeder_visits_now;
  const before = change.feeder_visits_before;
  const nowText = `${now.toFixed(1)} раза в день`;

  if (before === null || before <= 0) return nowText;

  const delta = now - before;
  if (Math.abs(delta) < 0.3) return `${nowText}, как и раньше`;

  return delta > 0
    ? `${nowText}, было ${before.toFixed(1)}`
    : `${nowText}, было ${before.toFixed(1)}: стал подходить реже`;
}
