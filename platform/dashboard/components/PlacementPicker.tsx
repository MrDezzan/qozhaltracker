"use client";

import { useState } from "react";
import {
  PLACEMENTS,
  PLACEMENT_INFO,
  Placement,
  DEFAULT_PLACEMENT,
} from "../lib/cameras";

/**
 * Выбор расположения камеры карточками, а не выпадающим списком.
 *
 * Монтажник не знает, что стоит за словом «сверху», и в списке выберет
 * первое попавшееся. Карточка сразу говорит, куда вешать и что это даст, —
 * тогда выбор осмысленный, а не случайный.
 */
export function PlacementPicker({
  name = "placement",
  value,
}: {
  name?: string;
  value?: Placement;
}) {
  const [selected, setSelected] = useState<Placement>(value ?? DEFAULT_PLACEMENT);

  return (
    <fieldset>
      <legend className="block text-sm font-medium text-muted mb-2">
        Где стоит камера
      </legend>
      <div className="grid gap-2.5 sm:grid-cols-3">
        {PLACEMENTS.map((placement) => {
          const info = PLACEMENT_INFO[placement];
          const active = selected === placement;
          return (
            <label
              key={placement}
              className={`cursor-pointer rounded-lg border px-4 py-3.5 transition-colors ${
                active
                  ? "border-brand bg-soft"
                  : "border-line hover:bg-soft"
              }`}
            >
              <input
                type="radio"
                name={name}
                value={placement}
                checked={active}
                onChange={() => setSelected(placement)}
                className="sr-only"
              />
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`inline-block w-3 h-3 rounded-full border ${
                    active ? "border-4 border-brand" : "border-line"
                  }`}
                />
                <span className="text-sm font-medium text-ink">{info.name}</span>
              </span>
              <span className="block text-xs text-muted mt-1.5 leading-relaxed">
                {info.where}
              </span>
              <span className="block text-xs text-faint mt-1 leading-relaxed">
                {info.gives}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
