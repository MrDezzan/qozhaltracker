import { describe, expect, it, vi } from "vitest";
import {
  MIN_ANIMALS,
  MIN_CHECKS,
  checksRemaining,
  describeBias,
  formatKg,
  formatPercent,
  getWeightAccuracy,
  isTrustworthy,
  verdict,
  type WeightAccuracy,
} from "../lib/accuracy";

function accuracy(overrides: Partial<WeightAccuracy> = {}): WeightAccuracy {
  return {
    checked: 20,
    animals: 8,
    mae_kg: 18,
    mape_percent: 3.6,
    bias_percent: 0.4,
    worst_percent: 9.1,
    ...overrides,
  };
}

describe("хватает ли данных", () => {
  it("на трёх проверках цифре верить нельзя", () => {
    // На трёх взвешиваниях можно получить ошибку в 1 %, и она не будет
    // значить ничего. Назвать такую цифру клиенту хуже, чем промолчать
    expect(isTrustworthy(accuracy({ checked: 3 }))).toBe(false);
  });

  it("одного животного мало, сколько его ни взвешивай", () => {
    // Модель будет угадывать знакомое тело, а не работать по признакам
    expect(isTrustworthy(accuracy({ checked: 30, animals: 1 }))).toBe(false);
  });

  it("двадцати проверок по восьми животным достаточно", () => {
    expect(isTrustworthy(accuracy())).toBe(true);
  });

  it("пустого замера не бывает достаточно", () => {
    expect(isTrustworthy(null)).toBe(false);
  });

  it("считает, сколько ещё взвешиваний нужно", () => {
    expect(checksRemaining(accuracy({ checked: 3 }))).toBe(MIN_CHECKS - 3);
    expect(checksRemaining(accuracy())).toBe(0);
    expect(checksRemaining(null)).toBe(MIN_CHECKS);
  });

  it("пороги заданы осмысленно", () => {
    expect(MIN_CHECKS).toBeGreaterThan(MIN_ANIMALS);
  });
});

describe("что означает полученная ошибка", () => {
  it("до пяти процентов — виден привес отдельного животного", () => {
    // Месячная прибавка на откорме 30–45 кг, ошибка 5 % на корове
    // в 500 кг это 25 кг — тренд ещё различим
    const result = verdict(accuracy({ mape_percent: 3.6 }));
    expect(result.level).toBe("good");
    expect(result.headline).toContain("верить");
  });

  it("до десяти — только по стаду", () => {
    const result = verdict(accuracy({ mape_percent: 8.2 }));
    expect(result.level).toBe("usable");
    expect(result.detail).toContain("группе");
  });

  it("больше десяти — показывать нельзя", () => {
    const result = verdict(accuracy({ mape_percent: 14 }));
    expect(result.level).toBe("poor");
    expect(result.headline).toContain("нельзя");
  });

  it("мало данных — честное «неизвестно», а не ноль процентов", () => {
    const result = verdict(accuracy({ checked: 2, mape_percent: 0.8 }));
    expect(result.level).toBe("unknown");
    expect(result.headline).toContain("не знаем");
    // Соблазн показать 0,8 % велик, и это была бы ложь
    expect(result.detail).not.toContain("0,8");
  });

  it("граница ровно на пяти процентах считается хорошей", () => {
    expect(verdict(accuracy({ mape_percent: 5 })).level).toBe("good");
  });
});

describe("перекос отдельно от разброса", () => {
  it("систематическое завышение называется прямо", () => {
    // Перекос лечится одним коэффициентом, разброс требует другого
    // метода измерения. Прятать их в одну «среднюю ошибку» нельзя
    expect(describeBias(accuracy({ bias_percent: 6.2 }))).toContain("завышает");
  });

  it("систематическое занижение тоже", () => {
    expect(describeBias(accuracy({ bias_percent: -4.5 }))).toContain("занижает");
  });

  it("мелкий перекос молчит, а не сообщает о себе", () => {
    // «Перекоса нет» — это лишняя строка на экране: человеку нечего
    // с ней делать
    expect(describeBias(accuracy({ bias_percent: 0.3 }))).toBe("");
  });

  it("отсутствие данных ничего не выдумывает", () => {
    expect(describeBias(accuracy({ bias_percent: null }))).toBe("");
  });
});

describe("чтение из базы", () => {
  it("берёт точность своей фермы", async () => {
    const rpc = vi.fn().mockResolvedValue({ data: [accuracy()], error: null });
    const result = await getWeightAccuracy({ rpc } as never, "farm-1");

    expect(rpc).toHaveBeenCalledWith("weight_accuracy", { target_farm_id: "farm-1" });
    expect(result?.mape_percent).toBe(3.6);
  });

  it("нулевая проверка — это отсутствие данных, а не точность 0", async () => {
    const rpc = vi
      .fn()
      .mockResolvedValue({ data: [accuracy({ checked: 0 })], error: null });
    expect(await getWeightAccuracy({ rpc } as never, "farm-1")).toBeNull();
  });

  it("ошибка базы не роняет страницу", async () => {
    const rpc = vi.fn().mockResolvedValue({ data: null, error: { message: "нет" } });
    expect(await getWeightAccuracy({ rpc } as never, "farm-1")).toBeNull();
  });
});

describe("вывод чисел", () => {
  it("проценты с одним знаком", () => {
    expect(formatPercent(3.64)).toBe("3.6 %");
  });

  it("килограммы с одним знаком", () => {
    expect(formatKg(18.42)).toBe("18.4 кг");
  });

  it("пустое значение не превращается в ноль", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatKg(undefined)).toBe("—");
  });
});
