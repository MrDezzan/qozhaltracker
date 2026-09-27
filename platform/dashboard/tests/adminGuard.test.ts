import { describe, it, expect, vi } from "vitest";
import { getRole, requireAdmin, isDeviceOffline } from "../lib/adminGuard";

function makeMockClient(userId: string | null, role: string | null, error: unknown = null) {
  return {
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: userId ? { user: { id: userId } } : null },
      }),
    },
    from: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          single: vi.fn().mockResolvedValue({
            data: role ? { role } : null,
            error,
          }),
        }),
      }),
    }),
  } as any;
}

describe("getRole", () => {
  it("returns null without a session", async () => {
    expect(await getRole(makeMockClient(null, null))).toBeNull();
  });

  it("returns the role from profiles", async () => {
    expect(await getRole(makeMockClient("u1", "admin"))).toBe("admin");
    expect(await getRole(makeMockClient("u1", "owner"))).toBe("owner");
  });

  it("returns null when the profile is missing", async () => {
    expect(await getRole(makeMockClient("u1", null, { message: "no rows" }))).toBeNull();
  });
});

describe("requireAdmin", () => {
  it("passes for an admin", async () => {
    await expect(requireAdmin(makeMockClient("u1", "admin"))).resolves.toBeUndefined();
  });

  it("rejects a farm owner", async () => {
    await expect(requireAdmin(makeMockClient("u1", "owner"))).rejects.toThrow(
      /права администратора/
    );
  });

  it("rejects a device account", async () => {
    await expect(requireAdmin(makeMockClient("u1", "device"))).rejects.toThrow(
      /права администратора/
    );
  });

  it("rejects an anonymous visitor", async () => {
    await expect(requireAdmin(makeMockClient(null, null))).rejects.toThrow(
      /не вошли/
    );
  });
});

describe("isDeviceOffline", () => {
  const now = new Date("2026-08-09T12:00:00.000Z");

  it("treats a device that never reported as offline", () => {
    expect(isDeviceOffline(null, now)).toBe(true);
  });

  it("treats a recent heartbeat as online", () => {
    expect(isDeviceOffline("2026-08-09T11:58:00.000Z", now)).toBe(false);
  });

  it("treats a stale heartbeat as offline", () => {
    expect(isDeviceOffline("2026-08-09T11:50:00.000Z", now)).toBe(true);
  });

  it("is online exactly at the threshold", () => {
    expect(isDeviceOffline("2026-08-09T11:55:00.000Z", now, 5)).toBe(false);
  });

  it("is offline one second past the threshold", () => {
    expect(isDeviceOffline("2026-08-09T11:54:59.000Z", now, 5)).toBe(true);
  });

  it("respects a custom threshold", () => {
    expect(isDeviceOffline("2026-08-09T11:50:00.000Z", now, 15)).toBe(false);
  });
});
