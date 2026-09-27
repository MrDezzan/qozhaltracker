import { ReactNode } from "react";

/**
 * Шапка внутреннего раздела.
 *
 * На главном экране её нет и не должно быть: там первый экран телефона
 * отдан ответу «всё ли в порядке», а не сообщению о том, где человек
 * находится. Он и так знает — он сам сюда зашёл.
 *
 * А внутри разделов она нужна: человек приходит сюда по ссылке из
 * другого места и должен понять, куда попал.
 */
export function PageHeader({
  title,
  description,
  action,
  breadcrumb,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  breadcrumb?: ReactNode;
}) {
  return (
    <div className="mb-6 sm:mb-8">
      {breadcrumb && (
        <div className="mb-3 text-[length:var(--text-sm)]">{breadcrumb}</div>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div>
          <h1 className="text-[length:var(--text-xl)] font-semibold tracking-tight text-ink">
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 text-[length:var(--text-base)] text-muted">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    </div>
  );
}
