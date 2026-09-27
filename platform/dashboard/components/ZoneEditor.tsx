"use client";
import { useActionState, useRef, useState } from "react";
import { createZoneAction, ZoneActionState } from "../app/admin/farms/[id]/zoneActions";
import { Button } from "./ui/Button";
import {
  ZONE_KIND_GUIDE,
  ZONE_KIND_LABELS,
  ZoneKind,
  ZoneRow,
  polygonToSvgPoints,
} from "../lib/zones";

const initialState: ZoneActionState = { status: "idle" };

type ZoneFormAction = (
  prev: ZoneActionState,
  formData: FormData
) => Promise<ZoneActionState>;

type Props = {
  farmId: string;
  cameraId: string;
  cameraName: string;
  snapshotUrl: string | null;
  zones: ZoneRow[];
  /**
   * Кто сохраняет зону. По умолчанию админский вариант — так работали все
   * существующие вызовы. Хозяйство передаёт свой: там проверяется
   * принадлежность фермы, а не право администратора, и сводить эти две
   * проверки в одну функцию с флагом нельзя.
   */
  action?: ZoneFormAction;
};

const VIEW_W = 1000;
const VIEW_H = 562;

export function ZoneEditor({
  farmId,
  cameraId,
  cameraName,
  snapshotUrl,
  zones,
  action = createZoneAction,
}: Props) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const [points, setPoints] = useState<[number, number][]>([]);
  const [kind, setKind] = useState<ZoneKind>("feeder");
  const surfaceRef = useRef<HTMLDivElement>(null);

  function addPoint(e: React.MouseEvent<HTMLDivElement>) {
    const box = surfaceRef.current?.getBoundingClientRect();
    if (!box) return;
    // Храним доли, а не пиксели: зона не зависит от разрешения камеры
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
    setPoints((prev) => [...prev, [x, y]]);
  }

  const ready = points.length >= 3;

  if (!snapshotUrl) {
    return (
      <p className="text-sm text-muted">
        Чтобы обвести зону, нужен снимок с камеры «{cameraName}». Запустите обработку на
        ферме и обновите страницу.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div
        ref={surfaceRef}
        onClick={addPoint}
        className="relative rounded-lg overflow-hidden border border-line cursor-crosshair select-none"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={snapshotUrl} alt={`Кадр с камеры ${cameraName}`} className="w-full block" />

        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full pointer-events-none"
        >
          {zones.map((zone) => (
            <polygon
              key={zone.id}
              points={polygonToSvgPoints(zone.polygon, VIEW_W, VIEW_H)}
              fill="color-mix(in srgb, var(--color-dark) 28%, transparent)"
              stroke="var(--color-surface)"
              strokeWidth={2}
            />
          ))}

          {points.length > 1 && (
            <polygon
              points={polygonToSvgPoints(points, VIEW_W, VIEW_H)}
              fill="color-mix(in srgb, var(--color-calm) 25%, transparent)"
              stroke="var(--color-calm)"
              strokeWidth={2}
            />
          )}
          {points.map(([x, y], index) => (
            <circle
              key={index}
              cx={x * VIEW_W}
              cy={y * VIEW_H}
              r={5}
              fill="var(--color-calm)"
              stroke="var(--color-surface)"
              strokeWidth={2}
            />
          ))}
        </svg>
      </div>

      <div className="rounded-lg bg-soft border border-line px-4 py-3 space-y-1.5">
        <p className="text-sm text-muted leading-relaxed">
          <strong className="font-medium">{ZONE_KIND_LABELS[kind]}.</strong>{" "}
          {ZONE_KIND_GUIDE[kind].what}
        </p>
        <p className="text-sm text-muted leading-relaxed">
          {ZONE_KIND_GUIDE[kind].how}
        </p>
        <p className="text-xs text-faint leading-relaxed pt-1">
          Нажимайте по углам области — минимум три точки, замыкать не нужно.
          Уже сохранённые зоны показаны серым. Переставили кормушку или
          повернули камеру — поправьте разметку: иначе система будет считать
          время у пустого угла, и это выглядит так, будто животные перестали
          есть.
        </p>
      </div>

      <form action={formAction} className="flex flex-wrap items-end gap-3">
        <input type="hidden" name="farmId" value={farmId} />
        <input type="hidden" name="cameraId" value={cameraId} />
        <input type="hidden" name="polygon" value={JSON.stringify(points)} />

        <div>
          <label htmlFor="zone-name" className="block text-sm font-medium text-muted mb-2">
            Название
          </label>
          <input
            id="zone-name"
            name="name"
            required
            placeholder="Кормушка слева"
            className="border border-line rounded-lg px-3.5 py-2.5 text-sm bg-surface placeholder:text-faint focus:outline-none focus:ring-4 focus:ring-brand/5 focus:border-brand"
          />
        </div>

        <div>
          <label htmlFor="zone-kind" className="block text-sm font-medium text-muted mb-2">
            Тип
          </label>
          <select
            id="zone-kind"
            name="kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as ZoneKind)}
            className="border border-line rounded-lg px-3.5 py-2.5 text-sm bg-surface focus:outline-none focus:ring-4 focus:ring-brand/5 focus:border-brand"
          >
            {(Object.keys(ZONE_KIND_LABELS) as ZoneKind[]).map((kind) => (
              <option key={kind} value={kind}>
                {ZONE_KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </div>

        <Button type="submit" disabled={pending || !ready}>
          {pending ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="secondary" onClick={() => setPoints([])} disabled={points.length === 0}>
          Сбросить
        </Button>

        {!ready && points.length > 0 && (
          <span className="text-sm text-muted">
            поставлено точек: {points.length} из 3
          </span>
        )}
        {state.status === "error" && (
          <span className="text-sm text-trouble w-full">{state.message}</span>
        )}
      </form>
    </div>
  );
}
