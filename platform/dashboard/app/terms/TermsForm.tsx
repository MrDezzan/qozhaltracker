"use client";

import { useActionState } from "react";
import { acceptTermsAction, AcceptState } from "./actions";
import { Button } from "../../components/ui/Button";

const INITIAL: AcceptState = { status: "idle" };

export function TermsForm() {
  const [state, action, pending] = useActionState(acceptTermsAction, INITIAL);

  return (
    <form action={action} className="mt-6">
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          name="confirm"
          className="mt-0.5 h-4 w-4 rounded border-line accent-[var(--color-brand)]"
        />
        <span className="text-sm text-muted leading-relaxed">
          Я прочитал условия, принимаю их и подтверждаю, что оформление
          видеонаблюдения за работниками — обязанность моего хозяйства.
        </span>
      </label>

      {state.status === "error" && (
        <p className="text-sm text-trouble mt-3">{state.message}</p>
      )}

      <div className="mt-5">
        <Button type="submit" disabled={pending}>
          {pending ? "Сохраняем…" : "Принимаю"}
        </Button>
      </div>
    </form>
  );
}
