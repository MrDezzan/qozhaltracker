"use client";

import { useActionState } from "react";
import { runDetectionAction, ActionState } from "../app/alertActions";

const INITIAL: ActionState = { status: "idle" };

/**
 * Отклонения ищет расписание раз в десять минут. Кнопка нужна, когда
 * хозяин только что разобрался с происшествием и хочет сразу увидеть
 * результат, а не ждать очередного круга.
 */
export function DetectNowButton() {
  const [state, action, pending] = useActionState(runDetectionAction, INITIAL);

  return (
    <form action={action} className="flex items-center gap-3">
      {state.status !== "idle" && (
        <span
          className={`text-xs ${
            state.status === "error" ? "text-trouble" : "text-muted"
          }`}
        >
          {state.message}
        </span>
      )}
      <button
        type="submit"
        disabled={pending}
        className="text-sm text-muted hover:text-ink underline underline-offset-2 disabled:opacity-40"
      >
        {pending ? "Проверяем…" : "Проверить сейчас"}
      </button>
    </form>
  );
}
