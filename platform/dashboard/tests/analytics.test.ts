import { describe, it, expect } from "vitest";
import {
  activityByHour,
  compareWithPreviousDay,
  assessFarmCondition,
  nextStep,
  type Reason,
  type ReasonKind,
} from "../lib/analytics";
import { EventRow } from "../lib/formatters";

const visit = (occurredAt: string, seconds: number, id = occurredAt): EventRow => ({
  id,
  camera_id: "cam-1",
  animal_id: null,
  event_type: "zone_exit",
  payload: { zone_name: "Кормушка", zone_kind: "feeder", duration_s: seconds },
  occurred_at: occurredAt,
});

describe("activityByHour", () => {
  it("always returns 24 hours so the chart keeps its shape", () => {
    expect(activityByHour([])).toHaveLength(24);
  });

  it("puts a visit into its hour", () => {
    // Пояс задаётся явно: раньше час брался из часов машины,
    // и тест проходил или падал в зависимости от того, где его запускают
    const result = activityByHour([visit("2026-08-09T10:30:00.000Z", 120)], "UTC");
    expect(result[10].visits).toBe(1);
    expect(result[10].seconds).toBe(120);
  });

  it("sums several visits in the same hour", () => {
    const result = activityByHour(
      [
        visit("2026-08-09T10:10:00.000Z", 60, "a"),
        visit("2026-08-09T10:50:00.000Z", 90, "b"),
      ],
      "UTC"
    );
    expect(result[10].visits).toBe(2);
    expect(result[10].seconds).toBe(150);
  });

  it("counts the hour by farm time, not server time", () => {
    // Тот же момент: 22:00 по UTC — это уже три часа ночи в Алматы.
    // Без пояса весь график уезжал на пять часов, и выходило,
    // что стадо кормится ночью
    const events = [visit("2026-08-09T22:00:00.000Z", 120)];
    expect(activityByHour(events, "UTC")[22].visits).toBe(1);
    expect(activityByHour(events, "Asia/Almaty")[3].visits).toBe(1);
  });

  it("ignores other kinds of events", () => {
    const counted: EventRow = { ...visit("2026-08-09T10:00:00.000Z", 0), event_type: "counted" };
    expect(activityByHour([counted]).every((h) => h.visits === 0)).toBe(true);
  });

  it("ignores broken durations", () => {
    const broken: EventRow = {
      ...visit("2026-08-09T10:00:00.000Z", 0),
      payload: { duration_s: "долго" },
    };
    expect(activityByHour([broken]).every((h) => h.visits === 0)).toBe(true);
  });
});

describe("compareWithPreviousDay", () => {
  const now = new Date("2026-08-09T12:00:00.000Z");

  it("splits today from yesterday", () => {
    const result = compareWithPreviousDay(
      [
        visit("2026-08-09T10:00:00.000Z", 600, "today"),
        visit("2026-08-08T10:00:00.000Z", 300, "yesterday"),
      ],
      now
    );
    expect(result.today).toBe(600);
    expect(result.previous).toBe(300);
  });

  it("computes the change in percent", () => {
    const result = compareWithPreviousDay(
      [
        visit("2026-08-09T10:00:00.000Z", 150, "today"),
        visit("2026-08-08T10:00:00.000Z", 100, "yesterday"),
      ],
      now
    );
    expect(result.changePercent).toBe(50);
  });

  it("reports a drop as a negative change", () => {
    const result = compareWithPreviousDay(
      [
        visit("2026-08-09T10:00:00.000Z", 50, "today"),
        visit("2026-08-08T10:00:00.000Z", 100, "yesterday"),
      ],
      now
    );
    expect(result.changePercent).toBe(-50);
  });

  it("has no percentage without a baseline", () => {
    const result = compareWithPreviousDay([visit("2026-08-09T10:00:00.000Z", 50)], now);
    expect(result.changePercent).toBeNull();
  });

  it("ignores events older than two days", () => {
    const result = compareWithPreviousDay([visit("2026-08-01T10:00:00.000Z", 999)], now);
    expect(result.today).toBe(0);
    expect(result.previous).toBe(0);
  });
});

