import { describe, expect, it } from "vitest";
import {
  MAX_SCALE,
  MIN_SCALE,
  describeScale,
  pixelLength,
  previewLength,
  scaleFrom,
  validateCalibration,
} from "../lib/calibration";

describe("длина отрезка в пикселях", () => {
  it("считает по диагонали, а не только по горизонтали", () => {
    // Линию проводят под углом — вдоль ворот, по доске наискось.
    // Если бы считали только dx, доска «укоротилась» бы, и масштаб
    // вышел бы завышенным
    const px = pixelLength([0, 0], [0.5, 0.5], 1000, 1000);
    expect(px).toBeCloseTo(Math.sqrt(500 * 500 + 500 * 500), 3);
  });

  it("учитывает, что кадр не квадратный", () => {
    const horizontal = pixelLength([0, 0.5], [1, 0.5], 1920, 1080);
    const vertical = pixelLength([0.5, 0], [0.5, 1], 1920, 1080);
    expect(horizontal).toBeCloseTo(1920);
    expect(vertical).toBeCloseTo(1080);
  });

  it("нулевой отрезок даёт ноль, а не NaN", () => {
    expect(pixelLength([0.3, 0.3], [0.3, 0.3], 1920, 1080)).toBe(0);
  });
});

describe("масштаб", () => {
  it("сантиметры делятся на пиксели", () => {
    expect(scaleFrom(100, 200)).toBeCloseTo(0.5);
  });

  it("без длины или без линии масштаба нет", () => {
    expect(scaleFrom(0, 200)).toBeNull();
    expect(scaleFrom(100, 0)).toBeNull();
    expect(scaleFrom(-100, 200)).toBeNull();
  });
});

describe("проверка калибровки", () => {
  it("пропускает правдоподобный случай", () => {
    // Метровая доска заняла 250 пикселей: 0,4 см на пиксель,
    // кадр охватывает 7,7 м — камера над проходом
    expect(validateCalibration(100, 250)).toBe("");
  });

  it("ловит метры вместо сантиметров", () => {
    // Человек написал «1» вместо «100»: масштаб 0,004 см на пиксель,
    // и корова стала бы длиной восемь сантиметров
    const problem = validateCalibration(1, 250);
    expect(problem).not.toBe("");
    expect(problem).toContain("не сходится");
  });

  it("ловит перепутанные местами сантиметры и пиксели", () => {
    // Линия в два пикселя при длине в метр: 50 см на пиксель
    expect(validateCalibration(100, 2)).not.toBe("");
  });

  it("просит сначала провести линию", () => {
    expect(validateCalibration(100, 0)).toContain("два конца");
  });

  it("просит указать длину", () => {
    expect(validateCalibration(0, 250)).toContain("длину");
  });

  it("границы включают сами себя", () => {
    // Ровно на границе — ещё принимаем: отбрасывать значение, которое
    // мы сами объявили допустимым, значит спорить с собственным правилом
    expect(validateCalibration(MIN_SCALE * 100, 100)).toBe("");
    expect(validateCalibration(MAX_SCALE * 100, 100)).toBe("");
  });
});

describe("предпросмотр", () => {
  it("крупное показывает в метрах", () => {
    expect(previewLength(0.4, 1920)).toBe("7.68 м");
  });

  it("мелкое — в сантиметрах", () => {
    expect(previewLength(0.4, 100)).toBe("40 см");
  });
});

describe("описание калибровки", () => {
  it("говорит прямо, когда камера не откалибрована", () => {
    expect(describeScale(null)).toContain("не задан");
    expect(
      describeScale({
        cm_per_pixel: null,
        calibration_length_cm: null,
        calibration_pixels: null,
        calibrated_at: null,
      })
    ).toContain("не задан");
  });

  it("переводит масштаб в ширину кадра", () => {
    const text = describeScale({
      cm_per_pixel: 0.4,
      calibration_length_cm: 100,
      calibration_pixels: 250,
      calibrated_at: "2026-08-19T10:00:00Z",
    });
    expect(text).toContain("7.7 м");
  });
});
