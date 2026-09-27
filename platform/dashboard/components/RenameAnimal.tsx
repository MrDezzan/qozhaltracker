"use client";

import { useState } from "react";
import { renameAnimalAction } from "../app/animals/enrollActions";
import { Button } from "./ui/Button";

/**
 * Переименование прямо в карточке.
 *
 * Клички меняются: «№ 12» становится «Зорькой», когда до неё дошли руки.
 * Ради этого не должно быть отдельного экрана редактирования.
 */
export function RenameAnimal({ animalId, label }: { animalId: string; label: string }) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-muted hover:text-ink transition-colors"
      >
        Переименовать
      </button>
    );
  }

  return (
    <form action={renameAnimalAction} className="flex items-center gap-2">
      <input type="hidden" name="animalId" value={animalId} />
      <input
        name="label"
        defaultValue={label}
        autoFocus
        className="border border-line rounded-lg px-3 py-2 text-sm w-40"
      />
      <Button type="submit">Сохранить</Button>
      <Button variant="secondary" onClick={() => setOpen(false)}>
        Отмена
      </Button>
    </form>
  );
}
