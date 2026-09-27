"use client";

import { useState } from "react";
import { deleteAnimalAction } from "../app/animals/enrollActions";

/**
 * Удаление животного — с подтверждением.
 *
 * Крестик в углу строки нажимается случайно, а вместе с животным
 * уходят его записанные ракурсы, взвешивания и вся история. Вернуть
 * это нечем, поэтому один лишний клик здесь оправдан.
 */
export function DeleteAnimal({ animalId, label }: { animalId: string; label: string }) {
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button
        type="button"
        onClick={() => setAsking(true)}
        aria-label={`Удалить «${label}»`}
        className="text-faint hover:text-trouble transition-colors px-2"
      >
        ×
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <form action={deleteAnimalAction}>
        <input type="hidden" name="animalId" value={animalId} />
        <button type="submit" className="text-sm text-trouble hover:underline">
          Удалить
        </button>
      </form>
      <button
        type="button"
        onClick={() => setAsking(false)}
        className="text-sm text-faint hover:text-ink"
      >
        Нет
      </button>
    </span>
  );
}
