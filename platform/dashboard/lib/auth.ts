import { SupabaseClient } from "@supabase/supabase-js";

/**
 * «Вы не вошли» в одном месте на весь проект.
 *
 * Эту строку не только показывают: по ней ещё и узнают ситуацию.
 * Главная страница сравнивала ошибку с таким же текстом, написанным у
 * себя, и достаточно было поправить слово в одном из двух мест, чтобы
 * человек вместо страницы входа получил пустой экран с ошибкой. Два
 * одинаковых текста в разных файлах расходятся всегда.
 */
export const НЕ_ВОШЁЛ = "Вы не вошли";

export async function requireFarmId(client: SupabaseClient): Promise<string> {
  const { data: sessionData } = await client.auth.getUser();
  const userId = sessionData.user?.id;
  if (!userId) {
    throw new Error(НЕ_ВОШЁЛ);
  }

  const { data, error } = await client
    .from("farms")
    .select("id")
    .eq("owner_user_id", userId)
    .limit(1)
    .single();

  if (error || !data) {
    throw new Error("За этим входом нет фермы");
  }
  return data.id;
}

/**
 * Ферма текущего пользователя, либо null.
 *
 * У администратора своей фермы нет, и `requireFarmId` для него бросает
 * исключение. На страницах хозяйства это давало пустую страницу ошибки
 * вместо объяснения — а администратор заходит сюда регулярно, просто
 * чтобы посмотреть, что видит клиент.
 */
export async function findFarmId(client: SupabaseClient): Promise<string | null> {
  try {
    return await requireFarmId(client);
  } catch {
    return null;
  }
}

/** Переводит коды ошибок Supabase Auth в понятный пользователю текст. */
export function describeAuthError(message: string): string {
  if (/invalid login credentials/i.test(message)) {
    return "Неверный email или пароль";
  }
  if (/email rate limit|over_email_send_rate_limit/i.test(message)) {
    return "Слишком много писем. Подождите час или войдите по паролю";
  }
  if (/email not confirmed/i.test(message)) {
    return "Email не подтверждён. Подтвердите пользователя в Supabase → Authentication";
  }
  return message;
}
