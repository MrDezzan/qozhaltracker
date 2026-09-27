import {
  WeightAccuracy,
  describeBias,
  formatKg,
  formatPercent,
  isTrustworthy,
  verdict,
} from "../lib/accuracy";

const LEVEL_STYLE: Record<string, string> = {
  good: "border-calm/30 bg-calm-bg/60",
  usable: "border-watch/30 bg-watch-bg/60",
  poor: "border-trouble/30 bg-trouble-bg/60",
  unknown: "border-line bg-soft",
};

/**
 * Насколько можно верить весу.
 *
 * Показывается рядом с вводом взвешиваний, потому что это одна тема:
 * человек вносит вес — и тут же видит, что от этого изменилось.
 */
export function WeightAccuracyPanel({ accuracy }: { accuracy: WeightAccuracy | null }) {
  const result = verdict(accuracy);
  const trusted = isTrustworthy(accuracy);

  return (
    <div className="px-5 sm:px-6 pb-6 space-y-4">
      <div className={`rounded-lg border px-4 py-3 ${LEVEL_STYLE[result.level]}`}>
        <p className="text-sm font-medium text-ink">{result.headline}</p>
        <p className="text-sm text-muted mt-1 leading-relaxed">{result.detail}</p>
      </div>

      {trusted && accuracy && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Metric
              label="Обычно ошибается на"
              value={formatPercent(accuracy.mape_percent)}
              hint={formatKg(accuracy.mae_kg)}
            />
            <Metric
              label="Самый плохой случай"
              value={formatPercent(accuracy.worst_percent)}
              hint={`проверено на ${accuracy.animals} животных`}
            />
          </div>

          <p className="text-sm text-muted">{describeBias(accuracy)}</p>
        </>
      )}

      <p className="text-xs text-faint leading-relaxed">
        Проверяем на животных, которых система при обучении не видела. Иначе
        цифра вышла бы красивее правды.
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg bg-soft px-3 py-2.5">
      <div className="text-xs text-muted">{label}</div>
      <div className="text-lg font-medium text-ink tabular mt-0.5">{value}</div>
      {hint && <div className="text-xs text-faint">{hint}</div>}
    </div>
  );
}
