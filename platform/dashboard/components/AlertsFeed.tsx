import Link from "next/link";
import {
  AlertRow,
  Severity,
  alertAdvice,
  alertName,
  describeAlert,
} from "../lib/alerts";
import { acknowledgeAlertAction } from "../app/alertActions";
import { EmptyState } from "./ui/EmptyState";
import { timeAgo } from "../lib/format";

const SEVERITY_STYLE: Record<Severity, string> = {
  danger: "border-l-red-500 bg-trouble-bg/40",
  warning: "border-l-amber-400 bg-watch-bg/30",
  info: "border-l-neutral-300",
};

const SEVERITY_DOT: Record<Severity, string> = {
  danger: "bg-trouble",
  warning: "bg-watch",
  info: "bg-line",
};

type Props = {
  alerts: AlertRow[];
  animalNames?: Record<string, string>;
  limit?: number;
  showAdvice?: boolean;
  /**
   * Только чтение: без кнопки «Принять в работу».
   *
   * Нужно там, где страница не подключена к базе. Кнопка, которая
   * отвечает ошибкой, читается как неисправность платформы.
   */
  readOnly?: boolean;
  /** Куда ведёт ссылка «Все тревоги». */
  moreHref?: string;
};

export function AlertsFeed({
  alerts,
  animalNames = {},
  limit,
  showAdvice = true,
  readOnly = false,
  moreHref = "/alerts",
}: Props) {
  if (alerts.length === 0) {
    return (
      <EmptyState
        title="Активных тревог нет"
        hint="Появятся при обнаружении постороннего в зоне охраны."
      />
    );
  }

  const shown = limit ? alerts.slice(0, limit) : alerts;

  return (
    <div>
      <ul className="divide-y divide-line-soft">
        {shown.map((alert) => {
          const subject =
            (alert.animal_id && animalNames[alert.animal_id]) || alert.title;
          const facts = describeAlert(alert);
          return (
            <li
              key={alert.id}
              className={`border-l-2 px-5 sm:px-6 py-4 ${SEVERITY_STYLE[alert.severity]} ${
                alert.acknowledged_at ? "opacity-60" : ""
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${SEVERITY_DOT[alert.severity]}`}
                    />
                    <span className="text-sm font-medium text-ink truncate">
                      {subject}
                    </span>
                    <span className="text-sm text-muted truncate">
                      {alertName(alert.kind)}
                    </span>
                  </div>

                  {facts && (
                    <p className="text-sm text-muted mt-1 tabular">{facts}</p>
                  )}

                  {showAdvice && (
                    <p className="text-xs text-muted mt-1.5 leading-relaxed">
                      {alertAdvice(alert.kind)}
                    </p>
                  )}
                </div>

                <div className="flex flex-col items-end gap-2 shrink-0">
                  <span className="text-xs text-muted whitespace-nowrap">
                    {timeAgo(alert.opened_at)}
                  </span>
                  {alert.acknowledged_at ? (
                    <span className="text-xs text-faint">В работе</span>
                  ) : readOnly ? null : (
                    <form action={acknowledgeAlertAction}>
                      <input type="hidden" name="alertId" value={alert.id} />
                      <button
                        type="submit"
                        className="text-xs text-muted underline underline-offset-2 hover:text-ink"
                      >
                        Принять в работу
                      </button>
                    </form>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {limit && alerts.length > limit && (
        <div className="px-5 sm:px-6 py-3 border-t border-line-soft">
          <Link
            href={moreHref}
            className="text-sm text-muted hover:text-ink"
          >
            Все тревоги ({alerts.length})
          </Link>
        </div>
      )}
    </div>
  );
}
