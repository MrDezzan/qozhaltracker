import { describe, expect, it } from "vitest";
import {
  ActivityRow,
  HIGH_RATIO,
  LOW_RATIO,
  MIN_DAYS_FOR_BASELINE,
  MIN_SECONDS_VISIBLE,
  activityVerdict,
  describeVisits,
  formatMeters,
} from "../lib/activity";

function row(over: Partial<ActivityRow> = {}): ActivityRow {
  return {
    animal_id: "a1",
    label: "Зорька",
    day: "2026-08-19",
    meters: 800,
    seconds_visible: 3600,
    baseline_meters: 800,
    ratio_to_own: 1,
    ratio_to_herd: 1,
    days_known: 10,
    ...over,
  };
}

describe("оценка активности", () => {
  it("без данных не выдумывает вывод", () => {
    const verdict = activityVerdict(undefined);
    expect(verdict.level).toBe("unknown");
    expect(verdict.detail).toContain("масштаб");
  });

  it("без накопленной нормы молчит", () => {
    // По двум дням «норма» — это просто один из них, и любое
    // отклонение от неё случайно
    const verdict = activityVerdict(row({ days_known: MIN_DAYS_FOR_BASELINE - 1 }));
    expect(verdict.level).toBe("unknown");
    expect(verdict.headline).toContain("присматриваемся");
  });

  it("малое время в кадре не считает малоподвижностью", () => {
    // Иначе животное, зашедшее в кадр на минуту, каждый раз выглядело
    // бы больным
    const verdict = activityVerdict(
      row({ seconds_visible: MIN_SECONDS_VISIBLE - 1, meters: 20, ratio_to_own: 0.1 })
    );
    expect(verdict.level).toBe("unknown");
    expect(verdict.headline).toContain("не было видно");
  });

  it("обычный разброс не помечает", () => {
    // День на день не приходится. Помечать каждое отклонение на 15 %
    // значит приучить человека не смотреть на пометки вовсе
    expect(activityVerdict(row({ ratio_to_own: 0.85 })).level).toBe("normal");
    expect(activityVerdict(row({ ratio_to_own: 1.2 })).level).toBe("normal");
  });

  it("просадку относит к животному, когда стадо в норме", () => {
    const verdict = activityVerdict(
      row({ ratio_to_own: LOW_RATIO - 0.1, ratio_to_herd: 0.95 })
    );
    expect(verdict.level).toBe("low");
    expect(verdict.detail).toContain("дело в нём");
  });

  it("общую просадку стада не выдаёт за болезнь", () => {
    // Жара или перегон роняют активность у всех. Тревожиться о каждом
    // животном по очереди в такой день — прямой путь к недоверию
    const verdict = activityVerdict(
      row({ ratio_to_own: LOW_RATIO - 0.1, ratio_to_herd: 0.5 })
    );
    expect(verdict.level).toBe("low");
    expect(verdict.detail).toContain("меньше ходят все");
  });

  it("всплеск объясняет охотой, а не болезнью", () => {
    const verdict = activityVerdict(row({ ratio_to_own: HIGH_RATIO + 0.1 }));
    expect(verdict.level).toBe("high");
    expect(verdict.detail).toMatch(/охот/i);
  });

  it("в норме показывает, с чем сравнивали", () => {
    const verdict = activityVerdict(row({ baseline_meters: 640 }));
    expect(verdict.detail).toContain("640");
  });
});

describe("метры", () => {
  it("короткое — в метрах", () => {
    expect(formatMeters(840)).toBe("840 м");
  });

  it("длинное — в километрах", () => {
    expect(formatMeters(1500)).toBe("1.5 км");
  });

  it("пусто — прочерк, а не ноль", () => {
    // Ноль означал бы «не двигалась», а это другое утверждение
    expect(formatMeters(null)).toBe("—");
    expect(formatMeters(undefined)).toBe("—");
  });
});

describe("подходы к зонам", () => {
  it("пусто описывается словами", () => {
    expect(describeVisits(undefined)).toContain("не было");
    expect(describeVisits([])).toContain("не было");
  });

  it("перечисляет корм и воду", () => {
    // zone_kind берётся из ограничения миграции 0004: feeder, water,
    // gate, other. Здесь стояло "waterer" — то же неверное значение,
    // что и в коде, поэтому тест проходил, а поилка на экране не
    // показывалась никогда
    const text = describeVisits([
      { animal_id: "a1", zone_kind: "feeder", visits: 6, seconds: 1800 },
      { animal_id: "a1", zone_kind: "water", visits: 4, seconds: 300 },
    ]);
    expect(text).toContain("кормушка: 6 раз, 30 мин");
    expect(text).toContain("поилка: 4 раз, 5 мин");
  });

  it("проход и периметр в еду не считает", () => {
    const text = describeVisits([
      { animal_id: "a1", zone_kind: "passage", visits: 9, seconds: 60 },
    ]);
    expect(text).toBe("");
  });
});
