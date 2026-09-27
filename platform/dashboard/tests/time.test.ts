import { describe, it, expect } from "vitest";
import {
  DEFAULT_TIMEZONE,
  formatDateTimeInZone,
  formatTimeInZone,
  hourInZone,
  safeTimeZone,
  zoneOffsetLabel,
} from "../lib/time";

describe("safeTimeZone", () => {
  it("подставляет пояс фермы, если ничего не задано", () => {
    expect(safeTimeZone(null)).toBe(DEFAULT_TIMEZONE);
    expect(safeTimeZone(undefined)).toBe(DEFAULT_TIMEZONE);
    expect(safeTimeZone("")).toBe(DEFAULT_TIMEZONE);
  });

  it("пропускает настоящий пояс", () => {
    expect(safeTimeZone("Europe/Moscow")).toBe("Europe/Moscow");
  });

  it("битое значение в базе не роняет страницу", () => {
    expect(safeTimeZone("Не/Пояс")).toBe(DEFAULT_TIMEZONE);
  });
});

describe("hourInZone", () => {
  it("считает час по времени фермы, а не сервера", () => {
    // 22:00 UTC — это уже три часа ночи следующего дня в Алматы
    expect(hourInZone("2026-08-09T22:00:00.000Z", "Asia/Almaty")).toBe(3);
  });

  it("разница с UTC ровно пять часов", () => {
    expect(hourInZone("2026-08-09T10:00:00.000Z", "Asia/Almaty")).toBe(15);
  });

  it("полночь остаётся нулём, а не двадцатью четырьмя", () => {
    expect(hourInZone("2026-08-09T19:00:00.000Z", "Asia/Almaty")).toBe(0);
  });

  it("битая дата не роняет расчёт", () => {
    expect(hourInZone("не дата")).toBeNull();
  });

  it("неизвестный пояс приводит к поясу по умолчанию", () => {
    expect(hourInZone("2026-08-09T10:00:00.000Z", "Марс/Олимп")).toBe(15);
  });
});

describe("formatTimeInZone", () => {
  it("показывает время фермы", () => {
    expect(formatTimeInZone("2026-08-09T10:30:15.000Z", "Asia/Almaty")).toContain("15:30");
  });

  it("битая дата даёт прочерк", () => {
    expect(formatTimeInZone("нет")).toBe("—");
  });
});

describe("formatDateTimeInZone", () => {
  it("дата сдвигается вместе со временем", () => {
    // 21:00 UTC девятого — это уже второй час десятого числа на ферме
    const result = formatDateTimeInZone("2026-08-09T21:00:00.000Z", "Asia/Almaty");
    expect(result).toContain("10.08.2026");
  });

  it("битая дата даёт прочерк", () => {
    expect(formatDateTimeInZone("нет")).toBe("—");
  });
});

describe("zoneOffsetLabel", () => {
  it("подписывает график, чтобы не было вопроса «по чьему времени»", () => {
    const now = new Date("2026-08-09T10:00:00.000Z");
    expect(zoneOffsetLabel("Asia/Almaty", now)).toBe("UTC+5");
  });

  it("для UTC не пишет нулевой сдвиг", () => {
    const now = new Date("2026-08-09T10:00:00.000Z");
    expect(zoneOffsetLabel("UTC", now)).toBe("UTC");
  });
});
