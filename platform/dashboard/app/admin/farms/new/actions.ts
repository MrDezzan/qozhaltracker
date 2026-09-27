"use server";

import { getServerSupabase } from "../../../../lib/supabaseServer";
import { getAdminSupabase, getLoginDomain, getAppUrl } from "../../../../lib/supabaseAdmin";
import { requireAdmin } from "../../../../lib/adminGuard";
import { provisionFarm } from "../../../../lib/farmProvisioning";
import { formatHandoffMessage } from "../../../../lib/credentials";
import { describeError } from "../../../../lib/retry";

export type CreateFarmState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | {
      status: "success";
      farmName: string;
      ownerText: string;
      deviceText: string;
    };

export async function createFarmAction(
  _prev: CreateFarmState,
  formData: FormData
): Promise<CreateFarmState> {
  const farmName = String(formData.get("farmName") ?? "").trim();

  try {
    // Права проверяем клиентом пользователя, а не admin-клиентом:
    // admin-клиент обходит RLS и подтвердил бы что угодно.
    const userClient = await getServerSupabase();
    await requireAdmin(userClient);

    const admin = getAdminSupabase();
    const result = await provisionFarm(admin, { farmName, domain: getLoginDomain() });

    return {
      status: "success",
      farmName: result.farmName,
      ownerText: formatHandoffMessage({
        farmName: result.farmName,
        login: result.owner.login,
        password: result.owner.password,
        appUrl: getAppUrl(),
      }),
      deviceText: [
        `# Настройки устройства фермы «${result.farmName}»`,
        `# Вставить в файл cv-service/.env на мини-ПК`,
        ``,
        `SUPABASE_URL=${process.env.NEXT_PUBLIC_SUPABASE_URL ?? ""}`,
        `SUPABASE_ANON_KEY=${process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ""}`,
        `DEVICE_LOGIN=${result.device.authEmail}`,
        `DEVICE_PASSWORD=${result.device.password}`,
        ``,
        `# Отладка на ноутбучной камере: раскомментируйте строку ниже`,
        `# TRACKED_CLASSES=person`,
      ].join("\n"),
    };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}
