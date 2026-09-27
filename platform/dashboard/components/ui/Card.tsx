import { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`overflow-hidden rounded-[var(--card-radius)] border border-line bg-surface ${className}`}
    >
      {children}
    </section>
  );
}

/**
 * Шапка карточки.
 *
 * Описание тут обязательнее заголовка. «Кормушки и поилки» — это
 * название, а «сколько времени скот провёл у каждой» — это ответ на
 * вопрос «и что?», который человек задаёт про любую таблицу. Без
 * второй строки карточка выглядит отчётом для кого-то другого.
 */
export function CardHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-4 px-5 pt-5 pb-4 sm:px-6">
      <div>
        <h2 className="text-[length:var(--text-lg)] font-semibold leading-snug text-ink">
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-[length:var(--text-sm)] leading-snug text-muted">
            {description}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
  );
}

export function CardBody({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`px-5 pb-6 sm:px-6 ${className}`}>{children}</div>;
}
