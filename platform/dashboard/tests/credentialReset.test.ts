import { describe, it, expect, vi } from "vitest";
import { resetPassword, getFarmAccounts } from "../lib/credentialReset";

const noSleep = async () => {};

function makeAdmin(options: { updateError?: unknown } = {}) {
  const updateUserById = vi
    .fn()
    .mockResolvedValue({ data: { user: { id: "u1" } }, error: options.updateError ?? null });
  return {
    admin: { auth: { admin: { updateUserById } } } as any,
    updateUserById,
  };
}

describe("resetPassword", () => {
  it("issues a fresh strong password", async () => {
    const { admin } = makeAdmin();
    const result = await resetPassword(admin, {
      userId: "u1",
      login: "ferma-abc",
      retry: { sleep: noSleep },
    });
    expect(result.login).toBe("ferma-abc");
    expect(result.password).toHaveLength(16);
  });

  it("never returns the same password twice", async () => {
    const { admin } = makeAdmin();
    const first = await resetPassword(admin, { userId: "u1", login: "l", retry: { sleep: noSleep } });
    const second = await resetPassword(admin, { userId: "u1", login: "l", retry: { sleep: noSleep } });
    expect(first.password).not.toBe(second.password);
  });

  it("writes the new password to the account", async () => {
    const { admin, updateUserById } = makeAdmin();
    const result = await resetPassword(admin, {
      userId: "u1",
      login: "l",
      retry: { sleep: noSleep },
    });
    expect(updateUserById).toHaveBeenCalledWith("u1", { password: result.password });
  });

  it("refuses without an account", async () => {
    const { admin } = makeAdmin();
    await expect(
      resetPassword(admin, { userId: "", login: "l", retry: { sleep: noSleep } })
    ).rejects.toThrow(/кому менять пароль/);
  });

  it("surfaces the real reason on failure", async () => {
    const { admin } = makeAdmin({ updateError: new Error("fetch failed") });
    await expect(
      resetPassword(admin, { userId: "u1", login: "l", retry: { sleep: noSleep } })
    ).rejects.toThrow(/fetch failed/);
  });
});

describe("getFarmAccounts", () => {
  function makeClient(farmData: unknown, deviceData: unknown, email: string | null) {
    return {
      from: vi.fn().mockImplementation((table: string) => {
        if (table === "farms") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                single: vi.fn().mockResolvedValue({ data: farmData }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              limit: vi.fn().mockReturnValue({
                maybeSingle: vi.fn().mockResolvedValue({ data: deviceData }),
              }),
            }),
          }),
        };
      }),
      auth: {
        admin: {
          getUserById: vi
            .fn()
            .mockResolvedValue({ data: email ? { user: { email } } : null }),
        },
      },
    } as any;
  }

  it("returns both accounts", async () => {
    const client = makeClient(
      { owner_user_id: "u1" },
      { user_id: "u2", login: "device-abc" },
      "ferma-xyz@livestock.local"
    );
    const accounts = await getFarmAccounts(client, "farm-1");
    expect(accounts.ownerUserId).toBe("u1");
    expect(accounts.ownerLogin).toBe("ferma-xyz@livestock.local");
    expect(accounts.deviceUserId).toBe("u2");
    expect(accounts.deviceLogin).toBe("device-abc");
  });

  it("survives a farm without a device", async () => {
    const client = makeClient({ owner_user_id: "u1" }, null, "a@b.c");
    const accounts = await getFarmAccounts(client, "farm-1");
    expect(accounts.deviceUserId).toBeNull();
  });

  it("survives a missing owner", async () => {
    const client = makeClient(null, null, null);
    const accounts = await getFarmAccounts(client, "farm-1");
    expect(accounts.ownerUserId).toBeNull();
  });
});
