"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../../lib/supabaseServer";
import { requireAdmin } from "../../../lib/adminGuard";
import { describeError } from "../../../lib/retry";
import { isVerdict } from "../../../lib/training";

export type ReviewState =
  | { status: "idle" }
  | { status: "error"; message: string };

/**
 * Ставит вердикт кадру и переходит к следующему.
 *
 * Проверка прав стоит и здесь, хотя весь раздел /admin уже за проверкой
 * в layout: там она нужна, чтобы не показывать пустые экраны, а
 * настоящая защита — политики в базе и вот эта строка. Серверное
 * действие вызывается по своему адресу и через layout не проходит.
 */
export async function reviewFrameAction(
  _prev: ReviewState,
  formData: FormData
): Promise<ReviewState> {
  const frameId = String(formData.get("frameId") ?? "");
  const verdict = String(formData.get("verdict") ?? "");

  if (!frameId) {
    return { status: "error", message: "Кадр не выбран" };
  }

  if (!isVerdict(verdict)) {
    return { status: "error", message: `Неизвестный вердикт: ${verdict}` };
  }

  try {
    const supabase = await getServerSupabase();
    await requireAdmin(supabase);

    const { data, error } = await supabase.rpc("review_training_frame", {
      p_frame_id: frameId,
      p_verdict: verdict,
    });

    if (error) {
      // У ошибки Supabase берём `.message`: describeError отдал бы
      // «[object Object]», потому что это не Error, а обычный объект
      return { status: "error", message: error.message };
    }

    // Функция вернула false — вердикт этому кадру уже стоял. Такое
    // бывает от двойного нажатия или когда открыты две вкладки.
    // Молчать нельзя: экран выглядит одинаково, и человек решит, что
    // отбраковал, хотя засчиталось чужое решение
    if (data === false) {
      return {
        status: "error",
        message: "Этому кадру вердикт уже поставлен. Открыт в другой вкладке?",
      };
    }
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }

  revalidatePath("/admin/training");
  return { status: "idle" };
}
