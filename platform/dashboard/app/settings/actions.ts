"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { describeError } from "../../lib/retry";
import {
  TIMEZONES,
  DAY_GUARD_OPTIONS,
  describeGuardWindow,
  validateGuardWindow,
} from "../../lib/settings";

export type SettingsState =
  | { status: "idle" }
  | { status: "ok"; message: string }
  | { status: "error"; message: string };

function refresh() {
  revalidatePath("/settings");
  revalidatePath("/");
  revalidatePath("/alerts");
}

export async function setTimezoneAction(
  _prev: SettingsState,
  formData: FormData
): Promise<SettingsState> {
  const timezone = String(formData.get("timezone") ?? "");
  if (!TIMEZONES.some((t) => t.value === timezone)) {
    return { status: "error", message: "Выберите пояс из списка" };
  }

  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { error } = await supabase.rpc("set_farm_timezone", {
      target_farm_id: farmId,
      new_timezone: timezone,
    });
    if (error) {
      console.error("[settings] сохранение", error);
      return { status: "error", message: "Не удалось сохранить" };
    }

    refresh();
    return { status: "ok", message: "Часовой пояс сохранён" };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

export async function setRetentionAction(
  _prev: SettingsState,
  formData: FormData
): Promise<SettingsState> {
  const read = (key: string, min: number, max: number, title: string) => {
    const value = Number(formData.get(key) ?? NaN);
    if (!Number.isFinite(value) || value < min || value > max) {
      throw new Error(`${title}: от ${min} до ${max} дней`);
    }
    return Math.round(value);
  };

  try {
    const events = read("eventsDays", 30, 3650, "События");
    const sightings = read("sightingsDays", 7, 3650, "Кадры животных");
    const snapshots = read("snapshotsDays", 1, 90, "Кадры предпросмотра");

    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { error } = await supabase.from("retention_policy").upsert(
      {
        farm_id: farmId,
        events_days: events,
        sightings_days: sightings,
        snapshots_days: snapshots,
      },
      { onConflict: "farm_id" }
    );
    if (error) {
      console.error("[settings] сохранение", error);
      return { status: "error", message: "Не удалось сохранить" };
    }

    refresh();
    return { status: "ok", message: "Сроки хранения сохранены" };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

/**
 * Охранное окно: когда человек в кадре считается посторонним.
 *
 * Вынесено в интерфейс, потому что это единственная настройка охраны,
 * которую точно придётся править по месту: на одной ферме сторож обходит
 * территорию в полночь, на другой доярки приходят в четыре утра.
 */
export async function setGuardWindowAction(
  _prev: SettingsState,
  formData: FormData
): Promise<SettingsState> {
  const from = String(formData.get("guardFrom") ?? "").trim();
  const to = String(formData.get("guardTo") ?? "").trim();

  const problem = validateGuardWindow(from, to);
  if (problem) return { status: "error", message: problem };

  const daySeverity = String(formData.get("daySeverity") ?? "warning");
  const known = DAY_GUARD_OPTIONS.some((option) => option.value === daySeverity);
  if (!known) return { status: "error", message: "Выберите дневной режим" };

  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { error } = await supabase.from("alert_settings").upsert(
      { farm_id: farmId, guard_from: from, guard_to: to, guard_day_severity: daySeverity },
      { onConflict: "farm_id" }
    );
    if (error) {
      console.error("[settings] сохранение", error);
      return { status: "error", message: "Не удалось сохранить" };
    }

    refresh();
    return {
      status: "ok",
      message: `Охрана ${describeGuardWindow(from, to)}`,
    };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

