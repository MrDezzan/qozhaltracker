import { SupabaseClient } from "@supabase/supabase-js";
import { НЕ_ВОШЁЛ } from "./auth";

/**
 * Версия условий. Меняется вместе с текстом.
 *
 * Согласие привязано к версии, а не к пользователю: изменили текст —
 * подняли версию, и при следующем входе система спросит заново.
 * Так у нас всегда есть доказательство, с какой именно редакцией
 * согласился заказчик и когда.
 */
export const TERMS_VERSION = "1.0";

export type TermsStatus = {
  accepted: boolean;
  acceptedAt: string | null;
  version: string;
};

export async function getTermsStatus(client: SupabaseClient): Promise<TermsStatus> {
  const { data: sessionData } = await client.auth.getSession();
  const userId = sessionData.session?.user.id;
  if (!userId) {
    return { accepted: false, acceptedAt: null, version: TERMS_VERSION };
  }

  const { data, error } = await client
    .from("terms_acceptances")
    .select("accepted_at")
    .eq("user_id", userId)
    .eq("version", TERMS_VERSION)
    .maybeSingle();

  // Недоступность базы не должна запирать заказчика снаружи его же фермы:
  // считаем, что согласие есть, и спросим при следующем входе
  if (error) {
    return { accepted: true, acceptedAt: null, version: TERMS_VERSION };
  }

  return {
    accepted: Boolean(data),
    acceptedAt: data?.accepted_at ?? null,
    version: TERMS_VERSION,
  };
}

export async function acceptTerms(client: SupabaseClient): Promise<void> {
  const { data: sessionData } = await client.auth.getSession();
  const userId = sessionData.session?.user.id;
  if (!userId) {
    throw new Error(НЕ_ВОШЁЛ);
  }

  const { error } = await client
    .from("terms_acceptances")
    .upsert(
      { user_id: userId, version: TERMS_VERSION },
      { onConflict: "user_id,version", ignoreDuplicates: true }
    );

  if (error) {
    throw new Error(`Не удалось сохранить согласие: ${error.message}`);
  }
}