/** Виды причин: по ним подбирается кнопка, текст может меняться. */
const виды = (c: { reasons: { kind: string }[] }) => c.reasons.map((r) => r.kind);

describe("assessFarmCondition", () => {
  const healthy = {
    deviceOnline: true,
    camerasCount: 4,
    zonesConfigured: true,
    eventsToday: 120,
    feeding: { today: 3600, previous: 3500, changePercent: 3 },
  };

  it("gives a full score to a healthy farm", () => {
    const result = assessFarmCondition(healthy);
    expect(result.score).toBe(100);
    expect(result.label).toBe("Отклонений нет");
    expect(result.reasons).toEqual([]);
  });

  it("punishes an offline device hardest", () => {
    const result = assessFarmCondition({ ...healthy, deviceOnline: false });
    expect(result.score).toBeLessThan(60);
    expect(виды(result)).toContain("нет-связи");
  });

  it("notes missing cameras", () => {
    const result = assessFarmCondition({ ...healthy, camerasCount: 0 });
    expect(виды(result)).toContain("нет-камер");
  });

  it("notes unconfigured zones", () => {
    const result = assessFarmCondition({ ...healthy, zonesConfigured: false });
    expect(виды(result)).toContain("нет-зон");
  });

  it("notes silence from a device that is online", () => {
    const result = assessFarmCondition({ ...healthy, eventsToday: 0 });
    expect(виды(result)).toContain("тишина");
  });

  it("does not blame silence on an offline device twice", () => {
    const result = assessFarmCondition({
      ...healthy,
      deviceOnline: false,
      eventsToday: 0,
    });
    expect(виды(result)).not.toContain("тишина");
  });

  it("flags a sharp drop in feeding", () => {
    const result = assessFarmCondition({
      ...healthy,
      feeding: { today: 1000, previous: 3000, changePercent: -67 },
    });
    expect(виды(result)).toContain("мало-корма");
  });

  it("ignores a mild drop", () => {
    const result = assessFarmCondition({
      ...healthy,
      feeding: { today: 2800, previous: 3000, changePercent: -7 },
    });
    expect(result.score).toBe(100);
  });

  it("never goes below zero", () => {
    const result = assessFarmCondition({
      deviceOnline: false,
      camerasCount: 0,
      zonesConfigured: false,
      eventsToday: 0,
      feeding: { today: 0, previous: 3000, changePercent: -100 },
    });
    expect(result.score).toBeGreaterThanOrEqual(0);
  });
});

describe("что делать с причиной", () => {
  const причина = (kind: ReasonKind): Reason => ({ kind, text: "неважно" });

  it("ведёт в разметку, когда не отмечены кормушки", () => {
    expect(nextStep([причина("нет-зон")])).toEqual({
      href: "/zones",
      label: "Разметить кормушки",
    });
  });

  it("не предлагает ничего там, где фермер бессилен", () => {
    // Кнопка «Проверить камеры» при пропавшей связи с фермой уводит
    // человека туда, где он ничего не починит, и он решает, что
    // сломана программа
    expect(nextStep([причина("нет-связи")])).toBeNull();
    expect(nextStep([причина("нет-камер")])).toBeNull();
  });

  it("берёт первую причину, у которой есть куда пойти", () => {
    // Порядок причин — это порядок тяжести. Но если по самой тяжёлой
    // идти некуда, молчать незачем: показываем следующий шаг
    expect(nextStep([причина("нет-связи"), причина("нет-зон")])?.href).toBe(
      "/zones",
    );
  });

  it("без причин никуда не гонит", () => {
    expect(nextStep([])).toBeNull();
  });

  it("у каждого вида причины решено, куда идти", () => {
    // Таблица шагов объявлена как Record<ReasonKind, …>, так что
    // забыть новый вид не даст компилятор. Здесь проверяем обратное:
    // что все виды, которые ставит assessFarmCondition, таблице
    // известны и не роняют подбор
    const все: ReasonKind[] = [
      "нет-связи",
      "нет-камер",
      "нет-зон",
      "тишина",
      "мало-корма",
    ];
    for (const kind of все) {
      expect(() => nextStep([причина(kind)])).not.toThrow();
    }
  });
});
