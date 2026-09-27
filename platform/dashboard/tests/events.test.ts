import { describe, it, expect, vi } from "vitest";
import { getRecentEvents } from "../lib/events";

function makeMockClient(data: unknown, error: unknown = null) {
  const eq = vi.fn().mockReturnValue({
    order: vi.fn().mockReturnValue({
      limit: vi.fn().mockResolvedValue({ data, error }),
    }),
  });
  return {
    client: {
      from: vi.fn().mockReturnValue({ select: vi.fn().mockReturnValue({ eq }) }),
    } as any,
    eq,
  };
}

describe("getRecentEvents", () => {
  it("returns rows from the events table", async () => {
    const { client } = makeMockClient([{ id: "1", event_type: "detected" }]);
    const rows = await getRecentEvents(client, "farm-1", 50);
    expect(rows).toEqual([{ id: "1", event_type: "detected" }]);
    expect(client.from).toHaveBeenCalledWith("events");
  });

  it("always filters by farm, so an admin does not see other farms here", async () => {
    const { client, eq } = makeMockClient([]);
    await getRecentEvents(client, "farm-1");
    expect(eq).toHaveBeenCalledWith("farm_id", "farm-1");
  });

  it("throws a readable error when Supabase returns an error", async () => {
    const { client } = makeMockClient(null, { message: "network down" });
    await expect(getRecentEvents(client, "farm-1")).rejects.toThrow(/network down/);
  });

  it("returns an empty array when Supabase returns null data", async () => {
    const { client } = makeMockClient(null);
    await expect(getRecentEvents(client, "farm-1")).resolves.toEqual([]);
  });
});
