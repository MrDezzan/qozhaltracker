import Link from "next/link";
import { AnimalReadiness, readiness } from "../lib/enrollment";
import { ActivityRow, activityVerdict, formatMeters } from "../lib/activity";
import { timeAgo } from "../lib/format";
import { formatGain, formatWeight } from "../lib/weights";
import { DeleteAnimal } from "./DeleteAnimal";

export type AnimalRow = {
  id: string;
  label: string;
  readiness: AnimalReadiness | undefined;
  sightings: number;
  lastSeenAt: string | null;
  weightKg: number | null;
  dailyGainKg: number | null;
  activity: ActivityRow | undefined;
};

/**
 * Список животных: всё про одно животное в одной строке.
 *
 * Раньше это было две карточки — «эталонные снимки» и «список
 * животных», — и одну и ту же кличку приходилось искать в двух местах:
 * в первой смотрели, готово ли узнавание, во второй — когда видели.
 */
export function AnimalList({
  rows,
  readOnly = false,
}: {
  rows: AnimalRow[];
  /**
   * Только чтение: без кнопки удаления.
   *
   * Нужно там, где страница не подключена к базе. Кнопка, которая
   * отвечает ошибкой, хуже отсутствующей кнопки: человек решает, что
   * сломана платформа, а не что раздел открыт для просмотра.
   */
  readOnly?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-leaf bg-leaf-bg border-b border-line">
            <th className="font-normal px-5 sm:px-6 py-3">Кличка</th>
            <th className="font-normal px-4 py-3">Узнавание</th>
            <th className="font-normal px-4 py-3">Активность</th>
            <th className="font-normal px-4 py-3">Видели</th>
            <th className="font-normal px-4 py-3 text-right">Вес</th>
            <th className="font-normal px-4 py-3 text-right">Привес</th>
            <th className="w-20" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = readiness(row.readiness);
            const move = activityVerdict(row.activity);
            return (
              <tr key={row.id} className="border-b border-line-soft last:border-0">
                <td className="px-5 sm:px-6 py-3">
                  {/* В режиме только чтения кличка не ссылка: карточки
                      животного там нет, а ссылка, ведущая на страницу
                      входа, выглядит как поломка */}
                  {readOnly ? (
                    <span className="text-ink">{row.label}</span>
                  ) : (
                    <Link
                      href={`/animals/${row.id}`}
                      className="text-ink hover:underline"
                    >
                      {row.label}
                    </Link>
                  )}
                </td>

                <td className="px-4 py-3">
                  <span
                    className={`inline-flex items-center gap-1.5 ${
                      status.ready ? "text-calm" : "text-watch"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`w-1.5 h-1.5 rounded-full ${
                        status.ready ? "bg-calm" : "bg-watch"
                      }`}
                    />
                    {status.line}
                  </span>
                </td>

                <td className="px-4 py-3">
                  {move.level === "unknown" ? (
                    <span className="text-faint">—</span>
                  ) : (
                    <span
                      className={
                        move.level === "normal" ? "text-muted" : "text-watch"
                      }
                      title={move.detail}
                    >
                      {formatMeters(row.activity?.meters)}
                      {move.level !== "normal" && (
                        <span className="ml-1.5 text-xs">
                          {move.level === "low" ? "↓" : "↑"}
                        </span>
                      )}
                    </span>
                  )}
                </td>

                <td className="px-4 py-3 text-muted">
                  {row.lastSeenAt ? timeAgo(row.lastSeenAt) : "—"}
                </td>

                <td className="px-4 py-3 text-right tabular-nums text-ink">
                  {formatWeight(row.weightKg)}
                </td>

                <td className="px-4 py-3 text-right tabular-nums text-muted">
                  {formatGain(row.dailyGainKg)}
                </td>

                <td className="px-2 py-3 text-right">
                  {!readOnly && (
                    <DeleteAnimal animalId={row.id} label={row.label} />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
