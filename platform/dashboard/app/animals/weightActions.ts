"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { describeError } from "../../lib/retry";

export type WeighingState =
  | { status: "idle" }
  | { status: "ok"; message: string }
  | { status: "error"; message: string };

/**
 * Вес с настоящих весов.
 *
 * Это единственный источник правды: пока таких записей нет, система не
 * знает, сколько весит животное её размера, и показывать килограммы
 * нечестно.
 *
 * Пересчёт формулы идёт здесь же. Раньше для него была отдельная кнопка
 * «пересчитать» — и это оказалось лишним понятием: человек вносил вес,
 * ничего не менялось, и было непонятно, работает система или нет.
 */
export async function addWeighingAction(
  _prev: WeighingState,
  formData: FormData
): Promise<WeighingState> {
  const animalId = String(formData.get("animalId") ?? "");
  const raw = String(formData.get("weightKg") ?? "").replace(",", ".");
  const weightKg = Number(raw);

  if (!animalId) {
    return { status: "error", message: "Выберите животное" };
  }
  if (!Number.isFinite(weightKg) || weightKg <= 0 || weightKg >= 2000) {
    return { status: "error", message: "Введите вес в килограммах" };
  }

  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { error } = await supabase.from("weighings").insert({
      farm_id: farmId,
      animal_id: animalId,
      weight_kg: weightKg,
      source: "manual",
    });

    if (error) {
      console.error("[weights] insert", error);
      return { status: "error", message: "Не удалось сохранить вес" };
    }

    // Пересчитываем сразу. Ошибку молча глушим: вес уже записан, и это
    // главное, а формула подберётся при следующем взвешивании
    const { data } = await supabase.rpc("fit_weight_model", {
      target_farm_id: farmId,
    });
    const model = Array.isArray(data) ? data[0] : data;
    const done = model?.sample_count ?? 0;

    revalidatePath("/animals");
    revalidatePath(`/animals/${animalId}`);

    return {
      status: "ok",
      message: done
        ? `Записано. Система учла ${done} взвешиваний`
        : "Записано",
    };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

