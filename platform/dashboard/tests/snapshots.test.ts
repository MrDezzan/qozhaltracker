import { describe, it, expect, vi } from "vitest";
import {
  SNAPSHOT_BUCKET,
  snapshotPath,
  frameUrl,
  getSnapshotUrl,
  getSnapshotUpdatedAt,
  getCameraSnapshots,
  isSnapshotStale,
} from "../lib/snapshots";

function makeStorageClient(options: {
  signed?: { signedUrl: string } | null;
  signedError?: unknown;
  list?: unknown[] | null;
  listError?: unknown;
}) {
  const from = vi.fn().mockReturnValue({
    createSignedUrl: vi.fn().mockResolvedValue({
      data: options.signed ?? null,
      error: options.signedError ?? null,
    }),
    list: vi.fn().mockResolvedValue({
      data: options.list ?? null,
      error: options.listError ?? null,
    }),
  });
  return { storage: { from } } as any;
}

describe("snapshotPath", () => {
  it("puts the farm first so access rules can rely on it", () => {
    expect(snapshotPath("farm-1", "cam-2")).toBe("farm-1/cam-2.jpg");
  });
});

describe("getSnapshotUrl", () => {
  it("returns a signed url", async () => {
    const client = makeStorageClient({ signed: { signedUrl: "https://x/signed" } });
    await expect(getSnapshotUrl(client, "farm-1", "cam-1")).resolves.toBe("https://x/signed");
    expect(client.storage.from).toHaveBeenCalledWith(SNAPSHOT_BUCKET);
  });

  it("returns null when the snapshot does not exist yet", async () => {
    const client = makeStorageClient({ signedError: { message: "not found" } });
    await expect(getSnapshotUrl(client, "farm-1", "cam-1")).resolves.toBeNull();
  });
});

describe("getSnapshotUpdatedAt", () => {
  it("reads the update time from the listing", async () => {
    const client = makeStorageClient({
      list: [{ name: "cam-1.jpg", updated_at: "2026-08-09T12:00:00.000Z" }],
    });
    await expect(getSnapshotUpdatedAt(client, "farm-1", "cam-1")).resolves.toBe(
      "2026-08-09T12:00:00.000Z"
    );
  });

  it("falls back to creation time", async () => {
    const client = makeStorageClient({
      list: [{ name: "cam-1.jpg", created_at: "2026-08-09T11:00:00.000Z" }],
    });
    await expect(getSnapshotUpdatedAt(client, "farm-1", "cam-1")).resolves.toBe(
      "2026-08-09T11:00:00.000Z"
    );
  });

  it("returns null for an empty listing", async () => {
    const client = makeStorageClient({ list: [] });
    await expect(getSnapshotUpdatedAt(client, "farm-1", "cam-1")).resolves.toBeNull();
  });
});

describe("getCameraSnapshots", () => {
  it("returns one entry per camera", async () => {
    const client = makeStorageClient({
      signed: { signedUrl: "https://x/signed" },
      list: [{ name: "c.jpg", updated_at: "2026-08-09T12:00:00.000Z" }],
    });
    const result = await getCameraSnapshots(client, "farm-1", [
      { id: "cam-1", name: "Кормушка" },
      { id: "cam-2", name: "Поилка" },
    ]);
    expect(result).toHaveLength(2);
    expect(result[0].cameraName).toBe("Кормушка");

    // Адрес ведёт на наш сервер, а не в хранилище: по прямой ссылке
    // приходила копия из сети доставки, а не свежий кадр
    expect(result[1].url).toBe("/api/frame/cam-2");
    expect(result[1].url).not.toContain("http");
  });
});

describe("frameUrl", () => {
  it("ведёт на наш сервер, где заголовками распоряжаемся мы", () => {
    expect(frameUrl("cam-1")).toBe("/api/frame/cam-1");
  });

  it("не отдаёт наружу подписанную ссылку на файл", () => {
    // Доступ проверяется на каждый кадр, а не один раз на десять минут
    expect(frameUrl("cam-1")).not.toContain("token");
  });
});

describe("isSnapshotStale", () => {
  const now = new Date("2026-08-09T12:00:00.000Z");

  it("treats a missing snapshot as stale", () => {
    expect(isSnapshotStale(null, now)).toBe(true);
  });

  it("treats a fresh snapshot as current", () => {
    expect(isSnapshotStale("2026-08-09T11:59:00.000Z", now)).toBe(false);
  });

  it("treats an old snapshot as stale", () => {
    expect(isSnapshotStale("2026-08-09T11:40:00.000Z", now)).toBe(true);
  });

  it("respects a custom threshold", () => {
    expect(isSnapshotStale("2026-08-09T11:40:00.000Z", now, 30)).toBe(false);
  });
});
