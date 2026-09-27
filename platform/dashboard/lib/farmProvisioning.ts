import { SupabaseClient } from "@supabase/supabase-js";
import { issueCredentials, IssuedCredentials } from "./credentials";
import { withRetry, describeError } from "./retry";

export type ProvisionedFarm = {
  farmId: string;
  farmName: string;
  owner: IssuedCredentials;
  device: IssuedCredentials;
  deviceId: string;
};

type RetryOptions = {
  attempts?: number;
  delayMs?: number;
  sleep?: (ms: number) => Promise<void>;
};

/**
 * Создаёт ферму целиком: учётку владельца, саму ферму, учётку устройства.
 *
 * admin — клиент с secret-ключом (см. supabaseAdmin.ts).
 * Пароли возвращаются один раз и нигде не сохраняются.
 *
 * Каждый сетевой вызов повторяется при обрыве связи: Supabase Auth
 * иногда рвёт соединение на втором запросе подряд.
 * При неустранимой ошибке откатывает уже созданное, чтобы не оставлять
 * висящих пользователей без фермы.
 */
export async function provisionFarm(
  admin: SupabaseClient,
  params: { farmName: string; domain: string; retry?: RetryOptions }
): Promise<ProvisionedFarm> {
  const farmName = params.farmName.trim();
  if (!farmName) {
    throw new Error("Название фермы не может быть пустым");
  }

  const retry = params.retry ?? {};
  const owner = issueCredentials("farm", params.domain);
  const device = issueCredentials("device", params.domain);

  const createdUserIds: string[] = [];
  let createdFarmId: string | null = null;

  const rollback = async () => {
    // Откат сам может упасть по сети — это не должно скрыть исходную ошибку
    if (createdFarmId) {
      try {
        await admin.from("farms").delete().eq("id", createdFarmId);
      } catch (e) {
        console.error("Откат: не удалось удалить ферму", describeError(e));
      }
    }
    for (const id of createdUserIds) {
      try {
        await admin.auth.admin.deleteUser(id);
      } catch (e) {
        console.error("Откат: не удалось удалить пользователя", id, describeError(e));
      }
    }
  };

  try {
    // 1. Владелец. email_confirm: true — иначе вход потребует письма,
    // которого на синтетический адрес всё равно не придёт.
    const ownerUser = await withRetry(
      () =>
        admin.auth.admin.createUser({
          email: owner.authEmail,
          password: owner.password,
          email_confirm: true,
          app_metadata: { role: "owner" },
        }),
      retry
    );
    if (ownerUser.error || !ownerUser.data.user) {
      throw new Error(`Не удалось создать владельца: ${ownerUser.error?.message}`);
    }
    createdUserIds.push(ownerUser.data.user.id);

    // 2. Ферма
    const farm = await withRetry(
      async () =>
        await admin
          .from("farms")
          .insert({ name: farmName, owner_user_id: ownerUser.data.user!.id })
          .select("id")
          .single(),
      retry
    );
    if (farm.error || !farm.data) {
      throw new Error(`Не удалось создать ферму: ${farm.error?.message}`);
    }
    createdFarmId = farm.data.id;

    // 3. Устройство
    const deviceUser = await withRetry(
      () =>
        admin.auth.admin.createUser({
          email: device.authEmail,
          password: device.password,
          email_confirm: true,
          app_metadata: { role: "device" },
        }),
      retry
    );
    if (deviceUser.error || !deviceUser.data.user) {
      throw new Error(`Не удалось создать устройство: ${deviceUser.error?.message}`);
    }
    createdUserIds.push(deviceUser.data.user.id);

    // Явная проверка вместо приведения типа: если ферма не создалась,
    // лучше упасть здесь с понятным текстом, чем записать битую ссылку.
    const farmId = createdFarmId;
    if (!farmId) {
      throw new Error("Внутренняя ошибка: ферма не создана");
    }

    // Профиль устройства должен знать свою ферму — на этом держится RLS
    const profile = await withRetry(
      async () =>
        await admin
          .from("profiles")
          .update({ role: "device", farm_id: farmId })
          .eq("id", deviceUser.data.user!.id),
      retry
    );
    if (profile.error) {
      throw new Error(`Не удалось привязать устройство к ферме: ${profile.error.message}`);
    }

    const deviceRow = await withRetry(
      async () =>
        await admin
          .from("devices")
          .insert({
            farm_id: farmId,
            user_id: deviceUser.data.user!.id,
            name: "Основное устройство",
            login: device.login,
          })
          .select("id")
          .single(),
      retry
    );
    if (deviceRow.error || !deviceRow.data) {
      throw new Error(`Не удалось создать устройство: ${deviceRow.error?.message}`);
    }

    return {
      farmId,
      farmName,
      owner,
      device,
      deviceId: deviceRow.data.id,
    };
  } catch (e) {
    await rollback();
    // Разворачиваем причину: "fetch failed" сам по себе ничего не объясняет
    throw new Error(describeError(e));
  }
}
