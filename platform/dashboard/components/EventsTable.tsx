import { EventRow } from "../lib/formatters";
import { EmptyState } from "./ui/EmptyState";
import { DEFAULT_TIMEZONE, formatTimeInZone } from "../lib/time";

type Props = {
  events: EventRow[];
  cameraNames?: Record<string, string>;
  /** Время показывается по часам фермы, а не по часам сервера. */
  timeZone?: string;
};

// Что в ленту не попадает.
//
// `detected` — поштучные обнаружения, их было по тридцать в минуту на
// животное. `counted` — сводки поголовья: строка «1 гол.» каждую минуту
// забивает ленту так, что настоящие события в ней не найти, а само
// число уже есть и на плитке сверху, и на графике поголовья.
//
// В ленте остаётся то, о чём человек может что-то решить: кто и сколько
// был у кормушки, тревоги.
const NOISY_EVENT_TYPES = new Set(["detected", "counted"]);

export function meaningfulEvents(events: EventRow[]): EventRow[] {
  return events.filter((event) => !NOISY_EVENT_TYPES.has(event.event_type));
}

const EVENT_LABELS: Record<string, string> = {
  zone_enter: "Подошло к зоне",
  zone_exit: "Кормушка или поилка",
  weight_estimated: "Взвешено камерой",
  face_id_matched: "Узнали животное",
};

/** Что показать в колонке «Подробности» — у разных событий она разная. */
function describeEvent(event: EventRow): string {
  if (event.event_type === "zone_exit") {
    const zone = event.payload["zone_name"];
    const seconds = Number(event.payload["duration_s"] ?? 0);
    const minutes = Math.round(seconds / 60);
    const time = seconds < 60 ? `${Math.round(seconds)} с` : `${minutes} мин`;
    return zone ? `${zone} — ${time}` : time;
  }
  return "—";
}

export function EventsTable({
  events: allEvents,
  cameraNames = {},
  timeZone = DEFAULT_TIMEZONE,
}: Props) {
  const events = meaningfulEvents(allEvents);

  if (events.length === 0) {
    return (
      <EmptyState
        title="Событий пока нет"
        hint="События появятся после запуска распознавания."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[560px]">
      <thead>
        <tr className="text-left text-leaf bg-leaf-bg border-b border-line">
          <th className="font-normal px-6 py-3 w-28">Время</th>
          <th className="font-normal px-6 py-3">Камера</th>
          <th className="font-normal px-6 py-3">Что случилось</th>
          <th className="font-normal px-6 py-3">Подробности</th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => {
          return (
            <tr
              key={event.id}
              className="border-b border-line-soft last:border-0 hover:bg-soft/70 transition-colors"
            >
              <td className="px-6 py-3.5 tabular text-muted">
                {formatTimeInZone(event.occurred_at, timeZone)}
              </td>
              <td className="px-6 py-3.5 text-muted">
                {cameraNames[event.camera_id] ?? "Без названия"}
              </td>
              <td className="px-6 py-3.5 text-ink">
                {EVENT_LABELS[event.event_type] ?? event.event_type}
              </td>
              <td className="px-6 py-3.5 text-muted">{describeEvent(event)}</td>
            </tr>
          );
        })}
      </tbody>
      </table>
    </div>
  );
}
