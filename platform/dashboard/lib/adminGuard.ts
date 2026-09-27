import { SupabaseClient } from "@supabase/supabase-js";
import { НЕ_ВОШЁЛ } from "./auth";

export type Role = "admin" | "owner" | "device";

export async function getRole(client: SupabaseClient): Promise<Role | null> {
  const { data: sessionData } = await client.auth.getSession();
  const userId = sessionData.session?.user.id;
  if (!userId) return null;

  const { data, error } = await client
    .from("profiles")
    .select("role")
    .eq("id", userId)
    .single();

  if (error || !data) return null;
  return data.role as Role;
}

/** Бросает исключение, если текущий пользователь не админ. */
export async function requireAdmin(client: SupabaseClient): Promise<void> {
  const role = await getRole(client);
  if (role === null) {
    throw new Error(НЕ_ВОШЁЛ);
  }
  if (role !== "admin") {
    throw new Error("Нужны права администратора");
  }
}

/** Считается ли устройство офлайн: нет отметки или она старше порога. */
export function isDeviceOffline(
  lastSeenAt: string | null,
  now: Date = new Date(),
  thresholdMinutes = 5
): boolean {
  if (!lastSeenAt) return true;
  const diffMs = now.getTime() - new Date(lastSeenAt).getTime();
  return diffMs > thresholdMinutes * 60 * 1000;
}
