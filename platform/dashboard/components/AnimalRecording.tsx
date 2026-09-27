"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  cancelRecordingAction,
  pollRecordingAction,
  startRecordingAction,
  EnrollState,
} from "../app/animals/enrollActions";
import {
  RecordingSession,
  cameraProgress,
  framesLeftInStep,
  isEnough,
  isStuck,
  progressPercent,
  recordingHint,
  validateLabel,
  viewStates,
} from "../lib/enrollment";
import { SpeechMemory, hush, shouldSpeak, speak } from "../lib/speech";
import { Button } from "./ui/Button";

const INITIAL: EnrollState = { status: "idle" };

export type CameraOption = { id: string; name: string };

/**
 * Выбор камер для записи.
 *
 * Отмечать надо те, что смотрят на ОДНО И ТО ЖЕ место. Правило не
 * формальность: камеры пишут эталоны одновременно, и если перед
 * отмеченной камерой в другом конце фермы стоит другое животное, его
 * кадры лягут под эту кличку — молча и навсегда.
 *
 * Проверить это система не может: она не знает, куда смотрит камера.
 * Поэтому решает человек, и поэтому под галочками написано, зачем они.
 */
function CameraChoice({ cameras }: { cameras: CameraOption[] }) {
  const [picked, setPicked] = useState<string[]>(cameras.map((one) => one.id));

  // Выбор из одного варианта — не выбор, а лишний шаг
  if (cameras.length === 1) {
    return <input type="hidden" name="cameraIds" value={cameras[0].id} />;
  }

  function toggle(id: string) {
    setPicked((was) =>
      was.includes(id) ? was.filter((one) => one !== id) : [...was, id]
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {cameras.map((camera) => (
          <label
            key={camera.id}
            className="flex items-center gap-2 text-sm text-ink"
          >
            <input
              type="checkbox"
              name="cameraIds"
              value={camera.id}
              checked={picked.includes(camera.id)}
              onChange={() => toggle(camera.id)}
              className="accent-[var(--color-brand)]"
            />
            {camera.name}
          </label>
        ))}
      </div>
      <p className="text-xs text-muted">
        Отметьте камеры, которые смотрят на одно и то же место. Каждая
        запомнит животное по-своему: сверху спину, сбоку профиль.
      </p>
    </div>
  );
}

/**
 * Кнопка «Добавить животное».
 *
 * Раньше здесь был выбор камеры, поле, отдельная кнопка «начать запись»
 * и три строки объяснений. Человек стоит у загона с телефоном — ему
 * нужно вписать кличку и нажать одну кнопку.
 */
export function StartRecording({
  cameras,
  existingLabels,
}: {
  cameras: CameraOption[];
  existingLabels: string[];
}) {
  const [state, action, pending] = useActionState(startRecordingAction, INITIAL);
  const [label, setLabel] = useState("");
  const [open, setOpen] = useState(false);

  const problem = label ? validateLabel(label, existingLabels) : "";

  if (cameras.length === 0) return null;

  if (!open) {
    return <Button onClick={() => setOpen(true)}>Добавить животное</Button>;
  }

  return (
    <form action={action} className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          name="label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Кличка или номер"
          autoFocus
          className="border border-line rounded-lg px-3 py-2 text-sm w-44"
        />

        <Button type="submit" disabled={pending || Boolean(problem) || !label.trim()}>
          {pending ? "…" : "Добавить"}
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>

      <CameraChoice cameras={cameras} />

      {problem && <p className="text-sm text-watch">{problem}</p>}
      {state.status === "error" && (
        <p className="text-sm text-trouble">{state.message}</p>
      )}
    </form>
  );
}

/**
 * Дозапись уже заведённого животного.
 *
 * Нужна, когда камеру повесили после заведения: у животного есть
 * эталоны сбоку и ни одного сверху, и верхняя камера его не узнаёт.
 * Обмер силуэта с неё при этом сохраняется ничей — вес посчитан, а кому
 * он принадлежит, неизвестно.
 *
 * Новые эталоны добавляются к прежним, а не заменяют их.
 */
export function RecordAgain({
  animalId,
  label,
  cameras,
}: {
  animalId: string;
  label: string;
  cameras: CameraOption[];
}) {
  const [state, action, pending] = useActionState(startRecordingAction, INITIAL);
  const [open, setOpen] = useState(false);

  if (cameras.length === 0) return null;

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Записать ещё
      </Button>
    );
  }

  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="animalId" value={animalId} />
      <input type="hidden" name="label" value={label} />

      <CameraChoice cameras={cameras} />

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "…" : "Начать запись"}
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Отмена
        </Button>
      </div>

      {state.status === "error" && (
        <p className="text-sm text-trouble">{state.message}</p>
      )}
    </form>
  );
}

/**
 * Идущая запись: одно число и одна кнопка.
 *
 * Человек в этот момент у загона и смотрит на животное, а не на экран.
 * Счётчик обновляется сам.
 */
