"use client";

import { useActionState } from "react";
import {
  setGuardWindowAction,
  setRetentionAction,
  setTimezoneAction,
  SettingsState,
} from "../app/settings/actions";
import { Button } from "./ui/Button";
import {
  AlertSettings,
  RetentionPolicy,
  TIMEZONES,
  describeDays,
  DAY_GUARD_OPTIONS,
  describeGuardWindow,
  toTimeInput,
} from "../lib/settings";

const INITIAL: SettingsState = { status: "idle" };

function Message({ state }: { state: SettingsState }) {
  if (state.status === "idle") return null;
  return (
    <p
      className={`text-sm ${state.status === "error" ? "text-trouble" : "text-muted"}`}
    >
      {state.message}
    </p>
  );
}

export function TimezoneForm({ timezone }: { timezone: string }) {
  const [state, action, pending] = useActionState(setTimezoneAction, INITIAL);

  return (
    <form action={action} className="px-5 sm:px-6 pb-6 space-y-4 max-w-md">
      <p className="text-sm text-muted leading-relaxed">
        По этим часам считаются графики «по часам суток» и показывается время
        событий. Данные хранятся в едином времени, так что смена пояса
        пересчитает уже накопленное, а не испортит его.
      </p>
      <select
        name="timezone"
        defaultValue={timezone}
        className="w-full rounded-lg border border-line px-3 py-2 text-sm bg-surface"
      >
        {TIMEZONES.map((tz) => (
          <option key={tz.value} value={tz.value}>
            {tz.label}
          </option>
        ))}
      </select>
      <Message state={state} />
      <Button type="submit" disabled={pending}>
        {pending ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}

export function RetentionForm({ retention }: { retention: RetentionPolicy }) {
  const [state, action, pending] = useActionState(setRetentionAction, INITIAL);

  const rows: { key: string; name: string; value: number; hint: string }[] = [
    {
      key: "eventsDays",
      name: "События и визиты",
      value: retention.events_days,
      hint: "История хозяйства: подсчёты, время у кормушек",
    },
    {
      key: "sightingsDays",
      name: "Кадры без клички",
      value: retention.sightings_days,
      hint: "Названные кадры не удаляются: на них держится распознавание",
    },
    {
      key: "snapshotsDays",
      name: "Кадры предпросмотра",
      value: retention.snapshots_days,
      hint: "Расходный материал, занимает больше всего места",
    },
  ];

  return (
    <form action={action} className="px-5 sm:px-6 pb-6 space-y-5">
      <p className="text-sm text-muted leading-relaxed">
        Старые данные убираются каждую ночь. Без ограничений хранилище растёт
        без остановки и рано или поздно кончится.
      </p>

      <div className="space-y-4 max-w-lg">
        {rows.map((row) => (
          <div key={row.key} className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
              <label
                htmlFor={row.key}
                className="block text-sm text-ink"
              >
                {row.name}
              </label>
              <p className="text-xs text-faint mt-0.5 leading-relaxed">
                {row.hint}
              </p>
            </div>
            <div className="shrink-0 text-right">
              <input
                id={row.key}
                name={row.key}
                type="number"
                min={1}
                defaultValue={row.value}
                className="w-24 rounded-lg border border-line px-3 py-2 text-sm tabular"
              />
              <div className="text-xs text-faint mt-1">
                {describeDays(row.value)}
              </div>
            </div>
          </div>
        ))}
      </div>

      <Message state={state} />
      <Button type="submit" disabled={pending}>
        {pending ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}


/**
 * Охранное окно: когда человек в кадре считается посторонним.
 *
 * Единственная настройка охраны, которую точно придётся править по месту:
 * на одной ферме сторож обходит территорию в полночь, на другой доярки
 * приходят в четыре утра. Оставить её только в базе — значит оставить
 * навсегда в значении по умолчанию.
 */
export function GuardWindowForm({ settings }: { settings: AlertSettings }) {
  const [state, action, pending] = useActionState(setGuardWindowAction, INITIAL);

  const from = toTimeInput(settings.guard_from, "22:00");
  const to = toTimeInput(settings.guard_to, "06:00");

  return (
    <form action={action} className="px-5 sm:px-6 pb-6 space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="block text-muted mb-1.5">Начало</span>
          <input
            type="time"
            name="guardFrom"
            defaultValue={from}
            className="border border-line rounded-lg px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="block text-muted mb-1.5">Конец</span>
          <input
            type="time"
            name="guardTo"
            defaultValue={to}
            className="border border-line rounded-lg px-3 py-2"
          />
        </label>
        <Button type="submit" disabled={pending}>
          {pending ? "Сохраняем…" : "Сохранить"}
        </Button>
      </div>

      <p className="text-sm text-muted leading-relaxed">
        Охрана смотрит <strong className="font-medium">круглосуточно</strong>.
        Эти часы задают не время работы, а строгость: {describeGuardWindow(from, to)}
        {" "}тревога срочная и поднимается через 5 секунд, в остальное время —
        мягче и через 30.
      </p>

      <fieldset className="space-y-2">
        <legend className="text-sm text-muted mb-1.5">
          Человек в кадре вне этих часов
        </legend>
        {DAY_GUARD_OPTIONS.map((option) => (
          <label
            key={option.value}
            className="flex items-start gap-3 rounded-lg border border-line px-4 py-3 cursor-pointer"
          >
            <input
              type="radio"
              name="daySeverity"
              value={option.value}
              defaultChecked={settings.guard_day_severity === option.value}
              className="mt-0.5"
            />
            <span className="text-sm">
              <span className="font-medium text-ink">{option.name}</span>
              <span className="block text-muted mt-0.5 leading-relaxed">
                {option.note}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      <p className="text-xs text-faint leading-relaxed">
        Работает только на камерах, где охрана включена отдельно. Если тревоги
        приходят на своих же людей — сдвиньте часы или смягчите дневной режим,
        а не отключайте охрану целиком.
      </p>

      {state.status !== "idle" && (
        <p
          className={
            state.status === "error"
              ? "text-sm text-trouble"
              : "text-sm text-muted"
          }
        >
          {state.message}
        </p>
      )}
    </form>
  );
}

