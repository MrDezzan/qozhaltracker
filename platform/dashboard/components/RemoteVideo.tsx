"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { hlsUrl, whepUrl } from "../lib/remoteStream";

type Props = {
  path: string;
  cameraName: string;
  onFailure?: (message: string) => void;
};

type Mode = "connecting" | "webrtc" | "hls" | "failed";

/**
 * Живое видео через сервер ретрансляции.
 *
 * Основной путь — WebRTC: задержка меньше секунды и никаких библиотек,
 * браузер умеет это сам. Подключаемся по WHEP — это стандартный обмен
 * описаниями соединения одним HTTP-запросом.
 *
 * Запасной путь — LL-HLS. Нужен потому, что WebRTC идёт по UDP, а в части
 * корпоративных и мобильных сетей UDP закрыт наглухо: там основной путь
 * не заработает никогда, сколько ни пробуй. HLS идёт по обычному HTTPS,
 * задержка 2-4 секунды вместо секунды.
 */
export function RemoteVideo({ path, cameraName, onFailure }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [mode, setMode] = useState<Mode>("connecting");
  const [message, setMessage] = useState<string | null>(null);

  const fallbackToHls = useCallback(
    (reason: string) => {
      const video = videoRef.current;
      if (!video) return;

      // Родная поддержка есть у Safari и на iOS — а это как раз телефон,
      // с которого чаще всего и смотрят. В Chrome на Android её нет:
      // там нужна отдельная библиотека, и пока честнее сказать прямо.
      const canPlayHls =
        video.canPlayType("application/vnd.apple.mpegurl") !== "";

      if (!canPlayHls) {
        setMode("failed");
        setMessage(
          `Видео не пошло: ${reason}. Похоже, сеть не пропускает видео. ` +
            "попробуйте с мобильного интернета вместо рабочего Wi-Fi."
        );
        onFailure?.(reason);
        return;
      }

      video.src = hlsUrl(path);
      setMode("hls");
      setMessage(null);
      void video.play().catch(() => undefined);
    },
    [path, onFailure]
  );

  useEffect(() => {
    let cancelled = false;
    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });
    pcRef.current = pc;

    // Только принимаем. Без этой строки браузер не попросит видео вовсе
    // и соединение установится пустым
    pc.addTransceiver("video", { direction: "recvonly" });

    pc.ontrack = (event) => {
      const video = videoRef.current;
      if (!video || cancelled) return;
      video.srcObject = event.streams[0];
      setMode("webrtc");
      setMessage(null);
      void video.play().catch(() => undefined);
    };

    pc.onconnectionstatechange = () => {
      if (cancelled) return;
      if (pc.connectionState === "failed") {
        fallbackToHls("соединение не установилось");
      }
    };

    async function connect() {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Ждём, пока браузер соберёт все варианты подключения, и шлём одним
      // куском. Досылать их по одному сложнее, а выигрыш — доли секунды
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === "complete") return resolve();
        const done = setTimeout(resolve, 3000);
        pc.onicegatheringstatechange = () => {
          if (pc.iceGatheringState === "complete") {
            clearTimeout(done);
            resolve();
          }
        };
      });

      const response = await fetch(whepUrl(path), {
        method: "POST",
        headers: { "Content-Type": "application/sdp" },
        body: pc.localDescription?.sdp ?? "",
      });

      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "просмотр больше не разрешён"
            : `сервер видео ответил ${response.status}`
        );
      }

      const answer = await response.text();
      if (cancelled) return;
      await pc.setRemoteDescription({ type: "answer", sdp: answer });
    }

    connect().catch((e: unknown) => {
      if (cancelled) return;
      fallbackToHls(e instanceof Error ? e.message : String(e));
    });

    return () => {
      cancelled = true;
      // Закрываем соединение явно: иначе сервер ретрансляции продолжает
      // считать нас зрителем, а ферма — гнать поток
      pc.close();
      pcRef.current = null;
    };
  }, [path, fallbackToHls]);

  return (
    <div className="w-full h-full relative">
      <video
        ref={videoRef}
        className="w-full h-full object-contain"
        playsInline
        muted
        autoPlay
        aria-label={`Видео с камеры ${cameraName}`}
      />
      {mode === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-faint">
          подключаемся к камере…
        </div>
      )}
      {mode === "failed" && message && (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-faint leading-relaxed">
          {message}
        </div>
      )}
      {mode === "hls" && (
        <div className="absolute bottom-2 right-2 rounded bg-brand/70 px-2 py-1 text-[11px] text-faint">
          запасной канал, задержка несколько секунд
        </div>
      )}
    </div>
  );
}
