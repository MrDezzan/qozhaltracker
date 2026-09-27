import { describe, it, expect, vi } from "vitest";
import { getFarmOverview, getCameras, maskStreamUrl } from "../lib/adminData";

function makeClient(data: unknown, error: unknown = null, withEq = false) {
  const tail = { order: vi.fn().mockResolvedValue({ data, error }) };
  const select = withEq
    ? vi.fn().mockReturnValue({ eq: vi.fn().mockReturnValue(tail) })
    : vi.fn().mockReturnValue(tail);
  return { from: vi.fn().mockReturnValue({ select }) } as any;
}

describe("getFarmOverview", () => {
  it("reads from the overview view", async () => {
    const client = makeClient([{ farm_id: "f1", farm_name: "Заря" }]);
    const rows = await getFarmOverview(client);
    expect(client.from).toHaveBeenCalledWith("admin_farm_overview");
    expect(rows).toHaveLength(1);
  });

  it("returns an empty array when there are no farms", async () => {
    await expect(getFarmOverview(makeClient(null))).resolves.toEqual([]);
  });

  it("throws a readable error", async () => {
    const client = makeClient(null, { message: "denied" });
    await expect(getFarmOverview(client)).rejects.toThrow(/denied/);
  });
});

describe("getCameras", () => {
  it("filters by farm", async () => {
    const client = makeClient([{ id: "c1" }], null, true);
    const rows = await getCameras(client, "farm-1");
    expect(client.from).toHaveBeenCalledWith("cameras");
    expect(rows).toHaveLength(1);
  });

  it("throws a readable error", async () => {
    const client = makeClient(null, { message: "nope" }, true);
    await expect(getCameras(client, "farm-1")).rejects.toThrow(/nope/);
  });
});

describe("maskStreamUrl", () => {
  it("hides the camera password", () => {
    expect(maskStreamUrl("rtsp://admin:secret123@192.168.1.64:554/stream1")).toBe(
      "rtsp://admin:••••@192.168.1.64:554/stream1"
    );
  });

  it("leaves urls without credentials untouched", () => {
    expect(maskStreamUrl("rtsp://192.168.1.64:554/stream1")).toBe(
      "rtsp://192.168.1.64:554/stream1"
    );
  });

  it("leaves a device index untouched", () => {
    expect(maskStreamUrl("0")).toBe("0");
  });
});
