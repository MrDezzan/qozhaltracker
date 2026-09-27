import { describe, it, expect, vi } from "vitest";
import {
  ZONE_KIND_LABELS,
  getZones,
  isValidPolygon,
  polygonToSvgPoints,
  polygonArea,
} from "../lib/zones";

const SQUARE: [number, number][] = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
];

describe("isValidPolygon", () => {
  it("accepts a square", () => {
    expect(isValidPolygon(SQUARE)).toBe(true);
  });

  it("rejects fewer than three points", () => {
    expect(isValidPolygon([[0, 0], [1, 1]])).toBe(false);
  });

  it("rejects coordinates outside the unit square", () => {
    expect(isValidPolygon([[0, 0], [1, 0], [1.5, 1]])).toBe(false);
    expect(isValidPolygon([[0, 0], [1, 0], [-0.1, 1]])).toBe(false);
  });

  it("rejects non-numeric coordinates", () => {
    expect(isValidPolygon([[0, 0], [1, 0], ["a", 1]])).toBe(false);
  });

  it("rejects nonsense", () => {
    expect(isValidPolygon(null)).toBe(false);
    expect(isValidPolygon("polygon")).toBe(false);
  });
});

describe("polygonToSvgPoints", () => {
  it("scales fractions to pixels", () => {
    expect(polygonToSvgPoints([[0, 0], [0.5, 1]], 100, 200)).toBe("0,0 50,200");
  });
});

describe("polygonArea", () => {
  it("computes the area of a unit square", () => {
    expect(polygonArea(SQUARE)).toBeCloseTo(1);
  });

  it("computes the area of a half square", () => {
    expect(polygonArea([[0, 0], [1, 0], [1, 0.5], [0, 0.5]])).toBeCloseTo(0.5);
  });

  it("gives zero for a degenerate line", () => {
    expect(polygonArea([[0, 0], [1, 1], [0.5, 0.5]])).toBeCloseTo(0);
  });
});

describe("ZONE_KIND_LABELS", () => {
  it("translates every kind", () => {
    expect(ZONE_KIND_LABELS.feeder).toBe("Кормушка");
    expect(ZONE_KIND_LABELS.water).toBe("Поилка");
    expect(ZONE_KIND_LABELS.gate).toBe("Проход");
  });
});

describe("getZones", () => {
  function makeClient(data: unknown, error: unknown = null) {
    return {
      from: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            order: vi.fn().mockResolvedValue({ data, error }),
          }),
        }),
      }),
    } as any;
  }

  it("returns zones for the camera", async () => {
    const client = makeClient([{ id: "z1", name: "Кормушка" }]);
    const zones = await getZones(client, "cam-1");
    expect(client.from).toHaveBeenCalledWith("zones");
    expect(zones).toHaveLength(1);
  });

  it("returns an empty list when there are none", async () => {
    await expect(getZones(makeClient(null), "cam-1")).resolves.toEqual([]);
  });

  it("throws a readable error", async () => {
    await expect(getZones(makeClient(null, { message: "denied" }), "cam-1")).rejects.toThrow(
      /denied/
    );
  });
});
