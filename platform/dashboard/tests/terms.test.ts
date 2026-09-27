import { describe, it, expect, vi } from "vitest";
import { SupabaseClient } from "@supabase/supabase-js";
import { TERMS_VERSION, acceptTerms, getTermsStatus } from "../lib/terms";

function client({
  userId = "u-1",
  row = null as { accepted_at: string } | null,
  error = null as { message: string } | null,
  upsert = vi.fn().mockResolvedValue({ error: null }),
}) {
  const maybeSingle = vi.fn().mockResolvedValue({ data: row, error });
  const eq2 = vi.fn().mockReturnValue({ maybeSingle });
  const eq1 = vi.fn().mockReturnValue({ eq: eq2 });
  const select = vi.fn().mockReturnValue({ eq: eq1 });

  return {
    client: {
      auth: {
        getSession: vi
          .fn()
          .mockResolvedValue({ data: { session: userId ? { user: { id: userId } } : null } }),
      },
      from: vi.fn().mockReturnValue({ select, upsert }),
    } as unknown as SupabaseClient,
    upsert,
    eq1,
    eq2,
  };
}

describe("getTermsStatus", () => {
  it("нет записи — согласия нет", async () => {
    const { client: c } = client({});
    expect((await getTermsStatus(c)).accepted).toBe(false);
  });

  it("есть запись — согласие принято", async () => {
    const { client: c } = client({ row: { accepted_at: "2026-08-01T00:00:00.000Z" } });
    const status = await getTermsStatus(c);
    expect(status.accepted).toBe(true);
    expect(status.acceptedAt).toBe("2026-08-01T00:00:00.000Z");
  });

  it("проверяется именно текущая редакция", async () => {
    const { client: c, eq2 } = client({});
    await getTermsStatus(c);
    expect(eq2).toHaveBeenCalledWith("version", TERMS_VERSION);
  });

  it("неавторизованный пользователь не считается согласившимся", async () => {
    const { client: c } = client({ userId: "" });
    expect((await getTermsStatus(c)).accepted).toBe(false);
  });

  it("сбой базы не запирает заказчика снаружи его же фермы", async () => {
    // Иначе любая рябь связи выкидывала бы всех на экран условий
    const { client: c } = client({ error: { message: "нет связи" } });
    expect((await getTermsStatus(c)).accepted).toBe(true);
  });
});

describe("acceptTerms", () => {
  it("сохраняет согласие с версией", async () => {
    const { client: c, upsert } = client({});
    await acceptTerms(c);
    expect(upsert).toHaveBeenCalledWith(
      { user_id: "u-1", version: TERMS_VERSION },
      expect.objectContaining({ onConflict: "user_id,version" })
    );
  });

  it("повторное нажатие не создаёт вторую запись", async () => {
    const { client: c, upsert } = client({});
    await acceptTerms(c);
    expect(upsert.mock.calls[0][1]).toMatchObject({ ignoreDuplicates: true });
  });

  it("без авторизации согласие не сохраняется", async () => {
    const { client: c } = client({ userId: "" });
    await expect(acceptTerms(c)).rejects.toThrow("не вошли");
  });

  it("ошибка записи не проглатывается", async () => {
    const upsert = vi.fn().mockResolvedValue({ error: { message: "нет прав" } });
    const { client: c } = client({ upsert });
    await expect(acceptTerms(c)).rejects.toThrow("нет прав");
  });
});
