"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CameraSnapshot, streamUrl } from "../lib/snapshots";
import { requestLiveViewAction } from "../app/alertActions";
import {
  startRemoteStreamAction,
  stopRemoteStreamAction,
} from "../app/remoteStreamActions";
import type { StreamSession } from "../lib/remoteStream";
import { RemoteVideo } from "./RemoteVideo";
import { Button } from "./ui/Button";

/** Как часто просить у фермы продлить живой режим. */
const KEEPALIVE_MS = 30_000;
/** Как часто забирать кадр. Ферма в живом режиме отдаёт примерно раз в секунду. */
const FRAME_MS = 1000;
/** Через сколько без действий выключить живой режим сами. */
const IDLE_TIMEOUT_MS = 5 * 60_000;
/**
 * Кадр старше этого означает, что ферма отдаёт снимки в обычном режиме
 * (раз в 15 секунд), то есть до неё просьба о живом просмотре не дошла.
 */
const LIVE_EXPECTED_MS = 6_000;

type LiveRequest = { ok: true } | { ok: false; message: string } | null;

type Props = {
  snapshot: CameraSnapshot;
  onClose: () => void;
  /**
   * Настроен ли просмотр через интернет. Приходит сверху, потому что адрес
   * сервера видео читается на сервере, а это клиентский компонент.
   */
  remoteAvailable?: boolean;
};

/**
 * Возраст кадра по заголовкам ответа.
 *
 * Считаем от времени сервера, а не от часов браузера: на телефоне с
 * убежавшими часами свежий кадр иначе выглядел бы вчерашним.
 */
export function frameAgeMs(headers: Headers, fallbackNow: number): number | null {
  const modified = headers.get("last-modified");
  if (!modified) return null;

  const modifiedAt = new Date(modified).getTime();
  if (Number.isNaN(modifiedAt)) return null;

  const serverDate = headers.get("date");
  const referenceNow = serverDate ? new Date(serverDate).getTime() : NaN;
  const reference = Number.isNaN(referenceNow) ? fallbackNow : referenceNow;

  return reference - modifiedAt;
}

export function describeFrameAge(ms: number | null): string {
  if (ms === null) return "";
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 3) return "кадр только что";
  if (seconds < 60) return `кадр ${seconds} с назад`;
  const minutes = Math.round(seconds / 60);
  return `кадр ${minutes} мин назад`;
}

