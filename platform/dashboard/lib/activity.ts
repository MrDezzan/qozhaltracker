import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Активность животного по камерам.
 *
 * Главная оговорка, которую нельзя прятать: это путь **в кадре**, а не
 * весь путь животного. Камера видит кусок загона, остальное не учтено.
 * Поэтому абсолютные метры сами по себе почти ничего не значат, и
 * показывать их как измерение нельзя.
 *
 * Значат две вещи: сравнение животного с самим собой в прошлые дни и
 * сравнение с соседями по тому же загону сегодня. Их видит та же камера
 * в те же часы, так что помеха у всех одинаковая и в отношении она
 * сокращается.
 */

export type ActivityRow = {
  animal_id: string;
  label: string;
  day: string;
  meters: number;
  seconds_visible: number;
  baseline_meters: number | null;
  ratio_to_own: number | null;
  ratio_to_herd: number | null;
  days_known: number;
};

export type ActivityPoint = {
  day: string;
  meters: number;
  seconds_visible: number;
};

/**
 * Меньше этого числа дней собственная норма ничего не значит.
 *
 * По двум дням «норма» — это просто один из них, и любое отклонение от
 * неё случайно. Три дня — минимум, при котором медиана хоть что-то
 * отбрасывает.
 */
export const MIN_DAYS_FOR_BASELINE = 3;

/** Меньше этого времени в кадре метры не с чем соотнести. */
export const MIN_SECONDS_VISIBLE = 300;

export async function getActivity(
  client: SupabaseClient,
  farmId: string
): Promise<Map<string, ActivityRow>> {
  const { data } = await client.rpc("animal_activity", { target_farm_id: farmId });
  const rows = (data as ActivityRow[] | null) ?? [];
  return new Map(rows.map((row) => [row.animal_id, row]));
}

export async function getActivityHistory(
  client: SupabaseClient,
  animalId: string,
  days = 30
): Promise<ActivityPoint[]> {
  const { data } = await client.rpc("animal_activity_history", {
    target_animal_id: animalId,
    days,
  });
  return (data as ActivityPoint[] | null) ?? [];
}

export type ZoneVisitRow = {
  animal_id: string;
  zone_kind: string;
  visits: number;
  seconds: number;
};

export async function getZoneVisitsByAnimal(
  client: SupabaseClient,
  farmId: string,
  days = 1
): Promise<Map<string, ZoneVisitRow[]>> {
  const { data } = await client.rpc("animal_zone_visits", {
    target_farm_id: farmId,
    days,
  });
  const rows = (data as ZoneVisitRow[] | null) ?? [];
  const grouped = new Map<string, ZoneVisitRow[]>();
  for (const row of rows) {
    const list = grouped.get(row.animal_id) ?? [];
    list.push(row);
    grouped.set(row.animal_id, list);
  }
  return grouped;
}

export type ActivityVerdict = {
  level: "normal" | "low" | "high" | "unknown";
  headline: string;
  detail: string;
};

/**
 * Насколько сильно животное должно выбиться, чтобы это стоило показывать.
 *
 * Треть — не круглое число ради красоты. День на день не приходится:
 * животное могло больше времени провести вне кадра, могла быть жара,
 * мог быть перегон. Разброс в 10–20 % — это обычный день, и помечать
 * его значит приучить человека не смотреть на пометки вовсе.
 */
export const LOW_RATIO = 0.67;
export const HIGH_RATIO = 1.5;

/**
 * Что означает сегодняшняя активность.
 *
 * Сравнение идёт и со своей нормой, и со стадом. Если просело всё стадо
 * — это жара или перегон, а не болезнь у каждого животного по очереди,
 * и говорить о болезни нельзя.
 */
export function activityVerdict(row: ActivityRow | undefined): ActivityVerdict {
  if (!row) {
    return {
      level: "unknown",
      headline: "Нет данных",
      detail:
        "Чтобы считать метры, камере нужно знать масштаб. Поставщик " +
        "настраивает это один раз при установке.",
    };
  }

  if (row.days_known < MIN_DAYS_FOR_BASELINE) {
    const left = MIN_DAYS_FOR_BASELINE - row.days_known;
    return {
      level: "unknown",
      headline: "Ещё присматриваемся",
      detail: `Через ${left} дн. станет понятно, сколько это животное ходит обычно.`,
    };
  }

  if (row.seconds_visible < MIN_SECONDS_VISIBLE) {
    return {
      level: "unknown",
      headline: "Сегодня почти не было видно",
      detail: "Животное редко попадало в кадр, поэтому судить не по чему.",
    };
  }

  const own = row.ratio_to_own;
  if (own === null) {
    return {
      level: "unknown",
      headline: "Ещё присматриваемся",
      detail: "Пока не с чем сравнивать.",
    };
  }

  const herdDroppedToo = row.ratio_to_herd !== null && row.ratio_to_herd > 0.85;

  if (own <= LOW_RATIO) {
    const percent = Math.round((1 - own) * 100);
    return {
      level: "low",
      headline: `Ниже своей обычной на ${percent} %`,
      detail: herdDroppedToo
        ? "Остальные ходят как обычно, значит дело в нём. Стоит осмотреть: " +
          "хромота, вздутие."
        : "Сегодня меньше ходят все. Похоже на жару или перегон, а не на " +
          "болезнь.",
    };
  }

  if (own >= HIGH_RATIO) {
    const percent = Math.round((own - 1) * 100);
    return {
      level: "high",
      headline: `Выше своей обычной на ${percent} %`,
      detail:
        "Часто это охота, окно около суток. Стоит проверить и отметить " +
        "для осеменения.",
    };
  }

  return {
    level: "normal",
    headline: "В своей норме",
    detail: `Обычно проходит около ${Math.round(row.baseline_meters ?? 0)} м.`,
  };
}

export function formatMeters(meters: number | null | undefined): string {
  if (meters === null || meters === undefined) return "—";
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} км`;
  return `${Math.round(meters)} м`;
}

// Виды зон заданы ограничением в миграции 0004: feeder, water, gate,
// other. Здесь стояло "waterer" — значения, которого в базе не бывает.
// Поилка поэтому не подписывалась и выпадала из строки подходов, а
// понять это по экрану было нельзя: просто одной строкой меньше.
export const ZONE_KIND_LABEL: Record<string, string> = {
  feeder: "Кормушка",
  water: "Поилка",
  gate: "Проход",
  perimeter: "Периметр",
  other: "Прочее",
};

/** Подходы к корму и воде одной строкой. */
export function describeVisits(rows: ZoneVisitRow[] | undefined): string {
  if (!rows || rows.length === 0) return "Подходов не было";
  return rows
    .filter((row) => row.zone_kind === "feeder" || row.zone_kind === "water")
    .map((row) => {
      const name = ZONE_KIND_LABEL[row.zone_kind] ?? row.zone_kind;
      const minutes = Math.round(row.seconds / 60);
      return `${name.toLowerCase()}: ${row.visits} раз, ${minutes} мин`;
    })
    .join("; ");
}
