import { HourlyPoint } from "../lib/analytics";
import { EmptyState } from "./ui/EmptyState";

export function HourlyChart({ points }: { points: HourlyPoint[] }) {
  const maxSeconds = Math.max(...points.map((p) => p.seconds), 0);

  if (maxSeconds === 0) {
    return (
      <EmptyState
        title="Данных по часам пока нет"
        hint="Данные появятся после первых подходов к кормушкам."
      />
    );
  }

  return (
    <div>
      <div className="flex items-end gap-[3px] h-32">
        {points.map((point) => {
          const height = (point.seconds / maxSeconds) * 100;
          const minutes = Math.round(point.seconds / 60);
          return (
            <div
              key={point.hour}
              className="flex-1 min-w-0 bg-line-soft rounded-sm relative group"
              style={{ height: "100%" }}
            >
              <div
                className="absolute bottom-0 left-0 right-0 bg-brand rounded-sm"
                style={{ height: `${height}%` }}
                title={`${point.hour}:00 · ${minutes} мин, ${point.visits} подходов`}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-faint tabular mt-2">
        <span>00</span>
        <span>06</span>
        <span>12</span>
        <span>18</span>
        <span>23</span>
      </div>
    </div>
  );
}
