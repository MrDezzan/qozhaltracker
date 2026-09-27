"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getBrowserSupabase } from "../lib/supabaseBrowser";
import { alertName } from "../lib/alerts";

/**
 * Держит страницу в актуальном состоянии без перезагрузки.
 *
 * Раньше данные обновлялись раз в тридцать секунд по таймеру. Для тревоги
 * это много: если у животного подскочила температура, узнать об этом надо
 * тогда же, а не через полминуты. Поэтому подписываемся на изменения в базе
 * и обновляем страницу по факту события.
 *
 * Таймер оставлен запасным вариантом: соединение может не подняться из-за
 * прокси или корпоративной сети, и лучше медленно, чем никак.
 */

const FALLBACK_REFRESH_MS = 60_000;

type Props = {
  farmId: string;
  /** Показывать ли всплывающие уведомления браузера о новых тревогах. */
  notify?: boolean;
};

export function RealtimeSync({ farmId, notify = true }: Props) {
  const router = useRouter();
  const [connected, setConnected] = useState(false);
  // Обновление страницы стоит запроса к серверу. Если событий приходит
  // много подряд, сваливаем их в одно обновление.
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const supabase = getBrowserSupabase();

    const refreshSoon = () => {
      if (pending.current) clearTimeout(pending.current);
      pending.current = setTimeout(() => router.refresh(), 400);
    };

    const showNotification = (row: Record<string, unknown>) => {
      if (!notify) return;
      if (typeof window === "undefined" || !("Notification" in window)) return;
      if (Notification.permission !== "granted") return;

      const severity = String(row["severity"] ?? "");
      const kind = String(row["kind"] ?? "");
      const title = String(row["title"] ?? "");
      new Notification(alertName(kind), {
        body: title,
        tag: String(row["id"] ?? kind),
        requireInteraction: severity === "danger",
      });
    };

    const channel = supabase
      .channel(`farm-${farmId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "alerts",
          filter: `farm_id=eq.${farmId}`,
        },
        (payload) => {
          showNotification(payload.new as Record<string, unknown>);
          refreshSoon();
        }
      )
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "alerts",
          filter: `farm_id=eq.${farmId}`,
        },
        refreshSoon
      )
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "events",
          filter: `farm_id=eq.${farmId}`,
        },
        refreshSoon
      )
      .subscribe((status) => setConnected(status === "SUBSCRIBED"));

    return () => {
      if (pending.current) clearTimeout(pending.current);
      void supabase.removeChannel(channel);
    };
  }, [farmId, notify, router]);

  // Запасной таймер работает, только пока живая подписка не поднялась
  useEffect(() => {
    if (connected) return;
    const timer = setInterval(() => router.refresh(), FALLBACK_REFRESH_MS);
    return () => clearInterval(timer);
  }, [connected, router]);

  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span
        aria-hidden
        className={`inline-block w-1.5 h-1.5 rounded-full ${
          connected ? "bg-calm" : "bg-line"
        }`}
      />
      {connected ? "обновление в реальном времени" : "обновление раз в минуту"}
      {notify && <NotificationOptIn />}
    </div>
  );
}

/**
 * Разрешение на уведомления браузер даёт только по клику пользователя.
 * Просить его сразу при загрузке — верный способ получить отказ навсегда.
 */
function NotificationOptIn() {
  const [state, setState] = useState<NotificationPermission | "unsupported">("default");

  useEffect(() => {
    if (typeof window === "undefined" || !("Notification" in window)) {
      setState("unsupported");
      return;
    }
    setState(Notification.permission);
  }, []);

  if (state !== "default") return null;

  return (
    <button
      type="button"
      onClick={() => void Notification.requestPermission().then(setState)}
      className="underline underline-offset-2 hover:text-ink"
    >
      Включить оповещения
    </button>
  );
}
