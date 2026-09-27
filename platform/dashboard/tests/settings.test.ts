import { describe, it, expect } from "vitest";
import {
  TIMEZONES,
  describeDays,
} from "../lib/settings";
import {
  DEFAULT_PLACEMENT,
  PLACEMENTS,
  PLACEMENT_INFO,
  isPlacement,
  measuresWeight,
  placementName,
} from "../lib/cameras";

describe("расположение камеры", () => {
  it("у каждого варианта есть и куда вешать, и что это даст", () => {
    for (const placement of PLACEMENTS) {
      const info = PLACEMENT_INFO[placement];
      expect(info.name.length).toBeGreaterThan(2);
      expect(info.where.length).toBeGreaterThan(10);
      expect(info.gives.length).toBeGreaterThan(10);
    }
  });

  it("силуэт снимается только с камеры над животными", () => {
    // Сбоку площадь проекции зависит от поворота животного
    // и с массой не связана
    expect(measuresWeight("overhead")).toBe(true);
    expect(measuresWeight("side")).toBe(false);
    expect(measuresWeight("wide")).toBe(false);
  });

  it("по умолчанию камера считается боковой", () => {
    // Ошибочный «сверху» породил бы обмеры, которым нельзя верить
    expect(DEFAULT_PLACEMENT).toBe("side");
    expect(measuresWeight(DEFAULT_PLACEMENT)).toBe(false);
  });

  it("мусор из базы не проходит за расположение", () => {
    expect(isPlacement("сверху")).toBe(false);
    expect(isPlacement(null)).toBe(false);
    expect(isPlacement("overhead")).toBe(true);
  });

  it("неизвестное значение показывается честно, а не подменяется", () => {
    expect(placementName("что-то")).toBe("не указано");
    expect(placementName("overhead")).toBe(PLACEMENT_INFO.overhead.name);
  });
});

describe("часовые пояса", () => {
  it("все предложенные пояса существуют", () => {
    for (const tz of TIMEZONES) {
      expect(() => new Intl.DateTimeFormat("ru-RU", { timeZone: tz.value })).not.toThrow();
    }
  });

  it("пояс фермы по умолчанию есть в списке", () => {
    expect(TIMEZONES.some((t) => t.value === "Asia/Almaty")).toBe(true);
  });
});

describe("describeDays", () => {
  it("недели и месяцы читаются словами", () => {
    expect(describeDays(7)).toBe("неделя");
    expect(describeDays(30)).toBe("месяц");
    expect(describeDays(90)).toBe("3 мес.");
  });

  it("длинные сроки округляются до лет", () => {
    expect(describeDays(400)).toBe("около года");
    expect(describeDays(730)).toBe("около 2 лет");
  });

  it("короткие сроки остаются днями", () => {
    expect(describeDays(3)).toBe("3 дн.");
  });
});
