"use client";
import { useActionState } from "react";
import { addCameraAction, CameraActionState } from "../app/admin/farms/[id]/actions";
import { Button } from "./ui/Button";
import { Field } from "./ui/Field";
import { PlacementPicker } from "./PlacementPicker";

const initialState: CameraActionState = { status: "idle" };

export function AddCameraForm({ farmId }: { farmId: string }) {
  const [state, formAction, pending] = useActionState(addCameraAction, initialState);

  return (
    <form action={formAction} className="space-y-5 max-w-xl">
      <input type="hidden" name="farmId" value={farmId} />
      <Field label="Название" name="name" required placeholder="Кормушка" />
      <Field
        label="Адрес потока"
        name="sourceUri"
        required
        mono
        placeholder="rtsp://admin:пароль@192.168.1.64:554/stream1"
        hint="Проверьте адрес в VLC. Пошло видео, значит верный."
      />
      <PlacementPicker />
      <Field
        label="Поток по локальной сети"
        name="streamUrl"
        mono
        placeholder="http://192.168.1.50:8089/stream/<камера>?token=…"
        hint="Необязательно. Работает, только когда телефон в сети фермы."
      />
      <Button type="submit" disabled={pending}>
        {pending ? "Добавляем…" : "Добавить камеру"}
      </Button>
      {state.status === "error" && <p className="text-sm text-trouble">{state.message}</p>}
    </form>
  );
}
