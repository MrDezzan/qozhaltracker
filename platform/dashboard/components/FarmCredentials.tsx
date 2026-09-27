"use client";
import { useActionState } from "react";
import {
  resetFarmCredentialsAction,
  CredentialsState,
} from "../app/admin/farms/[id]/credentialActions";
import { CredentialsCard } from "./CredentialsCard";
import { Button } from "./ui/Button";

const initialState: CredentialsState = { status: "idle" };

export function FarmCredentials({
  farmId,
  farmName,
}: {
  farmId: string;
  farmName: string;
}) {
  const [state, formAction, pending] = useActionState(
    resetFarmCredentialsAction,
    initialState
  );

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted leading-relaxed">
        Посмотреть выданный ранее пароль нельзя: в базе хранится только его
        зашифрованный отпечаток. Можно лишь выпустить новый, старый сразу
        перестанет подходить, а уже открытые сессии завершатся в течение часа.
      </p>

      <div className="flex flex-wrap gap-3">
        <form action={formAction}>
          <input type="hidden" name="farmId" value={farmId} />
          <input type="hidden" name="farmName" value={farmName} />
          <input type="hidden" name="target" value="owner" />
          <Button type="submit" variant="secondary" disabled={pending}>
            {pending ? "Выпускаем…" : "Новый пароль клиенту"}
          </Button>
        </form>

        <form action={formAction}>
          <input type="hidden" name="farmId" value={farmId} />
          <input type="hidden" name="farmName" value={farmName} />
          <input type="hidden" name="target" value="device" />
          <Button type="submit" variant="secondary" disabled={pending}>
            {pending ? "Выпускаем…" : "Новый пароль устройству"}
          </Button>
        </form>
      </div>

      {state.status === "error" && <p className="text-sm text-trouble">{state.message}</p>}

      {state.status === "success" && (
        <>
          <div className="rounded-xl border border-line bg-surface px-5 py-4">
            <div className="flex gap-3">
              <span
                aria-hidden
                className="mt-1.5 inline-block w-1.5 h-1.5 rounded-full bg-watch shrink-0"
              />
              <p className="text-sm text-muted leading-relaxed">
                <span className="font-medium text-ink">
                  Скопируйте пароль сейчас.
                </span>{" "}
                {state.target === "device"
                  ? "Устройство на ферме перестанет отправлять данные, пока новые настройки не окажутся в его файле .env."
                  : "Старый пароль перестанет работать. Передайте клиенту новый."}
              </p>
            </div>
          </div>

          <CredentialsCard
            title={
              state.target === "owner"
                ? "Доступ для клиента"
                : "Настройки для мини-ПК на ферме"
            }
            hint={
              state.target === "owner"
                ? "Отправьте владельцу фермы в WhatsApp или Telegram"
                : "Вставить в файл cv-service/.env на устройстве"
            }
            text={state.text}
          />
        </>
      )}
    </div>
  );
}
