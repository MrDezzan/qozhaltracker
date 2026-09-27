import { describe, it, expect } from "vitest";
import { summariseZoneVisits, formatDuration } from "../lib/feeding";
import { EventRow } from "../lib/formatters";

const visit = (overrides: Record<string, unknown> = {}, id = "e1"): EventRow => ({
  id,
  camera_id: "cam-1",
  animal_id: null,
  event_type: "zone_exit",
  payload: {
    zone_id: "z1",
    zone_name: "Кормушка",
    zone_kind: "feeder",
    duration_s: 120,
    ...overrides,
  },
  occurred_at: "2026-08-09T10:00:00.000Z",
});

describe("summariseZoneVisits", () => {
  it("returns nothing without visits", () => {
    expect(summariseZoneVisits([])).toEqual([]);
  });

  it("ignores plain detections", () => {
    const detection: EventRow = { ...visit(), event_type: "detected" };
    expect(summariseZoneVisits([detection])).toEqual([]);
  });

  it("counts visits and total time per zone", () => {
    const result = summariseZoneVisits([
      visit({ duration_s: 100 }, "e1"),
      visit({ duration_s: 200 }, "e2"),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].visits).toBe(2);
    expect(result[0].totalSeconds).toBe(300);
    expect(result[0].averageSeconds).toBe(150);
  });

  it("keeps zones apart", () => {
    const result = summariseZoneVisits([
      visit({ duration_s: 100 }, "e1"),
      visit({ zone_id: "z2", zone_name: "Поилка", duration_s: 50 }, "e2"),
    ]);
    expect(result).toHaveLength(2);
  });

  it("sorts by total time, longest first", () => {
    const result = summariseZoneVisits([
      visit({ zone_id: "z1", duration_s: 10 }, "e1"),
      visit({ zone_id: "z2", zone_name: "Поилка", duration_s: 900 }, "e2"),
    ]);
    expect(result[0].zoneName).toBe("Поилка");
  });

  it("skips events without a zone", () => {
    expect(summariseZoneVisits([visit({ zone_id: undefined }, "e1")])).toEqual([]);
  });

  it("skips negative or broken durations", () => {
    expect(summariseZoneVisits([visit({ duration_s: -5 }, "e1")])).toEqual([]);
    expect(summariseZoneVisits([visit({ duration_s: "долго" }, "e2")])).toEqual([]);
  });

  it("falls back to a placeholder name", () => {
    const result = summariseZoneVisits([visit({ zone_name: undefined }, "e1")]);
    expect(result[0].zoneName).toBe("Без названия");
  });
});

describe("formatDuration", () => {
  it("shows seconds under a minute", () => {
    expect(formatDuration(45)).toBe("45 с");
  });

  it("shows whole minutes", () => {
    expect(formatDuration(300)).toBe("5 мин");
  });

  it("shows hours and minutes", () => {
    expect(formatDuration(3900)).toBe("1 ч 05 мин");
  });

  it("omits minutes when there are none", () => {
    expect(formatDuration(7200)).toBe("2 ч");
  });

  it("never shows a negative value", () => {
    expect(formatDuration(-10)).toBe("0 с");
  });
});
