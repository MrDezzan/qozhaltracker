import {
  METHOD_LABEL,
  METHOD_NOTE,
  MethodAccuracy,
  compareMethods,
  formatPercent,
  isTrustworthy,
} from "../lib/accuracy";

/**
 * Какой способ оценки веса точнее — на одних и тех же данных.
 *
 * Две формулы спорят между собой: по площади силуэта (работает сразу,
 * но площадь меняется от поворота животного) и по промерам в сантиметрах
 * (нужна калибровка камеры). Спор решает не рассуждение, а ошибка на
 * животных, которых формула при подборе не видела.
 *
 * Панель существует, чтобы у нас был ответ на вопрос «а калибровка вообще
 * что-то дала?» в килограммах, а не в ощущениях.
 */
export function MethodComparison({ rows }: { rows: MethodAccuracy[] }) {
  const result = compareMethods(rows);

  return (
    <div className="px-5 sm:px-6 pb-6 space-y-4">
      <div className="rounded-lg border border-line bg-soft px-4 py-3">
        <p className="text-sm font-medium text-ink">{result.headline}</p>
        <p className="text-sm text-muted mt-1 leading-relaxed">{result.detail}</p>
      </div>

      {rows.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {rows.map((row) => {
            const trusted = isTrustworthy(row);
            const winner = result.winner === row.method;
            return (
              <div
                key={row.method}
                className={`rounded-lg border px-4 py-3 ${
                  winner ? "border-calm/30 bg-calm-bg/60" : "border-line"
                }`}
              >
                <p className="text-sm font-medium text-ink">
                  {METHOD_LABEL[row.method]}
                </p>
                <p className="text-xs text-muted mt-0.5">{METHOD_NOTE[row.method]}</p>

                <p className="text-2xl font-medium text-ink mt-3 tabular-nums">
                  {trusted ? formatPercent(row.mape_percent) : "—"}
                </p>
                <p className="text-xs text-muted mt-1">
                  {trusted
                    ? `средняя ошибка · проверок ${row.checked}, особей ${row.animals}`
                    : `данных мало: проверок ${row.checked}, особей ${row.animals}`}
                </p>

                {trusted && row.worst_percent !== null && (
                  <p className="text-xs text-muted mt-1">
                    Худший случай {formatPercent(row.worst_percent)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
