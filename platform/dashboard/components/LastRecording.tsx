import { LastRecording as Row, describeOutcome, outcomeIsGood } from "../lib/enrollment";

/** Итог последней записи. Пока человек не начал следующую. */
export function LastRecordingNote({ last }: { last: Row | null }) {
  const text = describeOutcome(last);
  if (!text) return null;

  const good = outcomeIsGood(last);
  return (
    <div
      className={`rounded-lg border px-4 py-3 text-sm ${
        good
          ? "border-calm/30 bg-calm-bg/60 text-muted"
          : "border-watch/30 bg-watch-bg/60 text-muted"
      }`}
    >
      {text}
    </div>
  );
}
