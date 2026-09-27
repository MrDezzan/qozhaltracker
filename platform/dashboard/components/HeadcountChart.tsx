import { HeadcountPoint } from "../lib/formatters";
import { DEFAULT_TIMEZONE, timeInZone } from "../lib/time";
import { EmptyState } from "./ui/EmptyState";

type Props = {
  points: HeadcountPoint[];
  /**
   * Пояс фермы. Обязателен по смыслу, хотя и со значением по умолчанию:
   * подписи времени на графике брались срезом строки, то есть в UTC, и
   * на казахской ферме весь график был подписан на пять часов раньше,
   * чем происходило. Рядом стоит график по часам, где время уже
   * пересчитывалось правильно, — два графика противоречили друг другу.
   */
  timeZone?: string;
};

/**
 * Столбчатый график без внешних библиотек.
 * Подписи осей обязательны: график без них не читается,
 * а лишняя зависимость ради этого не нужна.
 */
export function HeadcountChart({ points, timeZone = DEFAULT_TIMEZONE }: Props) {
  if (points.length === 0) {
    return (
      <EmptyState
        title="Данных для графика недостаточно"
        hint="График появится после первых подсчётов."
      />
    );
  }

  const maxCount = Math.max(...points.map((p) => p.count));
  const axisMax = Math.max(1, maxCount);
  const width = 100;
  const height = 40;
  const barSlot = width / points.length;
  const barWidth = Math.max(0.5, Math.min(barSlot * 0.55, 3));

  const timeLabel = (bucket: string) => timeInZone(bucket, timeZone);
  const labelStep = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div className="flex gap-4">
      <div className="flex flex-col justify-between text-xs text-faint tabular w-7 text-right shrink-0 py-0.5">
        <span>{axisMax}</span>
        <span>{Math.round(axisMax / 2)}</span>
        <span>0</span>
      </div>

      <div className="flex-1 min-w-0">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="w-full h-40"
          role="img"
          aria-label="Поголовье по времени"
        >
          {[0, 0.5, 1].map((ratio) => (
            <line
              key={ratio}
              x1={0}
              x2={width}
              y1={height * ratio}
              y2={height * ratio}
              stroke="var(--color-line-soft)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {points.map((point, index) => {
            const barHeight = (point.count / axisMax) * (height - 1);
            return (
              <rect
                key={point.bucketStart}
                x={index * barSlot + (barSlot - barWidth) / 2}
                y={height - barHeight}
                width={barWidth}
                height={barHeight}
                rx={0.3}
                fill="var(--color-brand)"
              >
                <title>{`${timeLabel(point.bucketStart)} — ${point.count}`}</title>
              </rect>
            );
          })}
        </svg>

        <div className="flex justify-between text-xs text-faint tabular mt-3">
          {points
            .filter((_, i) => i % labelStep === 0 || i === points.length - 1)
            .map((point) => (
              <span key={point.bucketStart}>{timeLabel(point.bucketStart)}</span>
            ))}
        </div>
      </div>
    </div>
  );
}
