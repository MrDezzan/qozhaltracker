"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CameraSnapshot, isSnapshotStale } from "../lib/snapshots";
import {
  VIEW_MODE_LABEL,
  ViewMode,
  defaultMode,
  gridClass,
  isCrowded,
} from "../lib/cameraLayout";
import { timeAgo } from "../lib/format";
import { LiveCamera } from "./LiveCamera";

/**
 * Видеонаблюдение: трансляция с выбранной камеры.
 *
 * ОКНО ПОКАЗЫВАЕТСЯ ТОЛЬКО ТАМ, ГДЕ ЕСТЬ КАДР
 *
 * Раньше камера без кадра давала пустой прямоугольник с подписью
 * «Кадр с камеры №1». Подпись утверждала, что кадр есть, прямоугольник
 * был пуст, и человек полминуты решал, сломана камера, сеть или сама
 * программа. Теперь камера без кадра в перечень трансляций не попадает
 * вовсе: о ней сказано отдельной строкой, с временем последнего кадра.
 *
 * ПЕРЕКЛЮЧАТЕЛЬ СВЕРХУ
 *
 * Номер и название камеры стоят в заголовке, перечень камер под ним.
 * Стрелки «вперёд-назад» остались бы единственным способом дойти до
 * двадцатой камеры, а это двадцать нажатий вслепую.
 */

type Props = {
  snapshots: CameraSnapshot[];
  /**
   * Время сервера на момент отрисовки. Обязательный: если брать здесь
   * собственное время браузера, первая отрисовка на клиенте разойдётся
   * с серверной и React пожалуется на несовпадение.
   */
  now: Date;
  /**
   * Настроен ли просмотр через интернет. Читается на сервере (адрес сервера
   * видео там), поэтому приходит сюда сверху, а не берётся из окружения.
   */
  remoteAvailable?: boolean;
};

/** Камера с её номером в перечне: номер не должен зависеть от фильтров. */
type Нумерованная = CameraSnapshot & { номер: number };

