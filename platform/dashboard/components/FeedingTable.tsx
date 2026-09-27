import { ZoneSummary, formatDuration } from "../lib/feeding";
import { EmptyState } from "./ui/EmptyState";

const KIND_LABELS: Record<string, string> = {
  feeder: "Кормушка",
  water: "Поилка",
  gate: "Проход",
  other: "Место",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

export function FeedingTable({ zones }: { zones: ZoneSummary[] }) {
  if (zones.length === 0) {
    return (
      <EmptyState
        title="Зоны кормления не заданы"
        hint="Учёт начнётся после разметки зоны на кадре."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[560px]">
      <thead>
        <tr className="text-left text-leaf bg-leaf-bg border-b border-line">
          <th className="font-normal px-6 py-3">Где</th>
          <th className="font-normal px-6 py-3 text-right">Сколько раз подходили</th>
          <th className="font-normal px-6 py-3 text-right">Всего простояли</th>
          <th className="font-normal px-6 py-3 text-right">За один подход</th>
        </tr>
      </thead>
      <tbody>
        {zones.map((zone) => (
          <tr key={zone.zoneId} className="border-b border-line-soft last:border-0">
            <td className="px-6 py-4">
              <div className="text-ink">{zone.zoneName}</div>
              {/* Тип показываем, только если он не дублирует название */}
              {kindLabel(zone.zoneKind) !== zone.zoneName && (
                <div className="text-muted mt-0.5">{kindLabel(zone.zoneKind)}</div>
              )}
            </td>
            <td className="px-6 py-4 text-right tabular text-muted">{zone.visits}</td>
            <td className="px-6 py-4 text-right tabular text-ink">
              {formatDuration(zone.totalSeconds)}
            </td>
            <td className="px-6 py-4 text-right tabular text-muted">
              {formatDuration(zone.averageSeconds)}
            </td>
          </tr>
        ))}
      </tbody>
      </table>
    </div>
  );
}
