import { createBrowserClient } from "@supabase/ssr";
import { SupabaseClient } from "@supabase/supabase-js";

export function readPublicEnv(): { url: string; anonKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "Missing Supabase env vars: NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY"
    );
  }
  return { url, anonKey };
}

let cached: SupabaseClient | null = null;

/** Ленивый синглтон: не падает при импорте модуля без env-переменных. */
export function getBrowserSupabase(): SupabaseClient {
  if (!cached) {
    const { url, anonKey } = readPublicEnv();
    cached = createBrowserClient(url, anonKey);
  }
  return cached;
}
