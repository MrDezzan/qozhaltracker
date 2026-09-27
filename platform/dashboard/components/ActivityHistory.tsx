import { ActivityPoint, formatMeters } from "../lib/activity";

/**
 * Путь по дням — столбиками.
 *
 * Столбики, а не линия: пропущенный день здесь означает «животное не
 * попадало в кадр», и линия соединила бы соседние дни через пустоту,
 * нарисовав движение, которого не наблюдали.
 */
export function ActivityHistory({ points }: { points: ActivityPoint[] }) {
  if (points.length === 0) {
    return (
      <p className="text-sm text-muted">
        История появится через сутки работы камеры.
      </p>
    );
  }

  const peak = Math.max(...points.map((p) => p.meters), 1);

  return (
    <div>
      <div className="flex items-end gap-1 h-24">
        {points.map((point) => {
          const height = Math.max(2, Math.round((point.meters / peak) * 100));
          return (
            <div
              key={point.day}
              title={`${point.day}: ${formatMeters(point.meters)}`}
              className="flex-1 min-w-1 bg-line hover:bg-faint transition-colors rounded-sm"
              style={{ height: `${height}%` }}
            />
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-faint mt-2">
        <span>{points[0].day}</span>
        <span>максимум {formatMeters(peak)}</span>
        <span>{points[points.length - 1].day}</span>
      </div>
    </div>
  );
}
