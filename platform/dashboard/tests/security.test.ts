import { describe, expect, it } from "vitest";
import {
  alertAdvice,
  alertName,
  describeAlert,
  isSecurityAlert,
  type AlertRow,
} from "../lib/alerts";
import {
  describeGuardWindow,
  toTimeInput,
  validateGuardWindow,
} from "../lib/settings";

function intruder(detail: Record<string, unknown> = {}): AlertRow {
  return {
    id: "a1",
    animal_id: null,
    camera_id: "cam-1",
    snapshot_path: "farm-1/intruder/cam-1.jpg",
    kind: "intruder",
    severity: "danger",
    title: "Посторонний на территории: Въезд",
    detail,
    opened_at: "2026-08-13T22:10:00Z",
    resolved_at: null,
    acknowledged_at: null,
  };
}

describe("тревога о постороннем", () => {
  it("названа по-человечески", () => {
    expect(alertName("intruder")).toBe("Посторонний на территории");
  });

  it("подсказывает, что делать, включая случай «это свой»", () => {
    // Тревога без подсказки бесполезна в три часа ночи. И главное —
    // человек должен знать, как её унять, а не просто выключить охрану
    const advice = alertAdvice("intruder");
    expect(advice).toContain("снимок");
    expect(advice).toContain("охранное окно");
  });

  it("описывается цифрами, из-за которых поднялась", () => {
    expect(describeAlert(intruder({ persons: 1, seconds_present: 12.4 }))).toBe(
      "человек в кадре, держится 12 с"
    );
  });

  it("нескольких людей называет во множественном числе", () => {
    expect(describeAlert(intruder({ persons: 3, seconds_present: 7 }))).toBe(
      "людей в кадре: 3, держится 7 с"
    );
  });

  it("не ломается на пустых подробностях", () => {
    expect(describeAlert(intruder())).toContain("человек в кадре");
  });

  it("отделяется от прочих тревог", () => {
    // Охрана — своя срочность и свои люди: «посторонний ночью» не должен
    // теряться среди хозяйственных сообщений
    expect(isSecurityAlert("intruder")).toBe(true);
    expect(isSecurityAlert("headcount_drop")).toBe(false);
  });
});

describe("охранное окно", () => {
  it("время из базы обрезается до формата поля", () => {
    // Иначе браузер молча показывает пустое поле, и настройка выглядит
    // незаполненной, хотя она задана
    expect(toTimeInput("22:00:00", "00:00")).toBe("22:00");
    expect(toTimeInput("06:30:00+05", "00:00")).toBe("06:30");
  });

  it("пустое значение заменяется значением по умолчанию", () => {
    expect(toTimeInput(null, "22:00")).toBe("22:00");
    expect(toTimeInput("", "22:00")).toBe("22:00");
    expect(toTimeInput("ночью", "22:00")).toBe("22:00");
  });

  it("окно через полночь называется вслух", () => {
    // «с 22:00 до 06:00» без пояснения читается как пустой промежуток
    expect(describeGuardWindow("22:00", "06:00")).toContain("через полночь");
  });

  it("обычное окно читается просто", () => {
    expect(describeGuardWindow("09:00", "18:00")).toBe("с 09:00 до 18:00");
  });

  it("совпадающие границы означают круглосуточно", () => {
    expect(describeGuardWindow("00:00", "00:00")).toBe("круглосуточно");
  });

  it("мусор в поле не сохраняется", () => {
    expect(validateGuardWindow("22:00", "06:00")).toBe("");
    expect(validateGuardWindow("ночью", "06:00")).not.toBe("");
    expect(validateGuardWindow("", "")).not.toBe("");
  });
});
