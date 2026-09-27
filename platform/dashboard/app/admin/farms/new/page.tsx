"use client";
import { useActionState } from "react";
import Link from "next/link";
import { createFarmAction, CreateFarmState } from "./actions";
import { CredentialsCard } from "../../../../components/CredentialsCard";
import { PageHeader } from "../../../../components/ui/PageHeader";
import { Card, CardBody } from "../../../../components/ui/Card";
import { Button } from "../../../../components/ui/Button";
import { Field } from "../../../../components/ui/Field";

const initialState: CreateFarmState = { status: "idle" };

export default function NewFarmPage() {
  const [state, formAction, pending] = useActionState(createFarmAction, initialState);

  if (state.status === "success") {
    return (
      <main className="max-w-2xl">
        <PageHeader
          title={`Ферма «${state.farmName}» создана`}
          description="Скопируйте оба блока: пароли больше не отображаются"
        />

        <div className="mb-6 rounded-xl border border-line bg-surface px-5 py-4">
          <div className="flex gap-3">
            <span
              aria-hidden
              className="mt-1.5 inline-block w-1.5 h-1.5 rounded-full bg-watch shrink-0"
            />
            <p className="text-sm text-muted leading-relaxed">
              <span className="font-medium text-ink">Сохраните пароли сейчас.</span>{" "}
              В базе хранится только их зашифрованный отпечаток, восстановить оригинал
              нельзя. Если пароль потеряется, придётся выпустить новый.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <CredentialsCard
            title="Доступ для клиента"
            hint="Отправьте владельцу фермы в WhatsApp или Telegram"
            text={state.ownerText}
          />
          <CredentialsCard
            title="Настройки для мини-ПК на ферме"
            hint="Вставить в файл cv-service/.env на устройстве"
            text={state.deviceText}
          />
        </div>

        <div className="flex gap-3 mt-8">
          <Link href="/admin">
            <Button>К списку ферм</Button>
          </Link>
          <Link href="/admin/farms/new">
            <Button variant="secondary">Создать ещё одну</Button>
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-xl">
      <PageHeader
        title="Создать ферму"
        description="Логины формируются автоматически"
      />

      <Card>
        <CardBody className="!pt-6">
          <form action={formAction} className="space-y-5">
            <Field
              label="Название фермы"
              name="farmName"
              required
              placeholder="КХ Заря"
              hint="Так ферма будет называться в списке и в сообщении клиенту"
            />
            <Button type="submit" disabled={pending}>
              {pending ? "Создаём…" : "Создать ферму"}
            </Button>
            {state.status === "error" && (
              <p className="text-sm text-trouble">{state.message}</p>
            )}
          </form>
        </CardBody>
      </Card>

      <div className="mt-6 rounded-xl border border-line bg-surface px-6 py-5">
        <h3 className="text-sm font-medium text-ink mb-3">Что произойдёт</h3>
        <ol className="text-sm text-muted space-y-2 list-decimal list-inside leading-relaxed">
          <li>Логин владельца: вход на экран фермы</li>
          <li>Логин устройства: для мини-ПК с камерами</li>
          <li>Вы получите два готовых текста: клиенту и для настройки устройства</li>
          <li>Камеры добавляются после этого в карточке фермы</li>
        </ol>
      </div>
    </main>
  );
}
