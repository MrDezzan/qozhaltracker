import { describe, expect, it } from "vitest";
import { REPEAT_AFTER_MS, shouldSpeak } from "../lib/speech";

describe("когда говорить вслух", () => {
  it("первую фразу говорим сразу", () => {
    expect(shouldSpeak("Проведите мимо камеры", null, 1000)).toBe(true);
  });

  it("ту же фразу подряд не повторяем", () => {
    // Заедающий голос раздражает сильнее, чем молчание
    const memory = { said: "Проведите мимо камеры", at: 1000 };
    expect(shouldSpeak("Проведите мимо камеры", memory, 2000)).toBe(false);
  });

  it("новую фразу говорим сразу, не дожидаясь паузы", () => {
    const memory = { said: "Проведите мимо камеры", at: 1000 };
    expect(shouldSpeak("Теперь в обратную сторону", memory, 1100)).toBe(true);
  });

  it("через долгую паузу повторяем — это уже напоминание", () => {
    const memory = { said: "Проведите мимо камеры", at: 1000 };
    expect(shouldSpeak("Проведите мимо камеры", memory, 1000 + REPEAT_AFTER_MS)).toBe(
      true
    );
  });

  it("пустую фразу не произносим", () => {
    expect(shouldSpeak("", null, 1000)).toBe(false);
    expect(shouldSpeak("   ", null, 1000)).toBe(false);
  });
});
