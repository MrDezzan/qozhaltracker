import { ReactNode } from "react";

/**
 * Сворачиваемая карточка на нативном <details>: работает без JS
 * и не мигает при загрузке страницы.
 */
export function CollapsibleCard({
  title,
  description,
  defaultOpen = true,
  children,
}: {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details
      open={defaultOpen}
      className="group bg-surface border border-line rounded-xl overflow-hidden"
    >
      <summary className="flex items-start justify-between gap-4 px-6 py-5 cursor-pointer list-none hover:bg-soft/70 transition-colors">
        <div>
          <h2 className="text-base font-medium text-ink">{title}</h2>
          {description && <p className="text-sm text-muted mt-1">{description}</p>}
        </div>
        <span className="text-sm text-faint shrink-0 mt-0.5">
          <span className="group-open:hidden">Развернуть</span>
          <span className="hidden group-open:inline">Свернуть</span>
        </span>
      </summary>
      {children}
    </details>
  );
}
