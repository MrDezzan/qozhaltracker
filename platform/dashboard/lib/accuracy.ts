import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Честная точность оценки веса.
 *
 * Показатель, который считает `fit_weight_model`, вычисляется на тех же
 * взвешиваниях, по которым подбиралась формула. Такая ошибка всегда
 * красивее правды: формулу подогнали именно под эти точки. Показывать
 * это число клиенту нельзя.
 *
 * Здесь — ошибка на животных, которых модель при подборе не видела.
 */

/** Меньше этого числа отложенных проверок цифре верить нельзя. */
export const MIN_CHECKS = 8;

/** Меньше этого числа животных проверка вырождается. */
export const MIN_ANIMALS = 3;

/** Столько проверок и на стольких особях. Хватает ли — решает `isTrustworthy`. */
export type SampleSize = {
  checked: number;
  animals: number;
};

export type WeightAccuracy = SampleSize & {
  mae_kg: number | null;
  mape_percent: number | null;
  bias_percent: number | null;
  worst_percent: number | null;
};

export type HoldoutError = {
  animal_id: string;
  actual_kg: number;
  predicted_kg: number;
  error_kg: number;
  error_percent: number;
};

export async function getWeightAccuracy(
  client: SupabaseClient,
  farmId: string
): Promise<WeightAccuracy | null> {
  const { data, error } = await client.rpc("weight_accuracy", {
    target_farm_id: farmId,
  });

  if (error || !data) return null;
  const row = (Array.isArray(data) ? data[0] : data) as WeightAccuracy | undefined;
  if (!row || !row.checked) return null;
  return row;
}

export async function getHoldoutErrors(
  client: SupabaseClient,
  farmId: string
): Promise<HoldoutError[]> {
  const { data } = await client.rpc("weight_holdout_errors", {
    target_farm_id: farmId,
  });
  return (data as HoldoutError[] | null) ?? [];
}

/**
 * Хватает ли данных, чтобы вообще что-то говорить.
 *
 * Отдельно от расчёта, потому что это главное решение: на трёх
 * взвешиваниях можно получить ошибку в 1 %, и она не будет значить
 * ничего. Назвать такую цифру клиенту — хуже, чем промолчать.
 */
export function isTrustworthy(accuracy: SampleSize | null): boolean {
  if (!accuracy) return false;
  return accuracy.checked >= MIN_CHECKS && accuracy.animals >= MIN_ANIMALS;
}

/** Сколько ещё взвешиваний нужно. Ноль — хватает. */
export function checksRemaining(accuracy: SampleSize | null): number {
  const done = accuracy?.checked ?? 0;
  return Math.max(0, MIN_CHECKS - done);
}

export type Verdict = {
  /** Короткая оценка: на что это годится. */
  headline: string;
  detail: string;
  level: "good" | "usable" | "poor" | "unknown";
};

/**
 * Что означает полученная ошибка на практике.
 *
 * Число «7,3 %» само по себе не подсказывает, что делать. Границы взяты
 * от задачи: контроль привеса требует, чтобы месячная прибавка была
 * заметнее ошибки. На откорме это 30–45 кг в месяц, то есть на корове
 * в 500 кг ошибка до 5 % (25 кг) ещё позволяет видеть тренд, а 10 %
 * (50 кг) — уже нет.
 */
export function verdict(accuracy: WeightAccuracy | null): Verdict {
  if (!isTrustworthy(accuracy)) {
    const left = checksRemaining(accuracy);
    return {
      level: "unknown",
      headline: "Пока не знаем",
      detail:
        left > 0
          ? `Взвесьте ещё ${left} животных на весах, тогда сможем сказать, ` +
            "насколько точен вес с камеры."
          : "Взвесьте животных разного размера: сейчас проверка идёт по " +
            "слишком похожим.",
    };
  }

  const mape = accuracy!.mape_percent ?? 0;

  if (mape <= 5) {
    return {
      level: "good",
      headline: "Весу можно верить",
      detail:
        "За месяц животное набирает 30–45 кг, это заметно больше ошибки, " +
        "так что рост веса видно по каждому животному.",
    };
  }

  if (mape <= 10) {
    return {
      level: "usable",
      headline: "Годится для стада, но не для одного животного",
      detail:
        "Средний вес по группе считать можно. У отдельного животного " +
        "месячная прибавка теряется в ошибке.",
    };
  }

  return {
    level: "poor",
    headline: "Верить нельзя",
    detail:
      "Ошибка такая же большая, как то, что мы измеряем. Взвесьте больше " +
      "животных или проверьте, что камера висит над проходом.",
  };
}

