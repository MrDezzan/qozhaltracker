/**
 * Плитка с одним числом.
 *
 * Подпись стоит НАД числом, а не под ним, и это не вкус. Взгляд по
 * экрану идёт сверху вниз: увидев сперва «412», человек вынужден
 * дочитать до подписи и вернуться обратно. Увидев сперва «сейчас в
 * кадре», он уже знает, что означает число, когда до него доходит.
 *
 * Число крупное намеренно: ради него сюда и смотрят, а экран читают
 * стоя, с вытянутой руки.
 */
export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-[var(--card-radius)] border border-line bg-surface px-4 py-4 sm:px-5">
      <div className="text-[length:var(--text-sm)] font-medium leading-snug text-leaf">
        {label}
      </div>
      <div className="tabular mt-1.5 text-[length:var(--text-2xl)] font-semibold leading-none text-ink">
        {value}
      </div>
      {hint && (
        <div className="mt-1.5 text-[length:var(--text-xs)] text-faint">
          {hint}
        </div>
      )}
    </div>
  );
}
