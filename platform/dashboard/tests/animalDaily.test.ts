import { describe, it, expect, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  averageMeals,
  describeGrowth,
  describeMeals,
  getAnimalDaily,
  getWeekChange,
  missedFeedingStreak,
  type AnimalDay,
  type WeekChange,
} from "../lib/animalDaily";
import { ZONE_KIND_LABEL } from "../lib/activity";

function rpc(data: unknown, error: unknown = null) {
  return { rpc: vi.fn().mockResolvedValue({ data, error }) } as unknown as SupabaseClient;
}

function day(over: Partial<AnimalDay> = {}): AnimalDay {
  return {
    day: "2026-08-20", meters: 500, seconds_visible: 3600,
    feeder_seconds: 600, feeder_visits: 4, water_visits: 3,
    area_px: 10000, length_cm: null, width_cm: null, measurements: 5,
    ...over,
  };
}

function change(over: Partial<WeekChange> = {}): WeekChange {
  return {
    feeder_visits_now: 4, feeder_visits_before: 4,
    feeder_seconds_now: 600, feeder_seconds_before: 600,
    meters_now: 500, meters_before: 500,
    area_now: 10000, area_before: 10000,
    area_change_pct: 0, days_with_size: 7,
    ...over,
  };
}

describe("виды зон", () => {
  it("поилка называется water, как в базе", () => {
    // Ограничение в миграции 0004: feeder, water, gate, other.
    // Здесь стояло "waterer" — значения, которого не бывает, — и поилка
    // молча выпадала из строки подходов
    expect(ZONE_KIND_LABEL.water).toBe("Поилка");
    expect(ZONE_KIND_LABEL.waterer).toBeUndefined();
  });
});

describe("пропуски кормления", () => {
  it("считает подряд с конца", () => {
    const rows = [day(), day({ feeder_visits: 0 }), day({ feeder_visits: 0 })];
    expect(missedFeedingStreak(rows)).toBe(2);
  });

  it("вчерашний порядок обнуляет счёт", () => {
    // Три пропуска неделю назад и порядок со вчера — это выздоровление,
    // а не тревога
    const rows = [day({ feeder_visits: 0 }), day({ feeder_visits: 0 }), day()];
    expect(missedFeedingStreak(rows)).toBe(0);
  });

  it("пустая история — ноль", () => {
    expect(missedFeedingStreak([])).toBe(0);
  });

  it("все дни без подходов", () => {
    expect(missedFeedingStreak([day({ feeder_visits: 0 }), day({ feeder_visits: 0 })])).toBe(2);
  });
});

describe("среднее число подходов", () => {
  it("считает", () => {
    expect(averageMeals([day({ feeder_visits: 2 }), day({ feeder_visits: 4 })])).toBe(3);
  });

  it("нет данных — null, а не ноль", () => {
    // Ноль означал бы «не подходил», а это другое утверждение
    expect(averageMeals([])).toBeNull();
  });
});

describe("рост словами", () => {
  it("называет процент и направление", () => {
    expect(describeGrowth(change({ area_change_pct: 8 }))).toContain("+8%");
    expect(describeGrowth(change({ area_change_pct: 8 }))).toContain("больше");
  });

  it("уменьшение тоже называет", () => {
    expect(describeGrowth(change({ area_change_pct: -5 }))).toContain("меньше");
  });

  it("рябь меньше процента ростом не называет", () => {
    // Силуэт колеблется от позы. Называть полупроцентную рябь ростом
    // значит приучить человека не верить этой строке
    expect(describeGrowth(change({ area_change_pct: 0 }))).toContain("без изменений");
  });

  it("не измеряли — так и говорит", () => {
    expect(describeGrowth(change({ area_change_pct: null, days_with_size: 0 })))
      .toContain("не измеряли");
  });

  it("измеряли, но сравнить не с чем", () => {
    expect(describeGrowth(change({ area_change_pct: null, days_with_size: 3 })))
      .toContain("Мало замеров");
  });

  it("совсем нет данных", () => {
    expect(describeGrowth(null)).toContain("Данных пока нет");
  });
});

describe("подходы словами", () => {
  it("называет текущее число", () => {
    expect(describeMeals(change({ feeder_visits_now: 4.2 }))).toContain("4.2");
  });

  it("падение отмечает отдельно", () => {
    const text = describeMeals(change({ feeder_visits_now: 1, feeder_visits_before: 5 }));
    expect(text).toContain("реже");
  });

  it("мелкое колебание падением не считает", () => {
    const text = describeMeals(change({ feeder_visits_now: 4.1, feeder_visits_before: 4 }));
    expect(text).toContain("как и раньше");
  });

  it("без прошлой недели просто число", () => {
    const text = describeMeals(change({ feeder_visits_now: 3, feeder_visits_before: null }));
    expect(text).toContain("3.0");
    expect(text).not.toContain("было");
  });
});

describe("чтение из базы", () => {
  it("зовёт функцию с животным и сроком", async () => {
    const client = rpc([]);
    await getAnimalDaily(client, "a1", 14);
    expect(client.rpc).toHaveBeenCalledWith("animal_daily", {
      target_animal_id: "a1", days: 14,
    });
  });

  it("ошибка не роняет страницу", async () => {
    // Страница животного не должна падать из-за непринятой миграции:
    // остальные её разделы к этой функции отношения не имеют
    await expect(getAnimalDaily(rpc(null, { message: "нет функции" }), "a1"))
      .resolves.toEqual([]);
    await expect(getWeekChange(rpc(null, { message: "нет функции" }), "a1"))
      .resolves.toBeNull();
  });

  it("пустой ответ на сравнение недель — null", async () => {
    await expect(getWeekChange(rpc([]), "a1")).resolves.toBeNull();
  });
});
