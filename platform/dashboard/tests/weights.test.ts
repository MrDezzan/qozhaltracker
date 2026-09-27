import { describe, it, expect } from "vitest";
import {
  MIN_WEIGHINGS,
  WeightModel,
  describeAccuracy,
  formatGain,
  formatWeight,
  weighingsRemaining,
} from "../lib/weights";

function model(overrides: Partial<WeightModel> = {}): WeightModel {
  return {
    coefficient_a: 0.004,
    exponent_b: 1.5,
    sample_count: 24,
    mae_kg: 18,
    mape_percent: 4.5,
    r_squared: 0.91,
    fitted_at: "2026-08-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("weighingsRemaining", () => {
  it("показывает, сколько ещё нужно взвесить", () => {
    expect(weighingsRemaining(0)).toBe(MIN_WEIGHINGS);
    expect(weighingsRemaining(4)).toBe(MIN_WEIGHINGS - 4);
  });

  it("не уходит в минус, когда взвешиваний уже больше нужного", () => {
    expect(weighingsRemaining(MIN_WEIGHINGS + 5)).toBe(0);
  });
});

describe("describeAccuracy", () => {
  it("без формулы вес показывать нельзя", () => {
    const result = describeAccuracy(null);
    expect(result.trustworthy).toBe(false);
    expect(result.text).toContain("не подобрана");
  });

  it("называет ошибку прямо, а не прячет её", () => {
    expect(describeAccuracy(model()).text).toContain("4.5%");
  });

  it("хорошая формула считается пригодной", () => {
    expect(describeAccuracy(model({ mape_percent: 5 })).trustworthy).toBe(true);
  });

  it("большая ошибка снимает доверие", () => {
    expect(describeAccuracy(model({ mape_percent: 25 })).trustworthy).toBe(false);
  });

  it("неправдоподобная зависимость помечается, даже если ошибка красивая", () => {
    // Показатель степени должен быть около 1.5: площадь растёт как квадрат
    // линейного размера, масса — как куб. Ноль означает, что площадь
    // вообще не связана с весом, а формула подогнана под шум.
    const result = describeAccuracy(model({ exponent_b: 0.1, mape_percent: 2 }));
    expect(result.trustworthy).toBe(false);
    expect(result.text).toContain("неправдоподобно");
  });

  it("без посчитанной ошибки просто сообщает объём выборки", () => {
    const result = describeAccuracy(model({ mape_percent: null }));
    expect(result.text).toContain("24");
  });
});

describe("formatWeight", () => {
  it("округляет до килограмма — доли грамма тут не значат ничего", () => {
    expect(formatWeight(412.63)).toBe("413 кг");
  });

  it("нет оценки — прочерк, а не ноль", () => {
    expect(formatWeight(null)).toBe("—");
    expect(formatWeight(NaN)).toBe("—");
  });
});

describe("formatGain", () => {
  it("привес показывается со знаком", () => {
    expect(formatGain(1.24)).toBe("+1.24 кг/сут");
  });

  it("потеря веса тоже видна", () => {
    expect(formatGain(-0.4)).toBe("-0.40 кг/сут");
  });

  it("нет данных — прочерк", () => {
    expect(formatGain(null)).toBe("—");
  });
});

describe("привес подписывается один раз", () => {
  it("formatGain уже содержит «кг/сут»", () => {
    // В списке животных к этой строке дописывали ещё одно «/сут», и в
    // таблице стояло «+0.70 кг/сут/сут». На экране это выглядит как
    // ошибка расчёта, а не как опечатка в подписи
    expect(formatGain(0.7)).toBe("+0.70 кг/сут");
    expect(formatGain(0.7).endsWith("/сут")).toBe(true);
    expect(formatGain(null)).toBe("—");
  });
});