export function CameraSnapshots({
  snapshots,
  now: serverNow,
  remoteAvailable = false,
}: Props) {
  const [liveCameraId, setLiveCameraId] = useState<string | null>(null);
  const пронумерованы: Нумерованная[] = useMemo(
    () => snapshots.map((s, i) => ({ ...s, номер: i + 1 })),
    [snapshots],
  );
  const сСигналом = useMemo(
    () => пронумерованы.filter((s) => s.url),
    [пронумерованы],
  );
  const безСигнала = useMemo(
    () => пронумерованы.filter((s) => !s.url),
    [пронумерованы],
  );

  const [mode, setMode] = useState<ViewMode>(() => defaultMode(сСигналом.length));
  const [current, setCurrent] = useState(0);

  // Отсчёт идёт от времени сервера: к нему прибавляется то, что прошло
  // с загрузки страницы. Так первая отрисовка совпадает с серверной,
  // подпись «минуту назад» продолжает тикать, и сбитые часы на телефоне
  // не превращают свежий кадр во вчерашний.
  const [elapsedMs, setElapsedMs] = useState(0);
  useEffect(() => {
    const mountedAt = Date.now();
    const timer = setInterval(() => setElapsedMs(Date.now() - mountedAt), 10_000);
    return () => clearInterval(timer);
  }, [serverNow]);

  const now = elapsedMs === 0 ? serverNow : new Date(serverNow.getTime() + elapsedMs);

  const closeLive = useCallback(() => setLiveCameraId(null), []);

  // Камеру могли отключить, пока страница была открыта
  const выбран = Math.min(current, Math.max(0, сСигналом.length - 1));
  // При одной камере режима «сетка» не существует: заголовок обязан
  // назвать камеру, а не говорить «с камер» о единственной
  const режим: ViewMode = сСигналом.length === 1 ? "single" : mode;
  const показать = режим === "single" ? сСигналом.slice(выбран, выбран + 1) : сСигналом;

  if (snapshots.length === 0) {
    return (
      <Сообщение
        заголовок="Камеры не подключены"
        текст="Оборудование устанавливает монтажная служба. После установки трансляция появится здесь."
      />
    );
  }

  if (сСигналом.length === 0) {
    return (
      <>
        <Сообщение
          заголовок="Сигнал с камер не поступает"
          текст="Проверьте питание оборудования и подключение к сети. Если связь не восстановится, обратитесь в техническую поддержку."
        />
        <ПереченьБезСигнала камеры={безСигнала} now={now} />
      </>
    );
  }

  const текущая = сСигналом[выбран];
  const live = сСигналом.find((s) => s.cameraId === liveCameraId) ?? null;

  return (
    <>
      <h2 className="text-[length:var(--text-lg)] font-bold text-ink">
        {режим === "single" ? (
          <>
            Трансляция с камеры №{текущая.номер}
            <span className="ml-2 font-normal text-muted">
              {текущая.cameraName}
            </span>
          </>
        ) : (
          "Трансляция с камер"
        )}
      </h2>

      {/*
        Один переключатель, а не два.

        Сначала рядом стояли выбор вида («Сетка» или «Одна камера») и
        отдельный перечень камер. Два органа управления одним и тем же:
        человек нажимал камеру, вид оставался сетчатым, и казалось, что
        нажатие не сработало. Теперь это один перечень, где «Все камеры»
        такой же пункт, как любая камера.
      */}
      {сСигналом.length > 1 && (
        <div
          role="tablist"
          aria-label="Выбор камеры"
          className="mt-3 flex flex-wrap gap-2"
        >
          <button
            type="button"
            role="tab"
            aria-selected={режим === "grid"}
            onClick={() => setMode("grid")}
            className={`tap inline-flex items-center rounded-[var(--radius-md)] border px-3 text-[length:var(--text-sm)] font-medium transition-colors ${
              режим === "grid"
                ? "border-brand bg-brand text-on-brand"
                : "border-line-strong bg-surface text-ink hover:border-brand"
            }`}
          >
            {VIEW_MODE_LABEL.grid}
          </button>

          {сСигналом.map((snapshot, index) => {
            const устарел = isSnapshotStale(snapshot.updatedAt, now);
            const активна = режим === "single" && index === выбран;
            return (
              <button
                key={snapshot.cameraId}
                type="button"
                role="tab"
                aria-selected={активна}
                onClick={() => {
                  setCurrent(index);
                  setMode("single");
                }}
                className={`tap inline-flex items-center gap-2 rounded-[var(--radius-md)] border px-3 text-[length:var(--text-sm)] font-medium transition-colors ${
                  активна
                    ? "border-brand bg-brand text-on-brand"
                    : "border-line-strong bg-surface text-ink hover:border-brand"
                }`}
              >
                <span
                  aria-hidden
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    устарел ? "bg-watch" : "bg-calm"
                  }`}
                />
                <span className="tabular">№{snapshot.номер}</span>
                <span className="max-w-[12ch] truncate font-normal">
                  {snapshot.cameraName}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {режим === "grid" && isCrowded(сСигналом.length) && (
        <p className="mt-3 text-[length:var(--text-sm)] text-faint">
          Камер больше десяти. Отдельная камера показывается крупнее.
        </p>
      )}

      <div
        className={`mt-4 grid gap-3 ${режим === "single" ? "grid-cols-1" : gridClass(сСигналом.length)}`}
      >
        {показать.map((snapshot) => {
          const устарел = isSnapshotStale(snapshot.updatedAt, now);
          const можноСмотреть = Boolean(snapshot.liveUrl);
          return (
            <figure key={snapshot.cameraId} className="min-w-0">
              <button
                type="button"
                disabled={!можноСмотреть}
                onClick={() => setLiveCameraId(snapshot.cameraId)}
                aria-label={`Открыть трансляцию с камеры №${snapshot.номер}, ${snapshot.cameraName}`}
                className="group relative block aspect-video w-full overflow-hidden rounded-[var(--radius-lg)] border border-line bg-dark disabled:cursor-default"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  // Метка меняется вместе с кадром — иначе браузер
                  // покажет прежнюю картинку по тому же адресу
                  src={`${snapshot.url}?t=${snapshot.updatedAt ?? ""}`}
                  alt={`Камера №${snapshot.номер}, ${snapshot.cameraName}`}
                  className={`h-full w-full object-cover ${устарел ? "opacity-60" : ""}`}
                />

                {/* Подпись поверх кадра, а не под ним: в сетке из
                    двенадцати камер отдельная строка на каждую съедала
                    больше места, чем сами кадры */}
                <span className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-gradient-to-t from-dark/80 to-transparent px-3 pt-8 pb-2">
                  <span className="truncate text-[length:var(--text-sm)] font-medium text-on-dark">
                    №{snapshot.номер} {snapshot.cameraName}
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1.5 text-[length:var(--text-xs)] text-on-dark-muted">
                    <span
                      aria-hidden
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        устарел ? "bg-watch" : "bg-calm"
                      }`}
                    />
                    {snapshot.updatedAt
                      ? `кадр ${timeAgo(snapshot.updatedAt, now)}`
                      : "время кадра неизвестно"}
                  </span>
                </span>

                {можноСмотреть && (
                  <span className="absolute inset-0 flex items-center justify-center transition-colors group-hover:bg-dark/40">
                    <span className="rounded-[var(--radius-md)] bg-surface px-4 py-2 text-[length:var(--text-sm)] font-semibold text-ink opacity-0 transition-opacity group-hover:opacity-100">
                      Открыть трансляцию
                    </span>
                  </span>
                )}
              </button>
            </figure>
          );
        })}
      </div>

      <ПереченьБезСигнала камеры={безСигнала} now={now} />

      {live && (
        <LiveCamera
          snapshot={live}
          onClose={closeLive}
          remoteAvailable={remoteAvailable}
        />
      )}
    </>
  );
}

function Сообщение({
  заголовок,
  текст,
}: {
  заголовок: string;
  текст: string;
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-soft px-5 py-6">
      <p className="text-[length:var(--text-base)] font-semibold text-ink">
        {заголовок}
      </p>
      <p className="mt-1.5 max-w-prose text-[length:var(--text-sm)] text-muted">
        {текст}
      </p>
    </div>
  );
}

/**
 * Камеры, с которых кадр не пришёл.
 *
 * Строкой, а не пустым окном. Пустое окно с подписью «Камера №2»
 * выглядит как неисправность программы, а строка «кадров не поступало»
 * называет неисправность своим именем и указывает, где искать.
 */
function ПереченьБезСигнала({
  камеры,
  now,
}: {
  камеры: Нумерованная[];
  now: Date;
}) {
  if (камеры.length === 0) return null;

  return (
    <div className="mt-4 rounded-[var(--radius-lg)] border border-line bg-soft px-4 py-3">
      <p className="text-[length:var(--text-sm)] font-semibold text-ink">
        Без сигнала: {камеры.length}
      </p>
      <ul className="mt-2 space-y-1">
        {камеры.map((камера) => (
          <li
            key={камера.cameraId}
            className="flex flex-wrap items-baseline justify-between gap-x-4 text-[length:var(--text-sm)] text-muted"
          >
            <span className="text-ink">
              <span className="tabular">№{камера.номер}</span> {камера.cameraName}
            </span>
            <span>
              {камера.updatedAt
                ? `последний кадр ${timeAgo(камера.updatedAt, now)}`
                : "кадров не поступало"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
