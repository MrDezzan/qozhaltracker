import { SupabaseClient } from "@supabase/supabase-js";

export const TRAINING_BUCKET = "training";

/**
 * Вердикты отбраковки.
 *
 * Их ровно четыре, и это не про удобство, а про то, что с кадром будет
 * дальше. `ok` в разметку не идёт вовсе. `merged` и `missed` — это
 * ошибки модели, ради которых всё затевалось. `junk` уходит в мусор.
 */
export const VERDICTS = ["ok", "merged", "missed", "junk"] as const;
export type Verdict = (typeof VERDICTS)[number];

export function isVerdict(value: unknown): value is Verdict {
  return typeof value === "string" && (VERDICTS as readonly string[]).includes(value);
}

/** Рамка, которую нашла модель. Доля от размера кадра, не пиксели. */
export type TrainingBox = {
  x: number;
  y: number;
  w: number;
  h: number;
  c: number;
  n: string;
};

export type TrainingDetections = {
  count?: number;
  classes?: Record<string, number>;
  confidences?: number[];
  min_confidence?: number | null;
  boxes?: TrainingBox[];
};

export type TrainingFrame = {
  id: string;
  farm_id: string;
  farm_name: string;
  camera_id: string;
  camera_name: string;
  path: string;
  captured_at: string;
  reason: string;
  detections: TrainingDetections;
  pending: number;
};

export type TrainingSummaryRow = {
  farm_id: string;
  farm_name: string;
  total: number;
  pending: number;
  ok: number;
  merged: number;
  missed: number;
  junk: number;
  days: number;
  first_at: string | null;
  last_at: string | null;
};

/**
 * Почему кадр отобран — человеческими словами.
 *
 * Показывается прямо над кадром: без этого админ не понимает, куда
 * смотреть, и отбраковка идёт по общему впечатлению вместо конкретной
 * ошибки.
 */
export const REASON_LABELS: Record<string, { title: string; hint: string }> = {
  crowded: {
    title: "Животные стоят вплотную",
    hint: "Проверьте, не обведены ли двое одним контуром",
  },
  count_jump: {
    title: "Счётчик скакнул",
    hint: "Число животных резко изменилось с прошлого кадра",
  },
  low_confidence: {
    title: "Модель сомневалась",
    hint: "Есть обнаружение с низкой уверенностью",
  },
  routine: {
    title: "Обычный кадр",
    hint: "Взят для равновесия: такие кадры тоже нужны в датасете",
  },
};

/**
 * Ссылка на кадр подписывается на короткий срок: хранилище приватное,
 * иначе кадры с фермы утекли бы по прямой ссылке.
 *
 * Срок больше, чем у снимков предпросмотра: отбраковка идёт подряд, и
 * ссылка не должна протухнуть, пока человек думает над кадром.
 */
export async function getTrainingFrameUrl(
  client: SupabaseClient,
  path: string,
  expiresInSeconds = 600
): Promise<string | null> {
  const { data, error } = await client.storage
    .from(TRAINING_BUCKET)
    .createSignedUrl(path, expiresInSeconds);

  if (error || !data) return null;
  return data.signedUrl;
}

/** Следующий непросмотренный кадр. null — всё разобрано. */
export async function getNextFrame(
  client: SupabaseClient,
  farmId?: string
): Promise<TrainingFrame | null> {
  const { data, error } = await client.rpc("next_training_frame", {
    p_farm_id: farmId ?? null,
  });

  if (error || !data || data.length === 0) return null;
  return data[0] as TrainingFrame;
}

export async function getTrainingSummary(
  client: SupabaseClient
): Promise<TrainingSummaryRow[]> {
  const { data, error } = await client.rpc("training_summary");
  if (error || !data) return [];
  return data as TrainingSummaryRow[];
}

/**
 * Сколько кадров уже годится в разметку.
 *
 * Считаются `merged` и `missed` — только они показывают модели то, чего
 * она не умеет. `ok` тоже пойдёт в датасет, но четвертью и позже, а
 * прогресс сбора меряется найденными ошибками.
 */
export function usableForLabelling(row: TrainingSummaryRow): number {
  return Number(row.merged ?? 0) + Number(row.missed ?? 0);
}

/**
 * Совет, что делать дальше. Одна строка вместо таблицы чисел.
 *
 * Пороги отсюда: первая партия разметки — 300 кадров, и продолжать сбор
 * есть смысл, пока их не наберётся. Дней съёмки должно быть не меньше
 * недели: полторы тысячи кадров за один день — это одна погода и одно
 * освещение, и модель заучит именно их.
 */
export const FIRST_BATCH = 300;
export const MIN_DAYS = 7;

export function collectionAdvice(row: TrainingSummaryRow): string {
  const usable = usableForLabelling(row);
  const days = Number(row.days ?? 0);

  if (Number(row.pending ?? 0) > 0) {
    return `Осталось отбраковать ${row.pending}`;
  }
  if (days < MIN_DAYS) {
    return `Съёмки ${days} ${days === 1 ? "день" : "дн."}: мало разных условий, продолжайте сбор`;
  }
  if (usable < FIRST_BATCH) {
    return `Ошибок найдено ${usable} из ${FIRST_BATCH}, продолжайте сбор`;
  }
  return `Готово к разметке: ${usable} кадров с ошибками за ${days} дн.`;
}
