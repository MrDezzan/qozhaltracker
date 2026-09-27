"use client";

import { useActionState, useEffect, useRef } from "react";
import { reviewFrameAction, type ReviewState } from "../app/admin/training/actions";
import { REASON_LABELS, type TrainingFrame, type Verdict } from "../lib/training";

const INITIAL: ReviewState = { status: "idle" };

/**
 * Кнопки отбраковки.
 *
 * Порядок не случайный: сначала то, что нажимается чаще всего. По опыту
 * первых прогонов большая часть отобранных кадров оказывается нормальной,
 * и «Верно» должно быть под большим пальцем.
 *
 * Цифра — горячая клавиша. Без них отбраковка тысячи кадров это тысяча
 * прицельных нажатий мышью, и рука устаёт раньше, чем кончаются кадры.
 */
const BUTTONS: {
  verdict: Verdict;
  key: string;
  label: string;
  hint: string;
  tone: string;
}[] = [
  {
    verdict: "ok",
    key: "1",
    label: "Верно",
    hint: "Все животные обведены, лишнего нет",
    tone: "border-calm/30 bg-calm-bg text-calm hover:bg-calm/20",
  },
  {
    verdict: "merged",
    key: "2",
    label: "Слиплись",
    hint: "Двое и больше обведены одним контуром",
    tone: "border-watch/30 bg-watch-bg text-watch hover:bg-watch/20",
  },
  {
    verdict: "missed",
    key: "3",
    label: "Пропустила",
    hint: "Животное в кадре есть, а контура на нём нет",
    tone: "border-brand/30 bg-brand-soft text-brand hover:bg-brand/20",
  },
  {
    verdict: "junk",
    key: "4",
    label: "Мусор",
    hint: "Засвет, темнота, камера сдвинулась: размечать нечего",
    tone: "border-line bg-surface text-muted hover:bg-soft",
  },
];

export function TrainingReview({
  frame,
  imageUrl,
}: {
  frame: TrainingFrame;
  imageUrl: string | null;
}) {
  const [state, formAction, pending] = useActionState(reviewFrameAction, INITIAL);
  const formRef = useRef<HTMLFormElement>(null);

  const boxes = frame.detections?.boxes ?? [];
  const count = frame.detections?.count ?? boxes.length;
  const reason = REASON_LABELS[frame.reason] ?? {
    title: frame.reason,
    hint: "",
  };

  // Горячие клавиши. Отбраковка идёт сотнями кадров подряд, и переносить
  // руку на мышь на каждом — это и есть разница между «полчаса» и
  // «полдня»
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (pending) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const button = BUTTONS.find((b) => b.key === event.key);
      if (!button || !formRef.current) return;

      event.preventDefault();
      const data = new FormData(formRef.current);
      data.set("verdict", button.verdict);
      formAction(data);
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [formAction, pending]);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-3">
        <div>
          <span className="text-sm font-medium text-ink">{reason.title}</span>
          {reason.hint && (
            <span className="text-sm text-muted"> · {reason.hint}</span>
          )}
        </div>
        <span className="text-sm text-faint tabular-nums">
          осталось {frame.pending}
        </span>
      </div>

      <div className="relative rounded-xl overflow-hidden bg-brand select-none">
        {imageUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={imageUrl}
            alt="Кадр с камеры"
            className="w-full block"
            draggable={false}
          />
        ) : (
          <div className="aspect-video flex items-center justify-center px-6 text-center">
            <p className="text-sm text-faint">
              Файл кадра не открывается. Отметьте «Мусор», такой кадр
              всё равно не разметить.
            </p>
          </div>
        )}

        {/*
          Рамки рисуются ПОВЕРХ картинки, а не на ней. Кадр в хранилище
          обязан остаться чистым: с нарисованными линиями он непригоден
          для обучения: модель научится искать зелёные прямоугольники.

          viewBox 0..1 и preserveAspectRatio="none": координаты приходят
          долями от размера кадра, и слой сам растягивается под картинку
          любого размера, от телефона до монитора.
        */}
        {imageUrl && boxes.length > 0 && (
          <svg
            viewBox="0 0 1 1"
            preserveAspectRatio="none"
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden
          >
            {boxes.map((box, i) => (
              <rect
                key={i}
                x={box.x}
                y={box.y}
                width={box.w}
                height={box.h}
                fill="none"
                stroke={box.c < 0.6 ? "var(--color-watch)" : "var(--color-calm)"}
                strokeWidth={0.003}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-sm text-muted">
        <span className="text-ink font-medium">
          нашла: {count} {count === 1 ? "животное" : "жив."}
        </span>
        <span>{frame.farm_name}</span>
        <span>{frame.camera_name}</span>
        <span className="tabular-nums">
          {new Date(frame.captured_at).toLocaleString("ru-RU", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
        {/* Жёлтая рамка = модель сомневалась. Без подписи цвет читается
            как «эта чем-то отличается», а чем — непонятно */}
        {boxes.some((b) => b.c < 0.6) && (
          <span className="text-watch">жёлтым: где модель сомневалась</span>
        )}
      </div>

      <form ref={formRef} action={formAction} className="mt-5">
        <input type="hidden" name="frameId" value={frame.id} />

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {BUTTONS.map((button) => (
            <button
              key={button.verdict}
              type="submit"
              name="verdict"
              value={button.verdict}
              disabled={pending}
              title={button.hint}
              className={`rounded-xl border px-3 py-3 text-left transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${button.tone}`}
            >
              <span className="flex items-baseline gap-2">
                <span className="text-sm font-medium">{button.label}</span>
                <span className="text-xs opacity-50 tabular-nums">{button.key}</span>
              </span>
              <span className="block text-xs opacity-70 mt-0.5 leading-snug">
                {button.hint}
              </span>
            </button>
          ))}
        </div>
      </form>

      {state.status === "error" && (
        <p className="mt-3 text-sm text-trouble">{state.message}</p>
      )}
    </div>
  );
}
