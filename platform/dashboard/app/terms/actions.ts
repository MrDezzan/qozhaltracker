"use server";

import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { acceptTerms } from "../../lib/terms";
import { describeError } from "../../lib/retry";

export type AcceptState = { status: "idle" } | { status: "error"; message: string };

export async function acceptTermsAction(
  _prev: AcceptState,
  formData: FormData
): Promise<AcceptState> {
  if (formData.get("confirm") !== "on") {
    return { status: "error", message: "Отметьте согласие с условиями" };
  }

  try {
    const supabase = await getServerSupabase();
    await acceptTerms(supabase);
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }

  redirect("/");
}
