import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import {
  hlsUrl,
  isEndingSoon,
  pathFromRelayRequest,
  relayPublicUrl,
  remoteStreamEnabled,
  secondsLeft,
  startRemoteStream,
  stopRemoteStream,
  whepUrl,
  type StreamSession,
} from "../lib/remoteStream";

const ORIGINAL = process.env.NEXT_PUBLIC_RELAY_URL;

afterEach(() => {
  process.env.NEXT_PUBLIC_RELAY_URL = ORIGINAL;
});

describe("адрес сервера ретрансляции", () => {
  it("выключен, когда не задан", () => {
    delete process.env.NEXT_PUBLIC_RELAY_URL;
    expect(remoteStreamEnabled()).toBe(false);
  });

  it("отбрасывает завершающий слэш", () => {
    // Иначе адреса собирались бы с двойным слэшем и не открывались
    process.env.NEXT_PUBLIC_RELAY_URL = "https://video.example.kz/";
    expect(relayPublicUrl()).toBe("https://video.example.kz");
  });

  it("собирает адреса просмотра", () => {
    process.env.NEXT_PUBLIC_RELAY_URL = "https://video.example.kz";
    expect(whepUrl("abc")).toBe("https://video.example.kz/abc/whep");
    expect(hlsUrl("abc")).toBe("https://video.example.kz/abc/index.m3u8");
  });
});

describe("разбор пути из запроса сервера ретрансляции", () => {
  const good = "0123456789abcdef0123456789abcdef";

  it("вынимает путь из адреса публикации", () => {
    expect(pathFromRelayRequest(`/${good}/whip`)).toBe(good);
  });

  it("вынимает путь из адреса просмотра", () => {
    expect(pathFromRelayRequest(`/${good}/whep`)).toBe(good);
  });

  it("вынимает путь из запроса плейлиста", () => {
    expect(pathFromRelayRequest(`/${good}/index.m3u8`)).toBe(good);
  });

  it("не спотыкается о параметры запроса", () => {
    expect(pathFromRelayRequest(`/${good}/whep?x=1`)).toBe(good);
  });

  it("понимает путь без хвоста", () => {
    expect(pathFromRelayRequest(`/${good}`)).toBe(good);
  });

  it("отвергает всё, что не похоже на выданный путь", () => {
    // Пути выдаёт база: 32 шестнадцатеричных знака. Проверка формата
    // отсекает и опечатки, и попытки подставить своё
    expect(pathFromRelayRequest("/../../etc/passwd")).toBeNull();
    expect(pathFromRelayRequest("/admin/whep")).toBeNull();
    expect(pathFromRelayRequest("")).toBeNull();
    expect(pathFromRelayRequest("/")).toBeNull();
    expect(pathFromRelayRequest(`/${good.toUpperCase()}/whep`)).toBeNull();
    expect(pathFromRelayRequest(`/${good.slice(0, 31)}/whep`)).toBeNull();
  });
});

describe("сессия просмотра", () => {
  function session(expiresAt: string): StreamSession {
    return { id: "s1", cameraId: "cam-1", path: "abc", expiresAt };
  }

  const now = new Date("2026-08-13T12:00:00Z");

  it("считает остаток", () => {
    expect(secondsLeft(session("2026-08-13T12:05:00Z"), now)).toBe(300);
  });

  it("истёкшая даёт ноль, а не отрицательное", () => {
    expect(secondsLeft(session("2026-08-13T11:00:00Z"), now)).toBe(0);
  });

  it("предупреждает за минуту до конца", () => {
    // Погасшее без предупреждения видео читается как поломка,
    // предупреждённое — как правило работы
    expect(isEndingSoon(session("2026-08-13T12:00:30Z"), now)).toBe(true);
    expect(isEndingSoon(session("2026-08-13T12:05:00Z"), now)).toBe(false);
  });

  it("уже погасшая не считается заканчивающейся", () => {
    expect(isEndingSoon(session("2026-08-13T11:00:00Z"), now)).toBe(false);
  });
});

describe("открытие и закрытие", () => {
  it("просит открыть сессию на камеру", async () => {
    const rpc = vi.fn().mockResolvedValue({
      data: {
        id: "s1",
        camera_id: "cam-1",
        path: "abc",
        expires_at: "2026-08-13T12:10:00Z",
      },
      error: null,
    });

    const result = await startRemoteStream({ rpc } as never, "cam-1", 600);

    expect(rpc).toHaveBeenCalledWith("start_remote_stream", {
      target_camera_id: "cam-1",
      seconds: 600,
    });
    expect(result?.path).toBe("abc");
  });

  it("понимает ответ списком", async () => {
    // Postgres-функция, возвращающая строку таблицы, приходит массивом
    const rpc = vi.fn().mockResolvedValue({
      data: [
        {
          id: "s1",
          camera_id: "cam-1",
          path: "abc",
          expires_at: "2026-08-13T12:10:00Z",
        },
      ],
      error: null,
    });

    const result = await startRemoteStream({ rpc } as never, "cam-1");
    expect(result?.id).toBe("s1");
  });

  it("отказ базы не роняет интерфейс", async () => {
    const rpc = vi.fn().mockResolvedValue({ data: null, error: { message: "нет" } });
    expect(await startRemoteStream({ rpc } as never, "cam-1")).toBeNull();
  });

  it("закрывает сессию по идентификатору", async () => {
    const rpc = vi.fn().mockResolvedValue({ data: null, error: null });
    await stopRemoteStream({ rpc } as never, "s1");
    expect(rpc).toHaveBeenCalledWith("stop_remote_stream", { target_session_id: "s1" });
  });
});
