import { describe, it, expect } from "vitest";
import { timeAgo, plural, formatNumber } from "../lib/format";

const now = new Date("2026-08-09T12:00:00.000Z");

describe("plural", () => {
  it("uses the singular form for 1, 21, 31", () => {
    expect(plural(1, "минуту", "минуты", "минут")).toBe("минуту");
    expect(plural(21, "минуту", "минуты", "минут")).toBe("минуту");
  });

  it("uses the few form for 2-4", () => {
    expect(plural(3, "минуту", "минуты", "минут")).toBe("минуты");
    expect(plural(22, "минуту", "минуты", "минут")).toBe("минуты");
  });

  it("uses the many form for 5-20", () => {
    expect(plural(5, "минуту", "минуты", "минут")).toBe("минут");
    expect(plural(11, "минуту", "минуты", "минут")).toBe("минут");
    expect(plural(14, "минуту", "минуты", "минут")).toBe("минут");
  });
});

describe("timeAgo", () => {
  it("renders a dash for a missing value", () => {
    expect(timeAgo(null, now)).toBe("—");
  });

  it("says just now for the last minute", () => {
    expect(timeAgo("2026-08-09T11:59:30.000Z", now)).toBe("только что");
  });

  it("renders minutes with correct endings", () => {
    expect(timeAgo("2026-08-09T11:59:00.000Z", now)).toBe("1 минуту назад");
    expect(timeAgo("2026-08-09T11:57:00.000Z", now)).toBe("3 минуты назад");
    expect(timeAgo("2026-08-09T11:50:00.000Z", now)).toBe("10 минут назад");
  });

  it("renders hours", () => {
    expect(timeAgo("2026-08-09T09:00:00.000Z", now)).toBe("3 часа назад");
    expect(timeAgo("2026-08-09T01:00:00.000Z", now)).toBe("11 часов назад");
  });

  it("renders days", () => {
    expect(timeAgo("2026-08-07T12:00:00.000Z", now)).toBe("2 дня назад");
  });

  it("falls back to a date for old values", () => {
    expect(timeAgo("2026-01-01T12:00:00.000Z", now)).toMatch(/2026/);
  });

  it("does not break on a future timestamp", () => {
    expect(timeAgo("2026-08-09T12:05:00.000Z", now)).toBe("только что");
  });
});

describe("formatNumber", () => {
  it("groups thousands", () => {
    expect(formatNumber(12345).replace(/ /g, " ")).toBe("12 345");
  });
});
