import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { SupabaseClient } from "@supabase/supabase-js";
import { readPublicEnv } from "./supabaseBrowser";

/**
 * Клиент для серверных компонентов и route handlers.
 * Берёт сессию из cookies, поэтому серверный рендер видит вошедшего пользователя.
 */
export async function getServerSupabase(): Promise<SupabaseClient> {
  const { url, anonKey } = readPublicEnv();
  const cookieStore = await cookies();

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          );
        } catch {
          // Server Component не может писать cookies — обновление токена
          // произойдёт в route handler /auth/callback. Это ожидаемо.
        }
      },
    },
  });
}
