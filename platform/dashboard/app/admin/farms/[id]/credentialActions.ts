"use server";

import { getServerSupabase } from "../../../../lib/supabaseServer";
import { getAdminSupabase, getAppUrl } from "../../../../lib/supabaseAdmin";
import { requireAdmin } from "../../../../lib/adminGuard";
import { getFarmAccounts, resetPassword, ResetTarget } from "../../../../lib/credentialReset";
import { formatHandoffMessage, fromAuthEmail } from "../../../../lib/credentials";
import { describeError } from "../../../../lib/retry";

export type CredentialsState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "success"; target: ResetTarget; text: string };

export async function resetFarmCredentialsAction(
  _prev: CredentialsState,
  formData: FormData
): Promise<CredentialsState> {
  const farmId = String(formData.get("farmId") ?? "");
  const farmName = String(formData.get("farmName") ?? "");
  const target = String(formData.get("target") ?? "owner") as ResetTarget;

  try {
    // Права проверяем клиентом пользователя: admin-клиент обходит RLS
    const userClient = await getServerSupabase();
    await requireAdmin(userClient);

    const admin = getAdminSupabase();
    const accounts = await getFarmAccounts(admin, farmId);

    if (target === "owner") {
      if (!accounts.ownerUserId || !accounts.ownerLogin) {
        return { status: "error", message: "У фермы нет логина владельца" };
      }
      const result = await resetPassword(admin, {
        userId: accounts.ownerUserId,
        login: fromAuthEmail(accounts.ownerLogin),
      });
      return {
        status: "success",
        target,
        text: formatHandoffMessage({
          farmName,
          login: result.login,
          password: result.password,
          appUrl: getAppUrl(),
        }),
      };
    }

    if (!accounts.deviceUserId || !accounts.deviceLogin) {
      return { status: "error", message: "У фермы нет логина устройства" };
    }

    const user = await admin.auth.admin.getUserById(accounts.deviceUserId);
    const deviceEmail = user.data?.user?.email ?? accounts.deviceLogin;

    const result = await resetPassword(admin, {
      userId: accounts.deviceUserId,
      login: accounts.deviceLogin,
    });

    return {
      status: "success",
      target,
      text: [
        `# Настройки устройства фермы «${farmName}»`,
        `# Вставить в файл cv-service/.env на мини-ПК`,
        ``,
        `SUPABASE_URL=${process.env.NEXT_PUBLIC_SUPABASE_URL ?? ""}`,
        `SUPABASE_ANON_KEY=${process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ""}`,
        `DEVICE_LOGIN=${deviceEmail}`,
        `DEVICE_PASSWORD=${result.password}`,
      ].join("\n"),
    };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}
