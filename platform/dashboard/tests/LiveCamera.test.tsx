import { describe, it, expect } from "vitest";
import { describeFrameAge, frameAgeMs, liveState } from "../components/LiveCamera";

describe("describeFrameAge", () => {
  it("свежий кадр так и назван", () => {
    expect(describeFrameAge(500)).toBe("кадр только что");
  });

  it("секунды показываются как есть", () => {
    expect(describeFrameAge(12_000)).toBe("кадр 12 с назад");
  });

  it("долгое молчание переводится в минуты", () => {
    expect(describeFrameAge(180_000)).toBe("кадр 3 мин назад");
  });

  it("без заголовка времени ничего не выдумываем", () => {
    expect(describeFrameAge(null)).toBe("");
  });

  it("отрицательного возраста не показываем", () => {
    expect(describeFrameAge(-4000)).toBe("кадр только что");
  });
});

describe("frameAgeMs", () => {
  function headers(values: Record<string, string>): Headers {
    return new Headers(values);
  }

  it("возраст считается от времени сервера, а не от часов браузера", () => {
    // Часы браузера убежали на сутки вперёд — кадр всё равно свежий
    const h = headers({
      "last-modified": "Tue, 11 Aug 2026 10:00:00 GMT",
      date: "Tue, 11 Aug 2026 10:00:04 GMT",
    });
    expect(frameAgeMs(h, new Date("2026-08-12T10:00:00Z").getTime())).toBe(4000);
  });

  it("без заголовка времени сервера берутся часы браузера", () => {
    const h = headers({ "last-modified": "Tue, 11 Aug 2026 10:00:00 GMT" });
    const now = new Date("2026-08-11T10:00:10Z").getTime();
    expect(frameAgeMs(h, now)).toBe(10_000);
  });

  it("без времени изменения возраст неизвестен", () => {
    expect(frameAgeMs(headers({}), Date.now())).toBeNull();
  });

  it("битый заголовок не выдаётся за возраст", () => {
    // Заголовки допускают только однобайтовые символы, поэтому мусор латиницей
    expect(frameAgeMs(headers({ "last-modified": "recently" }), Date.now())).toBeNull();
  });
});

describe("liveState", () => {
  const ok = { ok: true } as const;

  it("отказ фермы не затирается удачно забранным кадром", () => {
    // Именно так живой просмотр и выглядел работающим, когда на деле
    // просьба показывать чаще до фермы не доходила
    const state = liveState({
      liveRequest: { ok: false, message: "Камера не найдена" },
      frameError: null,
      ageMs: 800,
    });
    expect(state.kind).toBe("problem");
    expect(state.consoleReason).toContain("0010");
    // Фермеру про миграцию не пишем
    expect(state.hint).not.toContain("0010");
  });

  it("кадр старше нескольких секунд означает обычный режим", () => {
    const state = liveState({ liveRequest: ok, frameError: null, ageMs: 11_000 });
    expect(state.kind).toBe("problem");
    expect(state.line).toContain("обычный режим");
    expect(state.consoleReason).toContain("перезапущена");
  });

  it("свежий кадр при принятой просьбе — это работающий просмотр", () => {
    const state = liveState({ liveRequest: ok, frameError: null, ageMs: 1200 });
    expect(state.kind).toBe("live");
    expect(state.hint).toBeUndefined();
  });

  it("пока кадра не было, состояние промежуточное", () => {
    const state = liveState({ liveRequest: ok, frameError: null, ageMs: null });
    expect(state.kind).toBe("connecting");
  });

  it("ошибка загрузки кадра показывается как есть", () => {
    const state = liveState({
      liveRequest: ok,
      frameError: "Ссылка на кадр устарела",
      ageMs: 500,
    });
    expect(state.kind).toBe("problem");
    expect(state.line).toBe("Ссылка на кадр устарела");
  });

  it("отказ фермы важнее ошибки кадра: чинить надо его", () => {
    const state = liveState({
      liveRequest: { ok: false, message: "нет прав" },
      frameError: "что-то ещё",
      ageMs: null,
    });
    expect(state.line).toBe("учащённая передача не включена");
  });
});
