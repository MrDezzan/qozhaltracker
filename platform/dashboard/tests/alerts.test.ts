import { describe, it, expect } from "vitest";
import {
  AlertRow,
  alertAdvice,
  alertName,
  countBySeverity,
  describeAlert,
  isHealthAlert,
  isSecurityAlert,
  sortAlerts,
} from "../lib/alerts";

function alert(overrides: Partial<AlertRow> = {}): AlertRow {
  return {
    id: "a1",
    animal_id: "an-1",
    camera_id: null,
    kind: "intruder",
    severity: "warning",
    title: "Зорька",
    detail: {},
    opened_at: "2026-08-11T10:00:00.000Z",
    resolved_at: null,
    acknowledged_at: null,
    ...overrides,
  };
}

describe("alertName / alertAdvice", () => {
  it("вид тревоги переведён на человеческий язык", () => {
    expect(alertName("intruder")).not.toBe("intruder");
    expect(alertAdvice("intruder").length).toBeGreaterThan(10);
  });

  it("неизвестный вид не роняет экран", () => {
    // Виды тревог от носимых датчиков убраны вместе с датчиками, но
    // старые строки могли остаться в базе. Экран должен их пережить
    expect(alertName("low_battery")).toBe("low_battery");
    expect(alertAdvice("low_battery")).toBe("");
  });
});

describe("describeAlert", () => {
  it("посторонний описан числом людей и временем в кадре", () => {
    const text = describeAlert(
      alert({ detail: { persons: 2, seconds_present: 47 } })
    );
    expect(text).toContain("людей в кадре: 2");
    expect(text).toContain("47");
  });

  it("один человек назван в единственном числе", () => {
    const text = describeAlert(alert({ detail: { persons: 1, seconds_present: 30 } }));
    expect(text).toContain("человек в кадре");
  });

  it("пустые подробности не роняют строку", () => {
    expect(describeAlert(alert({ detail: {} }))).toContain("человек в кадре");
  });

  it("неизвестный вид описывается пустой строкой, а не падением", () => {
    expect(describeAlert(alert({ kind: "low_battery", detail: {} }))).toBe("");
  });
});

describe("sortAlerts", () => {
  it("срочное идёт выше предупреждений", () => {
    const sorted = sortAlerts([
      alert({ id: "w", severity: "warning" }),
      alert({ id: "d", severity: "danger" }),
    ]);
    expect(sorted[0].id).toBe("d");
  });

  it("непросмотренное выше отмеченного при равной срочности", () => {
    const sorted = sortAlerts([
      alert({ id: "seen", acknowledged_at: "2026-08-11T10:05:00.000Z" }),
      alert({ id: "fresh" }),
    ]);
    expect(sorted[0].id).toBe("fresh");
  });

  it("при прочих равных новое выше старого", () => {
    const sorted = sortAlerts([
      alert({ id: "old", opened_at: "2026-08-11T08:00:00.000Z" }),
      alert({ id: "new", opened_at: "2026-08-11T11:00:00.000Z" }),
    ]);
    expect(sorted[0].id).toBe("new");
  });

  it("не портит исходный список", () => {
    const input = [alert({ id: "a" }), alert({ id: "b", severity: "danger" })];
    sortAlerts(input);
    expect(input[0].id).toBe("a");
  });
});

describe("countBySeverity", () => {
  it("считает по уровням", () => {
    const counts = countBySeverity([
      alert({ severity: "danger" }),
      alert({ severity: "danger" }),
      alert({ severity: "warning" }),
    ]);
    expect(counts).toEqual({ danger: 2, warning: 1, info: 0 });
  });

  it("пустой список даёт нули, а не пустоту", () => {
    expect(countBySeverity([])).toEqual({ danger: 0, warning: 0, info: 0 });
  });
});


describe("тревоги по поведению", () => {
  function health(over: Partial<AlertRow> = {}): AlertRow {
    return {
      id: "al1",
      animal_id: "a1",
      camera_id: null,
      kind: "low_both",
      severity: "danger",
      title: "Зорьке плохо",
      detail: {
        text: "Вчера прошла 100 м при обычных 600",
        value: 100,
        baseline: 600,
        days_in_row: 2,
      },
      opened_at: "2026-08-19T06:00:00.000Z",
      resolved_at: null,
      acknowledged_at: null,
      ...over,
    };
  }

  it("у каждого вида есть человеческое название", () => {
    const kinds = [
      "low_activity",
      "low_feeding",
      "low_both",
      "not_seen",
      "no_water",
      "heat",
      "herd_low",
    ];
    for (const kind of kinds) {
      expect(alertName(kind)).not.toBe(kind);
    }
  });

  it("у каждого вида есть совет, что пойти сделать", () => {
    // Тревога без совета бесполезна: в шесть утра в телефоне «низкая
    // активность» не говорит, что делать
    const kinds = [
      "low_activity",
      "low_feeding",
      "low_both",
      "not_seen",
      "no_water",
      "heat",
      "herd_low",
    ];
    for (const kind of kinds) {
      expect(alertAdvice(kind).length).toBeGreaterThan(20);
    }
  });

  it("показывает числа, по которым сделан вывод", () => {
    // Вердикт без чисел нечем проверить, и первое же несогласие
    // человека с системой кончается тем, что он ей не верит
    const text = describeAlert(health());
    expect(text).toContain("100");
    expect(text).toContain("600");
  });

  it("говорит, сколько дней это держится", () => {
    expect(describeAlert(health())).toContain("2");
  });

  it("объяснение от устройства не теряется", () => {
    const text = describeAlert(health());
    expect(text).toContain("Вчера прошла");
  });

  it("тревога о стаде не притворяется животным", () => {
    const text = describeAlert(
      health({ kind: "herd_low", animal_id: null, detail: { value: 0.5 } })
    );
    expect(text).toContain("50");
  });

  it("битая подробность не роняет страницу", () => {
    expect(() => describeAlert(health({ detail: {} }))).not.toThrow();
  });

  it("охота не считается тревогой о здоровье", () => {
    // Высокая активность — подсказка осеменатору, а не болезнь. Смешать
    // их значит звать ветврача к здоровой корове
    expect(isHealthAlert("heat")).toBe(false);
    expect(isHealthAlert("low_both")).toBe(true);
  });

  it("охрана и здоровье не путаются", () => {
    expect(isHealthAlert("intruder")).toBe(false);
    expect(isSecurityAlert("low_both")).toBe(false);
  });
});