export function LiveCamera({ snapshot, onClose, remoteAvailable = false }: Props) {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [liveRequest, setLiveRequest] = useState<LiveRequest>(null);
  const [ageMs, setAgeMs] = useState<number | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [remote, setRemote] = useState<StreamSession | null>(null);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [remoteBusy, setRemoteBusy] = useState(false);

  const startedAt = useRef(0);
  const objectUrl = useRef<string | null>(null);

  /**
   * Просмотр через интернет.
   *
   * Отдельная кнопка, а не автоматика: поток наружу стоит канала фермы,
   * и включать его молча, когда локальный путь мог бы сработать, — значит
   * тратить чужой интернет без спроса.
   */
  const openRemote = useCallback(async () => {
    setRemoteBusy(true);
    setRemoteError(null);
    const result = await startRemoteStreamAction(snapshot.cameraId);
    setRemoteBusy(false);

    if ("error" in result) {
      setRemoteError(result.error);
      return;
    }
    setRemote(result.session);
  }, [snapshot.cameraId]);

  // Окно закрыли — гасим поток, не дожидаясь конца срока. Иначе ферма
  // ещё десять минут гнала бы видео в никуда
  useEffect(() => {
    if (!remote) return;
    return () => {
      void stopRemoteStreamAction(remote.id);
    };
  }, [remote]);

  const keepAlive = useCallback(async () => {
    const result = await requestLiveViewAction(snapshot.cameraId, 60);
    // Состояние запроса и состояние кадра держим врозь: раньше удачно
    // забранный кадр затирал сообщение о том, что живой режим не включился,
    // и картина выходила противоположной действительности
    setLiveRequest("error" in result ? { ok: false, message: result.error } : { ok: true });
  }, [snapshot.cameraId]);

  /**
   * Кадр забираем запросом, а не подставляем в адрес картинки: так браузер
   * не отдаст старую копию из кэша, а по заголовкам видно, присылает ли
   * ферма новые кадры вообще.
   */
  const fetchFrame = useCallback(async () => {
    if (!snapshot.liveUrl) return;

    try {
      // Адрес наш, поэтому запрет кэширования доходит целиком.
      // Метка всё равно нужна: браузер иначе может отдать свою копию.
      const response = await fetch(`${snapshot.liveUrl}?_=${Date.now()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        setFrameError(
          response.status === 400 || response.status === 403
            ? "Нет доступа к камере. Войдите заново"
            : `Кадр не получен: ${response.status}`
        );
        return;
      }

      setAgeMs(frameAgeMs(response.headers, Date.now()));

      const blob = await response.blob();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = URL.createObjectURL(blob);
      setFrameUrl(objectUrl.current);
      setFrameError(null);
    } catch (e) {
      setFrameError(e instanceof Error ? e.message : String(e));
    }
  }, [snapshot.liveUrl]);

  // Забытая вкладка закрывается сама в любом режиме: и ускоренная отдача
  // кадров, и кодирование потока на ферме стоят процессорного времени
  useEffect(() => {
    startedAt.current = Date.now();
    const idle = setInterval(() => {
      if (Date.now() - startedAt.current > IDLE_TIMEOUT_MS) onClose();
    }, KEEPALIVE_MS);
    return () => clearInterval(idle);
  }, [onClose]);

  useEffect(() => {
    // При живом видео просить ускоренную отдачу кадров незачем: браузер
    // держит поток сам, а ферма видит зрителя по открытому соединению
    if (snapshot.hasStream || remote) return;

    void keepAlive();
    void fetchFrame();

    const keep = setInterval(() => void keepAlive(), KEEPALIVE_MS);
    const frames = setInterval(() => void fetchFrame(), FRAME_MS);

    return () => {
      clearInterval(keep);
      clearInterval(frames);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, [keepAlive, fetchFrame, snapshot.hasStream, remote]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const state: LiveState = remote
    ? { kind: "live", line: "видео через интернет" }
    : snapshot.hasStream
      ? { kind: "live", line: "видео с устройства" }
      : liveState({ liveRequest, frameError, ageMs });

  const hint = state.hint ?? remoteError;

  // Техническая причина не попадает на экран фермера: он всё равно не
  // станет применять миграцию. Но тому, кто приедет чинить, она нужна,
  // поэтому уходит в консоль браузера
  useEffect(() => {
    if (state.consoleReason) console.warn(state.consoleReason);
  }, [state.consoleReason]);

  return (
    <div
      className="fixed inset-0 z-50 bg-brand/85 flex items-center justify-center p-2 sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-label={`Трансляция: ${snapshot.cameraName}`}
    >
      {/*
        Окно подгоняется под картинку, а не наоборот.
        Раньше половину высоты занимали заголовок и три абзаца пояснений,
        а само видео оставалось маленьким — ровно наоборот тому, зачем
        окно открывают. Теперь пояснения ужаты до строки, а кадр берёт
        всю доступную высоту.
      */}
      <div
        className="bg-surface rounded-xl overflow-hidden w-full max-w-5xl flex flex-col max-h-[95vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-2 border-b border-line-soft shrink-0">
          <span
            aria-hidden
            className={`inline-block w-2 h-2 rounded-full shrink-0 ${
              state.kind === "live"
                ? "bg-trouble animate-pulse"
                : state.kind === "problem"
                  ? "bg-watch"
                  : "bg-line"
            }`}
          />
          <span className="text-sm font-medium text-ink truncate">
            {snapshot.cameraName}
          </span>
          <span className="text-xs text-muted truncate">{state.line}</span>

          <div className="ml-auto flex items-center gap-2 shrink-0">
            {remoteAvailable && !remote && (
              <Button onClick={() => void openRemote()} disabled={remoteBusy}>
                {remoteBusy ? "Включаем…" : "Через интернет"}
              </Button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Закрыть"
              className="rounded-md w-7 h-7 text-faint hover:text-ink hover:bg-line-soft transition-colors text-lg leading-none"
            >
              ×
            </button>
          </div>
        </div>

        {/* min-h-0 обязателен: без него flex-элемент не даёт себя сжать,
            и окно вылезает за пределы экрана вместо того, чтобы отдать
            картинке ровно оставшуюся высоту */}
        <div className="bg-brand flex-1 min-h-0 flex items-center justify-center">
          {remote ? (
            <RemoteVideo path={remote.path} cameraName={snapshot.cameraName} />
          ) : snapshot.hasStream ? (
            // Настоящее видео: браузер сам держит соединение и рисует
            // кадры по мере поступления, опрашивать ничего не нужно.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={streamUrl(snapshot.cameraId)}
              alt={`Видео с камеры ${snapshot.cameraName}`}
              className="max-w-full max-h-[80vh] object-contain"
            />
          ) : frameUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={frameUrl}
              alt={`Трансляция с камеры ${snapshot.cameraName}`}
              className="max-w-full max-h-[80vh] object-contain"
            />
          ) : (
            <div className="aspect-video w-full flex items-center justify-center text-sm text-faint">
              {state.kind === "problem" ? "кадр недоступен" : "ожидание кадра…"}
            </div>
          )}
        </div>

        {/* Подсказка только когда есть что сказать. Постоянный абзац
            «как это работает» человек прочитает один раз, а место
            занимать будет всегда */}
        {hint && (
          <div className="px-4 py-2.5 text-sm text-muted bg-watch-bg/70 border-t border-watch/30 leading-snug shrink-0">
            {hint}
          </div>
        )}

        <div className="px-4 py-2 text-xs text-faint border-t border-line-soft shrink-0 leading-snug">
          {remote
            ? "Через интернет. Сеанс закроется через 10 минут."
            : snapshot.hasStream
              ? "Прямое подключение в сети фермы."
              : "Обновление кадрами, без видеопотока."}
        </div>
      </div>
    </div>
  );
}

export type LiveState = {
  kind: "connecting" | "live" | "problem";
  line: string;
  /** Что видит фермер. Коротко и про то, что может сделать он сам. */
  hint?: string;
  /** Что уходит в консоль браузера для того, кто чинит. Не показывается. */
  consoleReason?: string;
};

/**
 * Что показать пользователю. Вынесено отдельно, потому что здесь легче
 * всего соврать: удачно забранный кадр выглядит как работающий живой
 * просмотр, даже когда сама просьба о нём до фермы не дошла.
 */
export function liveState(input: {
  liveRequest: LiveRequest;
  frameError: string | null;
  ageMs: number | null;
}): LiveState {
  if (input.liveRequest && !input.liveRequest.ok) {
    return {
      kind: "problem",
      line: "учащённая передача не включена",
      // Фермеру незачем знать про миграцию 0010: он всё равно ничего с
      // ней не сделает. Причина уходит в consoleReason, оттуда её
      // достанет тот, кто чинит
      hint: "Кадры поступают в обычном режиме, раз в 15 секунд. Обратитесь в техническую поддержку.",
      consoleReason: `Ферма не приняла просьбу показывать чаще: ${input.liveRequest.message}. Похоже, не применена миграция 0010.`,
    };
  }

  if (input.frameError) {
    return { kind: "problem", line: input.frameError };
  }

  if (input.ageMs === null) {
    return { kind: "connecting", line: "включение учащённой передачи…" };
  }

  if (input.ageMs > LIVE_EXPECTED_MS) {
    return {
      kind: "problem",
      line: `${describeFrameAge(input.ageMs)}, обычный режим`,
      hint: "Учащённая передача не включилась. Если не восстановится, обратитесь в поддержку.",
      consoleReason:
        "Ферма отдаёт кадры раз в 15 секунд: в живой режим она не перешла. " +
        "Проверьте, перезапущена ли обработка на мини-ПК: в журнале должна " +
        "быть строка «включён живой просмотр».",
    };
  }

  return {
    kind: "live",
    line: `учащённая передача, ${describeFrameAge(input.ageMs)}`,
  };
}