export function ActiveRecording({
  session,
  cameras = [],
}: {
  session: RecordingSession;
  cameras?: CameraOption[];
}) {
  const router = useRouter();
  const [current, setCurrent] = useState(session);
  const names = Object.fromEntries(cameras.map((one) => [one.id, one.name]));

  useEffect(() => {
    setCurrent(session);
  }, [session]);

  useEffect(() => {
    const timer = setInterval(async () => {
      const fresh = await pollRecordingAction();
      if (!fresh) {
        // Запись закончилась сама. Перерисовываем, чтобы человек увидел итог
        router.refresh();
        return;
      }
      setCurrent(fresh);
    }, 1000);
    return () => clearInterval(timer);
  }, [router]);

  const percent = progressPercent(current);
  const enough = isEnough(current);
  const steps = viewStates(current);
  const phrase = recordingHint(current, names);
  const left = framesLeftInStep(current);
  const byCamera = cameraProgress(current, names);

  // Голос повторяет то, что и так написано под полосой. Дублирование
  // намеренное: человек ведёт животное и на экран не смотрит
  const spoken = useRef<SpeechMemory | null>(null);
  useEffect(() => {
    const now = Date.now();
    if (shouldSpeak(phrase, spoken.current, now)) {
      speak(phrase);
      spoken.current = { said: phrase, at: now };
    }
  }, [phrase]);

  // Замолчать, когда полосы не станет: договаривать подсказку к
  // законченной записи незачем
  useEffect(() => hush, []);

  return (
    <div className="rounded-xl border-2 border-calm/40 bg-calm-bg/50 px-5 py-4 space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-base text-ink">
          {enough ? (
            <>
              <strong className="font-medium">{current.label}</strong> записано
            </>
          ) : (
            <>
              Проведите <strong className="font-medium">{current.label}</strong> мимо
              камеры
            </>
          )}
        </span>
        <span className="text-2xl font-medium text-ink tabular-nums">
          {percent} %
        </span>
      </div>

      <div className="h-2 rounded-full bg-calm/20 overflow-hidden">
        <div
          className="h-full bg-calm transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>

      {/* Разбивка по камерам. Только когда их больше одной: при одной
          это то же самое число, написанное дважды.

          Без неё полоса необъяснима. Боковая камера набрала своё,
          верхняя не видит животное — полоса стоит на половине, и понять,
          мимо какой камеры вести, неоткуда */}
      {byCamera.length > 1 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1">
          {byCamera.map((camera) => (
            <li
              key={camera.id}
              className={`flex items-center gap-1.5 text-sm ${
                camera.done ? "text-calm" : "text-muted"
              }`}
            >
              <span aria-hidden className="w-3 text-center">
                {camera.done ? "✓" : "●"}
              </span>
              {camera.name}
              <span className="tabular-nums text-muted">
                {camera.taken}/{camera.needed}
              </span>
            </li>
          ))}
        </ul>
      )}

      {steps.length > 0 && (
        <ul className="space-y-1.5">
          {steps.map((step) => (
            <li
              key={step.view}
              className={`flex items-center gap-2 text-sm ${
                step.state === "now"
                  ? "text-ink font-medium"
                  : step.state === "done"
                    ? "text-calm"
                    : "text-faint"
              }`}
            >
              <span aria-hidden className="w-4 text-center">
                {step.state === "done"
                  ? "✓"
                  : step.state === "skipped"
                    ? "–"
                    : step.state === "now"
                      ? "●"
                      : "○"}
              </span>
              {step.title}
              {step.state === "now" && left > 0 && (
                <span className="text-xs text-muted">ещё {left}</span>
              )}
              {step.state === "skipped" && (
                <span className="text-xs text-faint">пропущено</span>
              )}
            </li>
          ))}
        </ul>
      )}

      <p
        className={`text-sm ${
          isStuck(current) ? "text-watch font-medium" : "text-muted"
        }`}
      >
        {phrase}
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <form action={cancelRecordingAction}>
          <input type="hidden" name="sessionId" value={current.id} />
          <Button type="submit" variant="secondary">
            Отменить
          </Button>
        </form>
      </div>
    </div>
  );
}

/** Что делать. Три строки — потому что шагов ровно три. */
export function RecordingGuide() {
  return (
    <ol className="text-sm text-muted leading-relaxed space-y-2 text-left inline-block">
      <li>
        <span className="text-faint mr-1.5">1.</span>
        Нажмите «Добавить животное» и укажите кличку.
      </li>
      <li>
        <span className="text-faint mr-1.5">2.</span>
        Проведите его вокруг камеры полным кругом —{" "}
        <strong className="font-medium text-ink">одно</strong>, без
        соседей. Полминуты хватит.
      </li>
      <li>
        <span className="text-faint mr-1.5">3.</span>
        Готово. Камера распознаёт животное самостоятельно.
      </li>
    </ol>
  );
}
