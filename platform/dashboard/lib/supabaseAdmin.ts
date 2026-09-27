import "server-only";
import { createClient, SupabaseClient } from "@supabase/supabase-js";

/**
 * Клиент с secret-ключом: обходит RLS и умеет создавать пользователей.
 *
 * import "server-only" вверху файла — страховка от катастрофы: если этот
 * модуль случайно попадёт в клиентский бандл, сборка упадёт с ошибкой,
 * а не выложит ключ от всей базы в браузер.
 *
 * Вызывать ТОЛЬКО после успешного requireAdmin().
 */
export function getAdminSupabase(): SupabaseClient {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const secretKey = process.env.SUPABASE_SECRET_KEY;
  if (!url || !secretKey) {
    throw new Error(
      "Missing server env vars: NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SECRET_KEY"
    );
  }
  return createClient(url, secretKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

/** Домен для синтетических адресов логинов. Клиенту не показывается. */
export function getLoginDomain(): string {
  return process.env.LOGIN_EMAIL_DOMAIN || "livestock.local";
}

export function getAppUrl(): string {
  return process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000";
}
