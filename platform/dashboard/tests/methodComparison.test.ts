import { describe, expect, it } from "vitest";
import {
  MEANINGFUL_GAP,
  MethodAccuracy,
  compareMethods,
} from "../lib/accuracy";

function row(over: Partial<MethodAccuracy> & { method: MethodAccuracy["method"] }): MethodAccuracy {
  return {
    checked: 20,
    animals: 10,
    mape_percent: 8,
    bias_percent: 0,
    worst_percent: 15,
    ...over,
  };
}

describe("сравнение способов оценки веса", () => {
  it("без данных не выбирает победителя", () => {
    const result = compareMethods([]);
    expect(result.winner).toBeNull();
    expect(result.headline).toContain("не на чем");
  });

  it("не считает победой заметно меньшую ошибку на трёх взвешиваниях", () => {
    // Ошибка 1 % на четырёх проверках — случайность, а не достижение.
    // Объявить её победой значит переключить формулу на шуме
    const result = compareMethods([
      row({ method: "dimensions", checked: 4, animals: 2, mape_percent: 1 }),
      row({ method: "area", mape_percent: 9 }),
    ]);
    expect(result.winner).toBe("area");
  });

  it("называет способ точнее, когда разница осмысленная", () => {
    const result = compareMethods([
      row({ method: "area", mape_percent: 9 }),
      row({ method: "dimensions", mape_percent: 5 }),
    ]);
    expect(result.winner).toBe("dimensions");
    expect(result.detail).toContain("5.0 %");
    expect(result.detail).toContain("9.0 %");
  });

  it("при разнице в доли процента оставляет всё как есть", () => {
    const result = compareMethods([
      row({ method: "area", mape_percent: 7.0 }),
      row({ method: "dimensions", mape_percent: 7.0 + MEANINGFUL_GAP / 2 }),
    ]);
    expect(result.winner).toBeNull();
    expect(result.headline).toContain("одинаково");
  });

  it("объясняет, почему второго способа нет", () => {
    const result = compareMethods([row({ method: "area", mape_percent: 7 })]);
    expect(result.winner).toBe("area");
    expect(result.detail).toContain("не откалибрована");
  });

  it("порядок строк на итог не влияет", () => {
    const a = row({ method: "area", mape_percent: 9 });
    const d = row({ method: "dimensions", mape_percent: 5 });
    expect(compareMethods([a, d]).winner).toBe(compareMethods([d, a]).winner);
  });
});
