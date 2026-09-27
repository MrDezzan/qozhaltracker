import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Оценка живой массы.
 *
 * Формула подбирается на месте по контрольным взвешиваниям. До этого момента
 * система не показывает никаких килограммов: красивое, но выдуманное число
 * хуже пустой клетки — по нему начнут принимать решения.
 */

/** Меньше этого числа взвешиваний формуле верить нельзя — это подгонка под шум. */
export const MIN_WEIGHINGS = 10;

export type WeightModel = {
  coefficient_a: number;
  exponent_b: number;
  sample_count: number;
  mae_kg: number | null;
  mape_percent: number | null;
  r_squared: number | null;
  fitted_at: string;
};

export type WeightEstimate = {
  animal_id: string;
  label: string;
  measurements: number;
  estimated_weight_kg: number | null;
  last_measured_at: string;
};

export type DailyGain = {
  animal_id: string;
  label: string;
  weight_now_kg: number | null;
  daily_gain_kg: number | null;
};

export async function getWeightModel(
  client: SupabaseClient,
  farmId: string
): Promise<WeightModel | null> {
  const { data } = await client
    .from("weight_models")
    .select("coefficient_a, exponent_b, sample_count, mae_kg, mape_percent, r_squared, fitted_at")
    .eq("farm_id", farmId)
    .maybeSingle();
  return (data as WeightModel | null) ?? null;
}

export async function getWeightEstimates(
  client: SupabaseClient,
  farmId: string
): Promise<WeightEstimate[]> {
  const { data } = await client
    .from("animal_weight_estimates")
    .select("animal_id, label, measurements, estimated_weight_kg, last_measured_at")
    .eq("farm_id", farmId)
    .order("label");
  return (data as WeightEstimate[] | null) ?? [];
}

export async function getDailyGains(
  client: SupabaseClient,
  farmId: string
): Promise<DailyGain[]> {
  const { data } = await client
    .from("animal_daily_gain")
    .select("animal_id, label, weight_now_kg, daily_gain_kg")
    .eq("farm_id", farmId)
    .order("label");
  return (data as DailyGain[] | null) ?? [];
}

export async function countWeighings(
  client: SupabaseClient,
  farmId: string
): Promise<number> {
  const { count } = await client
    .from("weighings")
    .select("id", { count: "exact", head: true })
    .eq("farm_id", farmId);
  return count ?? 0;
}

/**
 * Сколько ещё взвешиваний нужно, прежде чем формулу можно будет подобрать.
 * Показываем это прямым текстом: иначе непонятно, почему нет килограммов.
 */
export function weighingsRemaining(done: number): number {
  return Math.max(0, MIN_WEIGHINGS - done);
}

export type Accuracy = { text: string; trustworthy: boolean };

/**
 * Честная подпись под оценкой.
 *
 * Ошибка считается на тех же данных, на которых подбиралась формула, поэтому
 * она оптимистична. Прятать это нельзя: пользователь должен понимать, что
 * ±20 кг на бычке в 400 кг — это нормально, а не поломка.
 */
export function describeAccuracy(model: WeightModel | null): Accuracy {
  if (!model) {
    return { text: "формула не подобрана", trustworthy: false };
  }
  if (model.mape_percent === null) {
    return { text: `подобрана по ${model.sample_count} взвешиваниям`, trustworthy: true };
  }

  const percent = Math.round(model.mape_percent * 10) / 10;
  const suffix = `средняя ошибка ${percent}% по ${model.sample_count} взвешиваниям`;

  // Показатель степени теоретически около 1.5: площадь растёт как квадрат
  // линейного размера, масса — как куб. Далёкое значение означает, что
  // данные плохие, даже если ошибка на них вышла красивой.
  const plausible = model.exponent_b > 0.9 && model.exponent_b < 2.5;
  if (!plausible) {
    return {
      text: `${suffix}; зависимость выглядит неправдоподобно, нужны ещё взвешивания`,
      trustworthy: false,
    };
  }

  return { text: suffix, trustworthy: percent <= 12 };
}

export function formatWeight(kg: number | null): string {
  if (kg === null || !Number.isFinite(kg)) return "—";
  return `${Math.round(kg)} кг`;
}

export function formatGain(kg: number | null): string {
  if (kg === null || !Number.isFinite(kg)) return "—";
  const sign = kg > 0 ? "+" : "";
  return `${sign}${kg.toFixed(2)} кг/сут`;
}
