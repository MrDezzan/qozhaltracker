import { describe, expect, it, vi } from "vitest";
import {
  getAnimals,
  getSightings,
  summariseAnimals,
  type AnimalRow,
  type SightingRow,
} from "../lib/sightings";

function sighting(overrides: Partial<SightingRow> = {}): SightingRow {
  return {
    id: "s1",
    camera_id: "cam-1",
    animal_id: "a1",
    track_id: 7,
    confidence: 0.9,
    occurred_at: "2026-08-13T10:00:00.000Z",
    ...overrides,
  };
}

function animal(overrides: Partial<AnimalRow> = {}): AnimalRow {
  return {
    id: "a1",
    label: "Зорька",
    created_at: "2026-08-01T00:00:00.000Z",
    ...overrides,
  };
}

function makeClient(data: unknown) {
  const chain: Record<string, unknown> = {};
  const self = () => chain;
  Object.assign(chain, {
    select: vi.fn(self),
    eq: vi.fn(self),
    order: vi.fn(self),
    limit: vi.fn(() => Promise.resolve({ data, error: null })),
    // Настоящий запрос supabase-js — thenable на любом шаге: один вызов
    // заканчивается на .order(), другой на .limit(). Поддельный клиент,
    // отдающий данные только с .limit(), проваливал первый из них
    then: (resolve: (value: unknown) => unknown) => resolve({ data, error: null }),
  });
  return { from: vi.fn(() => chain), _chain: chain } as never;
}

describe("getAnimals", () => {
  it("берёт животных своей фермы", async () => {
    const client = makeClient([animal()]);
    await expect(getAnimals(client, "farm-1")).resolves.toHaveLength(1);
  });
});

describe("getSightings", () => {
  it("больше не запрашивает путь к кадру", async () => {
    // Кадры не сохраняются: очередь «ждут имени» удалена целиком
    const client = makeClient([sighting()]);
    await getSightings(client, "farm-1");

    const fields = (client as never as { _chain: { select: { mock: { calls: string[][] } } } })
      ._chain.select.mock.calls[0][0];
    expect(fields).not.toContain("crop_path");
  });

  it("возвращает встречи", async () => {
    const client = makeClient([sighting()]);
    await expect(getSightings(client, "farm-1")).resolves.toHaveLength(1);
  });

  it("пустой ответ не ломает страницу", async () => {
    await expect(getSightings(makeClient(null), "farm-1")).resolves.toEqual([]);
  });
});

describe("summariseAnimals", () => {
  it("считает встречи и последний раз", () => {
    const summaries = summariseAnimals(
      [animal()],
      [
        sighting({ id: "s1", occurred_at: "2026-08-13T08:00:00.000Z" }),
        sighting({ id: "s2", occurred_at: "2026-08-13T12:00:00.000Z" }),
      ]
    );

    expect(summaries[0].sightings).toBe(2);
    expect(summaries[0].lastSeenAt).toBe("2026-08-13T12:00:00.000Z");
  });

  it("заведённое, но ни разу не встреченное животное остаётся в списке", () => {
    // Иначе только что заведённое животное исчезало бы из таблицы,
    // и человек решил бы, что оно не сохранилось
    const summaries = summariseAnimals([animal()], []);
    expect(summaries).toHaveLength(1);
    expect(summaries[0].sightings).toBe(0);
    expect(summaries[0].lastSeenAt).toBeNull();
  });

  it("сортирует по кличке", () => {
    const summaries = summariseAnimals(
      [animal({ id: "a2", label: "Ягодка" }), animal({ id: "a1", label: "Бурёнка" })],
      []
    );
    expect(summaries.map((s) => s.label)).toEqual(["Бурёнка", "Ягодка"]);
  });
});
