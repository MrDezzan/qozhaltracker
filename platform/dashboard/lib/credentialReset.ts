import { SupabaseClient } from "@supabase/supabase-js";
import { generatePassword } from "./credentials";
import { withRetry, describeError } from "./retry";

export type ResetTarget = "owner" | "device";

export type ResetResult = {
  login: string;
  password: string;
};

/**
 * Выпускает новый пароль. Старый показать невозможно: в базе лежит
 * только его односторонний отпечаток. Поэтому «посмотреть доступы» —
 * это всегда «выпустить новые».
 */
export async function resetPassword(
  admin: SupabaseClient,
  params: { userId: string; login: string; retry?: Parameters<typeof withRetry>[1] }
): Promise<ResetResult> {
  if (!params.userId) {
    throw new Error("Не нашли, кому менять пароль");
  }

  const password = generatePassword();

  const result = await withRetry(
    () =>
      admin.auth.admin.updateUserById(params.userId, {
        password,
      }),
    params.retry ?? {}
  );

  if (result.error) {
    throw new Error(describeError(result.error));
  }

  return { login: params.login, password };
}

/** Учётные записи фермы: владелец и устройство. */
export async function getFarmAccounts(
  admin: SupabaseClient,
  farmId: string
): Promise<{
  ownerUserId: string | null;
  ownerLogin: string | null;
  deviceUserId: string | null;
  deviceLogin: string | null;
}> {
  const farm = await admin
    .from("farms")
    .select("owner_user_id")
    .eq("id", farmId)
    .single();

  const device = await admin
    .from("devices")
    .select("user_id, login")
    .eq("farm_id", farmId)
    .limit(1)
    .maybeSingle();

  let ownerLogin: string | null = null;
  const ownerUserId = (farm.data?.owner_user_id as string) ?? null;

  if (ownerUserId) {
    const user = await admin.auth.admin.getUserById(ownerUserId);
    ownerLogin = user.data?.user?.email ?? null;
  }

  return {
    ownerUserId,
    ownerLogin,
    deviceUserId: (device.data?.user_id as string) ?? null,
    deviceLogin: (device.data?.login as string) ?? null,
  };
}
