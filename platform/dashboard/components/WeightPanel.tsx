"use client";

import { useActionState } from "react";
import { addWeighingAction, WeighingState } from "../app/animals/weightActions";
import { Button } from "./ui/Button";
import { MIN_WEIGHINGS, WeightModel, weighingsRemaining } from "../lib/weights";

const INITIAL: WeighingState = { status: "idle" };

type Props = {
  animals: { animalId: string; label: string }[];
  model: WeightModel | null;
  weighingsDone: number;
};

/**
 * Ввод веса с настоящих весов.
 *
 * Единственное, что человек должен здесь делать. Раньше рядом жила
 * таблица с оценками веса по всем животным — ровно та же, что и в
 * списке выше, — и кнопка «пересчитать формулу», про которую никто не
 * понимал, зачем она и когда её жать.
 */
export function WeightPanel({ animals, model, weighingsDone }: Props) {
  const [state, action, saving] = useActionState(addWeighingAction, INITIAL);
  const remaining = weighingsRemaining(weighingsDone);

  return (
    <div className="px-5 sm:px-6 pb-6 space-y-4">
      <p className="text-sm text-muted leading-relaxed">
        {model ? (
          <>
            Система знает, сколько весят ваши животные — она научилась этому по{" "}
            {weighingsDone} взвешиваниям. Чем больше вносите, тем точнее.
          </>
        ) : (
          <>
            Взвесьте {MIN_WEIGHINGS} животных на обычных весах и впишите
            килограммы — после этого система начнёт показывать вес остальных
            сама. Осталось {remaining}.
          </>
        )}
      </p>

      <form action={action} className="flex flex-wrap items-center gap-2">
        <select
          name="animalId"
          defaultValue=""
          className="rounded-lg border border-line px-3 py-2 text-sm bg-surface"
        >
          <option value="" disabled>
            Кого взвесили
          </option>
          {animals.map((animal) => (
            <option key={animal.animalId} value={animal.animalId}>
              {animal.label}
            </option>
          ))}
        </select>

        <input
          name="weightKg"
          inputMode="decimal"
          placeholder="кг"
          className="rounded-lg border border-line px-3 py-2 text-sm w-24"
        />

        <Button type="submit" disabled={saving || animals.length === 0}>
          {saving ? "Сохраняем…" : "Записать"}
        </Button>
      </form>

      {state.status !== "idle" && (
        <p
          className={`text-sm ${
            state.status === "error" ? "text-trouble" : "text-muted"
          }`}
        >
          {state.message}
        </p>
      )}
    </div>
  );
}
