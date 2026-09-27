"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { calibrateCameraAction } from "../app/zones/actions";
import {
  Calibration,
  describeScale,
  pixelLength,
  previewLength,
  scaleFrom,
  validateCalibration,
} from "../lib/calibration";
import { Button } from "./ui/Button";

/** Размер кадра, в котором считаются пиксели. Точки хранятся в долях. */
const FRAME_W = 1920;
const FRAME_H = 1080;

/**
 * Калибровка камеры: две точки по предмету известной длины.
 *
 * Никакого оборудования не требуется. Человек кладёт в кадр рулетку,
 * доску или метровую линейку, отмечает её концы на снимке и пишет длину.
 *
 * Две точки, а не рамка: рамка требует, чтобы предмет лежал строго
 * горизонтально, а линию можно провести под любым углом — и по диагонали
 * ворот, и вдоль стены.
 */
export function CameraCalibration({
  cameraId,
  cameraName,
  snapshotUrl,
  calibration,
}: {
  cameraId: string;
  cameraName: string;
  snapshotUrl: string | null;
  calibration: Calibration | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [points, setPoints] = useState<[number, number][]>([]);
  const [realCm, setRealCm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const surface = useRef<HTMLDivElement>(null);

  const pixels =
    points.length === 2
      ? pixelLength(points[0], points[1], FRAME_W, FRAME_H)
      : 0;
  const cm = Number(realCm.replace(",", "."));
  const scale = scaleFrom(cm, pixels);
  const problem = points.length === 2 && realCm ? validateCalibration(cm, pixels) : "";

  function addPoint(e: React.MouseEvent<HTMLDivElement>) {
    const box = surface.current?.getBoundingClientRect();
    if (!box) return;
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
    // Третий клик начинает заново: поправить одну точку из двух —
    // задача, ради которой не стоит заводить перетаскивание
    setPoints((prev) => (prev.length >= 2 ? [[x, y]] : [...prev, [x, y]]));
  }

  async function save() {
    setError(null);
    const result = await calibrateCameraAction(cameraId, cm, pixels);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    setOpen(false);
    setPoints([]);
    setRealCm("");
    startTransition(() => router.refresh());
  }

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted">{describeScale(calibration)}</span>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-sm text-muted hover:text-ink transition-colors"
        >
          {calibration?.cm_per_pixel ? "Задать заново" : "Задать масштаб"}
        </button>
      </div>
    );
  }

  if (!snapshotUrl) {
    return (
      <p className="text-sm text-muted">
        Нужен снимок с камеры «{cameraName}». Включите компьютер на ферме и
        обновите страницу.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-soft border border-line px-4 py-3 text-sm text-muted leading-relaxed">
        Положите на пол доску или рулетку — там,{" "}
        <strong className="font-medium text-ink">где ходят животные</strong>,
        а не у стены. Отметьте на снимке два её конца и впишите длину.
      </div>

      <div
        ref={surface}
        onClick={addPoint}
        className="relative rounded-lg overflow-hidden border border-line cursor-crosshair select-none"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={snapshotUrl} alt={`Кадр с камеры ${cameraName}`} className="w-full block" />

        <svg
          viewBox="0 0 1000 562"
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full pointer-events-none"
        >
          {points.length === 2 && (
            <line
              x1={points[0][0] * 1000}
              y1={points[0][1] * 562}
              x2={points[1][0] * 1000}
              y2={points[1][1] * 562}
              stroke="var(--color-calm)"
              strokeWidth={3}
            />
          )}
          {points.map(([x, y], index) => (
            <circle
              key={index}
              cx={x * 1000}
              cy={y * 562}
              r={6}
              fill="var(--color-calm)"
              stroke="var(--color-surface)"
              strokeWidth={2}
            />
          ))}
        </svg>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="block text-muted mb-1.5">Её длина, см</span>
          <input
            value={realCm}
            onChange={(e) => setRealCm(e.target.value)}
            inputMode="decimal"
            placeholder="100"
            className="border border-line rounded-lg px-3 py-2 w-28"
          />
        </label>

        <Button
          onClick={() => void save()}
          disabled={pending || points.length < 2 || !realCm || Boolean(problem)}
        >
          {pending ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="secondary" onClick={() => setPoints([])} disabled={!points.length}>
          Заново
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>

      {points.length < 2 && (
        <p className="text-sm text-muted">
          Отметьте два конца — поставлено {points.length} из 2
        </p>
      )}

      {/* Показываем не «0,42 см на пиксель», а во что это превращается.
          Ошибку в десять раз так видно сразу */}
      {scale && !problem && (
        <p className="text-sm text-muted">
          Получается, весь кадр в ширину — {previewLength(scale, FRAME_W)}.
          Похоже на правду?
        </p>
      )}

      {problem && <p className="text-sm text-watch leading-relaxed">{problem}</p>}
      {error && <p className="text-sm text-trouble">{error}</p>}
    </div>
  );
}