/**
 * Куда смещена оценка.
 *
 * Смещение лечится иначе, чем разброс: систематический перекос
 * поправляется одним коэффициентом, а разброс требует другого метода
 * измерения. Поэтому их надо разделять, а не прятать в одну «среднюю
 * ошибку».
 */
export function describeBias(accuracy: WeightAccuracy | null): string {
  const bias = accuracy?.bias_percent;
  if (bias === null || bias === undefined) return "";

  if (Math.abs(bias) < 1) return "";
  const side = bias > 0 ? "завышает" : "занижает";
  return `Система постоянно ${side} на ${Math.abs(bias).toFixed(1)} %`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)} %`;
}

export function formatKg(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)} кг`;
}

/**
 * Сравнение двух способов оценки веса.
 *
 * По площади силуэта — работает без калибровки, но площадь меняется от
 * поворота животного и опущенной головы. По промерам в сантиметрах —
 * требует калибровки камеры, зато устойчивее.
 *
 * Какой лучше, решает не убеждение, а ошибка на отложенной выборке.
 */

export type MethodName = "area" | "dimensions";

export const METHOD_LABEL: Record<MethodName, string> = {
  area: "По площади силуэта",
  dimensions: "По промерам в сантиметрах",
};

export const METHOD_NOTE: Record<MethodName, string> = {
  area: "Работает без калибровки камеры",
  dimensions: "Требует калибровки, устойчивее к повороту животного",
};

export type MethodAccuracy = SampleSize & {
  method: MethodName;
  mape_percent: number | null;
  bias_percent: number | null;
  worst_percent: number | null;
};

export async function getMethodComparison(
  client: SupabaseClient,
  farmId: string
): Promise<MethodAccuracy[]> {
  const { data } = await client.rpc("weight_method_comparison", {
    target_farm_id: farmId,
  });
  return ((data as MethodAccuracy[] | null) ?? []).filter((row) => row.checked > 0);
}

/**
 * Какой способ выбрать по итогам сравнения.
 *
 * Разница меньше процента — это шум выборки, а не преимущество. Менять
 * рабочий способ ради неё значит гонять формулу туда-сюда при каждом
 * новом взвешивании.
 */
export const MEANINGFUL_GAP = 1.0;

export type MethodVerdict = {
  winner: MethodName | null;
  headline: string;
  detail: string;
};

export function compareMethods(rows: MethodAccuracy[]): MethodVerdict {
  const usable = rows.filter((r) => isTrustworthy(r) && r.mape_percent !== null);

  if (usable.length === 0) {
    return {
      winner: null,
      headline: "Сравнивать пока не на чем",
      detail:
        "Нужны контрольные взвешивания. Для способа по промерам ещё и " +
        "калибровка камеры: без неё сантиметров не будет.",
    };
  }

  if (usable.length === 1) {
    const only = usable[0];
    const other: MethodName = only.method === "area" ? "dimensions" : "area";
    return {
      winner: only.method,
      headline: `Считаем ${METHOD_LABEL[only.method].toLowerCase()}`,
      detail:
        other === "dimensions"
          ? "Способ по промерам не проверен: камера не откалибрована, " +
            "сантиметров в измерениях нет."
          : "Способ по площади не проверен: нет измерений с площадью.",
    };
  }

  const sorted = [...usable].sort(
    (a, b) => (a.mape_percent ?? 0) - (b.mape_percent ?? 0)
  );
  const best = sorted[0];
  const rest = sorted[1];
  const gap = (rest.mape_percent ?? 0) - (best.mape_percent ?? 0);

  if (gap < MEANINGFUL_GAP) {
    return {
      winner: null,
      headline: "Способы работают одинаково",
      detail:
        `Разница ${gap.toFixed(1)} %: это шум выборки, а не преимущество. ` +
        "Оставляем тот, что уже работает: менять ради такой разницы значит " +
        "гонять формулу туда-сюда при каждом новом взвешивании.",
    };
  }

  return {
    winner: best.method,
    headline: `Точнее: ${METHOD_LABEL[best.method].toLowerCase()}`,
    detail:
      `${formatPercent(best.mape_percent)} против ` +
      `${formatPercent(rest.mape_percent)}, разница ${gap.toFixed(1)} %. ` +
      METHOD_NOTE[best.method] + ".",
  };
}
