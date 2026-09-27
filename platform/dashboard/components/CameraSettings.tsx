"use client";

import { useState } from "react";
import { useActionState } from "react";
import { updateCameraAction, CameraActionState } from "../app/admin/farms/[id]/actions";
import { PlacementPicker } from "./PlacementPicker";
import { Button } from "./ui/Button";
import { Field } from "./ui/Field";
import { Placement, PLACEMENT_INFO, measuresWeight, placementName } from "../lib/cameras";

const INITIAL: CameraActionState = { status: "idle" };

type Props = {
  farmId: string;
  camera: {
    id: string;
    name: string;
    placement: string;
    stream_url: string | null;
    security_enabled?: boolean;
  };
};

export function CameraSettings({ farmId, camera }: Props) {
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState(updateCameraAction, INITIAL);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-muted hover:text-ink transition-colors"
      >
        Настроить
      </button>
    );
  }

  return (
    <form action={action} className="space-y-5 text-left">
      <input type="hidden" name="farmId" value={farmId} />
      <input type="hidden" name="cameraId" value={camera.id} />

      <Field label="Название" name="name" required defaultValue={camera.name} />

      <PlacementPicker value={camera.placement as Placement} />

      <Field
        label="Поток по локальной сети"
        name="streamUrl"
        mono
        defaultValue={camera.stream_url ?? ""}
        placeholder="http://192.168.1.50:8089/stream/<id камеры>?token=…"
        hint="Необязательно. Работает, только когда телефон в сети фермы."
      />

      <label className="flex items-start gap-3 rounded-lg border border-line px-4 py-3 cursor-pointer">
        <input
          type="checkbox"
          name="securityEnabled"
          defaultChecked={camera.security_enabled ?? false}
          className="mt-0.5"
        />
        <span className="text-sm">
          <span className="font-medium text-ink">
            Следить за посторонними
          </span>
          <span className="block text-muted mt-0.5 leading-relaxed">
            Ночью система поднимет тревогу, если увидит человека. Включать
            только там, где ночью людей быть не должно: у кормового стола
            это будет срабатывать на утренней раздаче.
          </span>
          <span className="block text-muted mt-1.5 leading-relaxed">
            Снимать людей можно, только когда на ферме оформлены приказ о
            видеонаблюдении, ознакомление под роспись и таблички на входах.
          </span>
        </span>
      </label>

      {state.status === "error" && (
        <p className="text-sm text-trouble">{state.message}</p>
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={pending}>
          {pending ? "Сохраняем…" : "Сохранить"}
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>
    </form>
  );
}

/** Короткая подпись под камерой в списке: где стоит и что с неё снимается. */
export function PlacementBadge({ placement }: { placement: string }) {
  const known = placement in PLACEMENT_INFO;
  return (
    <span className="inline-flex flex-col">
      <span
        className={`text-sm ${known ? "text-ink" : "text-watch"}`}
      >
        {placementName(placement)}
      </span>
      {measuresWeight(placement) && (
        <span className="text-xs text-faint">снимается силуэт для веса</span>
      )}
    </span>
  );
}
