import Link from "next/link";
import { FarmCondition, nextStep } from "../lib/analytics";

/**
 * Ответ на единственный вопрос, с которым открывают этот экран:
 * всё ли в порядке на ферме.
 *
 * ПОЧЕМУ НЕ КОЛЬЦО С ЧИСЛОМ
 *
 * Здесь стояла круглая шкала «77 из 100». Выглядела она уместно, а
 * значила мало: семьдесят семь чего? Человек, увидевший её впервые, не
 * знает ни что такое сто, ни насколько плохо семьдесят семь, ни что
 * сделать, чтобы стало больше. Он смотрит на число и идёт искать смысл
 * в остальном экране — то есть шкала отнимала первый взгляд и ничего за
 * него не отдавала.
 *
 * Оценка сама по себе не выбрасывается: по ней считается, спокойно или
 * нет. Но показываем мы не оценку, а вывод и причины — то, ради чего
 * её и считали.
 *
 * ЦВЕТ НЕ ГОВОРИТ НИЧЕГО САМ
 *
 * Рядом всегда слово и значок. Каждый пятнадцатый мужчина не различает
 * красный и зелёный, и на ферме это не экзотика; к тому же экран
 * смотрят на солнце, где зелёный и янтарный сливаются.
 */

type Вид = {
  подпись: string;
  цвет: string;
  фон: string;
  рамка: string;
};

const ВИДЫ: Record<string, Вид> = {
  calm: {
    подпись: "Отклонений нет",
    цвет: "text-calm",
    фон: "bg-calm-bg",
    рамка: "border-calm-line",
  },
  watch: {
    подпись: "Требует внимания",
    цвет: "text-watch",
    фон: "bg-watch-bg",
    рамка: "border-watch-line",
  },
  trouble: {
    подпись: "Требуется вмешательство",
    цвет: "text-trouble",
    фон: "bg-trouble-bg",
    рамка: "border-trouble-line",
  },
};

/** Какое из трёх состояний. Границы те же, что были у оценки. */
export function tone(score: number): "calm" | "watch" | "trouble" {
  if (score >= 85) return "calm";
  if (score >= 60) return "watch";
  return "trouble";
}

function Значок({ вид }: { вид: "calm" | "watch" | "trouble" }) {
  // Значки нарисованы здесь, а не подтянуты библиотекой: их три, и
  // тянуть ради трёх картинок зависимость на полмегабайта незачем
  const общее = "w-9 h-9 shrink-0";
  if (вид === "calm") {
    return (
      <svg className={общее} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
        <path
          d="m8 12.5 2.5 2.5L16 9.5"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (вид === "watch") {
    return (
      <svg className={общее} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
        <path d="M12 7v6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="12" cy="16.5" r="1.2" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg className={общее} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3.5 21.5 20h-19L12 3.5Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M12 10v4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="12" cy="17" r="1.2" fill="currentColor" />
    </svg>
  );
}

export function FarmStatus({
  condition,
  farmName,
}: {
  condition: FarmCondition;
  farmName: string;
}) {
  const вид = tone(condition.score);
  const в = ВИДЫ[вид];
  const шаг = nextStep(condition.reasons);

  return (
    <section
      className={`rounded-[var(--radius-xl)] border ${в.рамка} ${в.фон} px-5 py-6 sm:px-7 sm:py-7`}
      aria-labelledby="farm-status"
    >
      <p className="text-[length:var(--text-sm)] text-muted">
        {farmName}
      </p>

      <div className={`mt-2 flex items-start gap-3 ${в.цвет}`}>
        <Значок вид={вид} />
        <h1
          id="farm-status"
          className="text-[length:var(--text-3xl)] font-semibold leading-tight tracking-tight"
        >
          {в.подпись}
        </h1>
      </div>

      {condition.reasons.length === 0 ? (
        <p className="mt-3 text-[length:var(--text-base)] text-muted">
          Оборудование на связи, поголовье в кадре.
        </p>
      ) : (
        <>
          {/* Причины — это и есть список дел. Поэтому не «показатели»,
              а прямая речь: что не так и что с этим делать */}
          <ul className="mt-4 space-y-2.5">
            {condition.reasons.map((причина) => (
              <li
                key={причина.kind}
                className="flex gap-2.5 text-[length:var(--text-base)] text-ink"
              >
                <span
                  aria-hidden="true"
                  className={`mt-2 h-2 w-2 shrink-0 rounded-full ${в.цвет.replace(
                    "text-",
                    "bg-",
                  )}`}
                />
                <span>{причина.text}</span>
              </li>
            ))}
          </ul>

          {/*
            Куда идти чинить. Без этого человек прочитает, что не так, и
            останется с этим один на один.

            Кнопка подбирается под причину. Там, где фермер сделать
            ничего не может (пропала связь с фермой, нет камер), кнопки
            нет и стоит строка про звонок: кнопка, ведущая не туда,
            хуже её отсутствия.
          */}
          {шаг ? (
            <Link
              href={шаг.href}
              className="tap mt-5 inline-flex items-center justify-center rounded-[var(--button-radius)] border border-action-hover bg-action px-6 text-[length:var(--text-base)] font-semibold text-on-action transition-colors hover:bg-action-hover hover:text-surface"
            >
              {шаг.label}
            </Link>
          ) : (
            <p className="mt-5 text-[length:var(--text-base)] text-muted">
              Устраняется технической службой. Обратитесь в поддержку.
            </p>
          )}
        </>
      )}
    </section>
  );
}
