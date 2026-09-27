type Tone = "online" | "offline" | "neutral" | "warning";

const DOTS: Record<Tone, string> = {
  online: "bg-calm",
  offline: "bg-trouble",
  warning: "bg-watch",
  neutral: "bg-line",
};

/**
 * Статус — точка плюс обычный текст, без цветной плашки.
 * Плашки на каждой строке превращают таблицу в светофор.
 */
export function StatusBadge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted">
      <span aria-hidden className={`inline-block w-1.5 h-1.5 rounded-full ${DOTS[tone]}`} />
      {children}
    </span>
  );
}
