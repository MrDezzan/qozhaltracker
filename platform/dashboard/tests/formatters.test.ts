import { describe, it, expect } from "vitest";
import { bucketHeadcountByMinute, EventRow } from "../lib/formatters";

const baseEvent = (overrides: Partial<EventRow>): EventRow => ({
  id: "evt-1",
  camera_id: "cam-1",
  animal_id: null,
  event_type: "detected",
  payload: {},
  occurred_at: "2026-08-07T10:00:00.000Z",
  ...overrides,
});

describe("bucketHeadcountByMinute", () => {
  it("counts distinct track ids within the same minute", () => {
    const events = [
      baseEvent({ id: "1", payload: { track_id: 1 }, occurred_at: "2026-08-07T10:00:05.000Z" }),
      baseEvent({ id: "2", payload: { track_id: 2 }, occurred_at: "2026-08-07T10:00:40.000Z" }),
      baseEvent({ id: "3", payload: { track_id: 1 }, occurred_at: "2026-08-07T10:00:50.000Z" }),
    ];
    const result = bucketHeadcountByMinute(events);
    expect(result).toEqual([{ bucketStart: "2026-08-07T10:00:00.000Z", count: 2 }]);
  });

  it("ignores non-detected event types", () => {
    const events = [
      baseEvent({ id: "1", event_type: "health_alert", payload: { track_id: 1 } }),
    ];
    expect(bucketHeadcountByMinute(events)).toEqual([]);
  });

  it("splits counts across separate minute buckets", () => {
    const events = [
      baseEvent({ id: "1", payload: { track_id: 1 }, occurred_at: "2026-08-07T10:00:05.000Z" }),
      baseEvent({ id: "2", payload: { track_id: 1 }, occurred_at: "2026-08-07T10:01:05.000Z" }),
    ];
    const result = bucketHeadcountByMinute(events);
    expect(result).toEqual([
      { bucketStart: "2026-08-07T10:00:00.000Z", count: 1 },
      { bucketStart: "2026-08-07T10:01:00.000Z", count: 1 },
    ]);
  });
});

describe("bucketHeadcountByMinute with summary events", () => {
  const counted = (bucket: string, count: number, id = bucket): EventRow => ({
    id,
    camera_id: "cam-1",
    animal_id: null,
    event_type: "counted",
    payload: { unique_count: count, peak_in_frame: count },
    occurred_at: `${bucket}:00.000Z`,
  });

  it("reads the count straight from a summary event", () => {
    expect(bucketHeadcountByMinute([counted("2026-08-07T10:00", 4)])).toEqual([
      { bucketStart: "2026-08-07T10:00:00.000Z", count: 4 },
    ]);
  });

  it("takes the largest value when several cameras report the same minute", () => {
    const result = bucketHeadcountByMinute([
      counted("2026-08-07T10:00", 2, "a"),
      counted("2026-08-07T10:00", 5, "b"),
    ]);
    expect(result).toEqual([{ bucketStart: "2026-08-07T10:00:00.000Z", count: 5 }]);
  });

  it("still understands older per-detection events", () => {
    const legacy: EventRow = {
      id: "old",
      camera_id: "cam-1",
      animal_id: null,
      event_type: "detected",
      payload: { track_id: 1 },
      occurred_at: "2026-08-07T09:00:00.000Z",
    };
    expect(bucketHeadcountByMinute([legacy])).toEqual([
      { bucketStart: "2026-08-07T09:00:00.000Z", count: 1 },
    ]);
  });

  it("prefers the summary when both kinds land in the same minute", () => {
    const legacy: EventRow = {
      id: "old",
      camera_id: "cam-1",
      animal_id: null,
      event_type: "detected",
      payload: { track_id: 1 },
      occurred_at: "2026-08-07T10:00:30.000Z",
    };
    const result = bucketHeadcountByMinute([counted("2026-08-07T10:00", 7), legacy]);
    expect(result).toEqual([{ bucketStart: "2026-08-07T10:00:00.000Z", count: 7 }]);
  });

  it("ignores broken counts", () => {
    const broken: EventRow = {
      ...counted("2026-08-07T10:00", 0),
      payload: { unique_count: "много" },
    };
    expect(bucketHeadcountByMinute([broken])).toEqual([]);
  });
});
