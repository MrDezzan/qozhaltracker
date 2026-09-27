import { ReactNode } from "react";

/**
 * Пусто — но не молча.
 *
 * Пустой экран без подсказки это самая частая причина «непонятно»: у
 * человека нет ни одного способа узнать, сломалось оно или так и надо.
 * Поэтому здесь всегда две вещи — что происходит и что с этим делать.
 *
 * Объяснение должно быть написано словами фермера, а не нашими.
 * «Учёт по зонам не начался» — это про нашу систему; «пока не
 * размечены кормушки» — про то, что он видит в загоне.
 */
export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="px-6 py-12 text-center sm:py-14">
      <p className="text-[length:var(--text-lg)] font-semibold text-ink">
        {title}
      </p>
      {hint && (
        <p className="mx-auto mt-2 max-w-sm text-[length:var(--text-base)] leading-relaxed text-muted">
          {hint}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
