import { describe, it, expect, vi } from "vitest";
import { provisionFarm } from "../lib/farmProvisioning";

type Scenario = {
  createUserFails?: boolean;
  farmInsertFails?: boolean;
  deviceUserFails?: boolean;
  profileUpdateFails?: boolean;
};

function makeAdminClient(scenario: Scenario = {}) {
  const deletedUsers: string[] = [];
  const deletedFarms: string[] = [];
  let userCounter = 0;

  const createUser = vi.fn().mockImplementation(async () => {
    userCounter += 1;
    if (scenario.createUserFails && userCounter === 1) {
      return { data: { user: null }, error: { message: "boom" } };
    }
    if (scenario.deviceUserFails && userCounter === 2) {
      return { data: { user: null }, error: { message: "device boom" } };
    }
    return { data: { user: { id: `user-${userCounter}` } }, error: null };
  });

  const client = {
    auth: {
      admin: {
        createUser,
        deleteUser: vi.fn().mockImplementation(async (id: string) => {
          deletedUsers.push(id);
          return { error: null };
        }),
      },
    },
    from: vi.fn().mockImplementation((table: string) => {
      if (table === "farms") {
        return {
          insert: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              single: vi.fn().mockResolvedValue(
                scenario.farmInsertFails
                  ? { data: null, error: { message: "farm boom" } }
                  : { data: { id: "farm-1" }, error: null }
              ),
            }),
          }),
          delete: vi.fn().mockReturnValue({
            eq: vi.fn().mockImplementation(async (_col: string, id: string) => {
              deletedFarms.push(id);
              return { error: null };
            }),
          }),
        };
      }
      if (table === "profiles") {
        return {
          update: vi.fn().mockReturnValue({
            eq: vi.fn().mockResolvedValue(
              scenario.profileUpdateFails ? { error: { message: "profile boom" } } : { error: null }
            ),
          }),
        };
      }
      return {
        insert: vi.fn().mockReturnValue({
          select: vi.fn().mockReturnValue({
            single: vi.fn().mockResolvedValue({ data: { id: "device-1" }, error: null }),
          }),
        }),
      };
    }),
  } as any;

  return { client, deletedUsers, deletedFarms, createUser };
}

const noSleep = async () => {};
const params = {
  farmName: "Заря",
  domain: "livestock.local",
  retry: { attempts: 3, sleep: noSleep },
};

describe("provisionFarm", () => {
  it("creates owner, farm and device and returns credentials once", async () => {
    const { client } = makeAdminClient();
    const result = await provisionFarm(client, params);

    expect(result.farmId).toBe("farm-1");
    expect(result.farmName).toBe("Заря");
    expect(result.owner.login).toMatch(/^ferma-/);
    expect(result.device.login).toMatch(/^device-/);
    expect(result.owner.password).toHaveLength(16);
    expect(result.owner.password).not.toBe(result.device.password);
  });

  it("confirms emails so login works without a mailbox", async () => {
    const { client, createUser } = makeAdminClient();
    await provisionFarm(client, params);
    for (const call of createUser.mock.calls) {
      expect(call[0].email_confirm).toBe(true);
    }
  });

  it("marks the device account with the device role", async () => {
    const { client, createUser } = makeAdminClient();
    await provisionFarm(client, params);
    expect(createUser.mock.calls[0][0].app_metadata).toEqual({ role: "owner" });
    expect(createUser.mock.calls[1][0].app_metadata).toEqual({ role: "device" });
  });

  it("rejects an empty farm name", async () => {
    const { client } = makeAdminClient();
    await expect(provisionFarm(client, { ...params, farmName: "   " })).rejects.toThrow(
      /не может быть пустым/
    );
  });

  it("rolls back the owner when farm creation fails", async () => {
    const { client, deletedUsers } = makeAdminClient({ farmInsertFails: true });
    await expect(provisionFarm(client, params)).rejects.toThrow(/Не удалось создать ферму/);
    expect(deletedUsers).toEqual(["user-1"]);
  });

  it("rolls back farm and owner when the device account fails", async () => {
    const { client, deletedUsers, deletedFarms } = makeAdminClient({ deviceUserFails: true });
    await expect(provisionFarm(client, params)).rejects.toThrow(/Не удалось создать устройство/);
    expect(deletedFarms).toEqual(["farm-1"]);
    expect(deletedUsers).toEqual(["user-1"]);
  });

  it("rolls back everything when binding the device to the farm fails", async () => {
    const { client, deletedUsers, deletedFarms } = makeAdminClient({ profileUpdateFails: true });
    await expect(provisionFarm(client, params)).rejects.toThrow(/привязать устройство/);
    expect(deletedFarms).toEqual(["farm-1"]);
    expect(deletedUsers).toEqual(["user-1", "user-2"]);
  });

  it("does not create a farm when the owner account fails", async () => {
    const { client, deletedFarms } = makeAdminClient({ createUserFails: true });
    await expect(provisionFarm(client, params)).rejects.toThrow(/создать владельца/);
    expect(deletedFarms).toEqual([]);
  });
});


describe("provisionFarm resilience", () => {
  it("retries a transient network failure and succeeds", async () => {
    const { client, createUser } = makeAdminClient();
    createUser.mockReset();
    let calls = 0;
    createUser.mockImplementation(async () => {
      calls += 1;
      if (calls === 1) throw new Error("fetch failed");
      return { data: { user: { id: `user-${calls}` } }, error: null };
    });

    const result = await provisionFarm(client, params);
    expect(result.farmId).toBe("farm-1");
    expect(calls).toBeGreaterThan(2);
  });

  it("reports the real cause instead of bare fetch failed", async () => {
    const { client, createUser } = makeAdminClient();
    createUser.mockReset();
    createUser.mockImplementation(async () => {
      throw new Error("fetch failed", {
        cause: new Error("getaddrinfo ENOTFOUND db.supabase.co"),
      });
    });

    await expect(provisionFarm(client, params)).rejects.toThrow(/ENOTFOUND/);
  });

  it("still returns the original error when rollback itself fails", async () => {
    const { client } = makeAdminClient({ deviceUserFails: true });
    client.auth.admin.deleteUser.mockRejectedValue(new Error("fetch failed"));
    await expect(provisionFarm(client, params)).rejects.toThrow(/создать устройство/);
  });
});
