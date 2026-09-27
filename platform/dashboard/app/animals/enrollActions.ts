"use server";

import { revalidatePath } from "next/cache";
import { getServerSupabase } from "../../lib/supabaseServer";
import { этоUuid } from "../../lib/validate";
import { requireFarmId } from "../../lib/auth";
import { describeError } from "../../lib/retry";
import { RecordingSession } from "../../lib/enrollment";

export type EnrollState =
  | { status: "idle" }
  | { status: "ok"; message: string }
  | { status: "error"; message: string };

function refresh() {
  revalidatePath("/animals");
}

/**
 * Начать запись животного.
 *
 * Заводит животное и открывает сеанс одним вызовом базы. Разделять
 * нельзя: между «завёл» и «начал писать» появилось бы состояние, в
 * котором животное в списке есть, а эталонов у него никогда не будет —
 * и оно молча не узнавалось бы.
 */
export async function startRecordingAction(
  _prev: EnrollState,
  formData: FormData
): Promise<EnrollState> {
  // Камер может быть несколько: верхняя и боковая пишут одно и то же
  // животное за один прогон. Эталоны с них несопоставимы между собой —
  // сверху спина, сбоку профиль, — и одна камера не запишет за другую
  const cameraIds = formData
    .getAll("cameraIds")
    .map((one) => String(one))
    .filter(Boolean);
  const label = String(formData.get("label") ?? "").trim();
  const animalId = String(formData.get("animalId") ?? "");

  if (cameraIds.length === 0) {
    return { status: "error", message: "Отметьте хотя бы одну камеру" };
  }
  if (!animalId && !label) {
    return { status: "error", message: "Введите кличку или номер" };
  }

  try {
    const supabase = await getServerSupabase();
    await requireFarmId(supabase);

    const { error } = await supabase.rpc("start_recording", {
      target_camera_ids: cameraIds,
      animal_label: label || null,
      existing_animal_id: animalId || null,
    });

    if (error) {
      console.error("[enroll] start_recording", error);
      return { status: "error", message: "Не удалось начать запись" };
    }

    refresh();
    return { status: "ok", message: "Запись началась" };
  } catch (e) {
    return { status: "error", message: describeError(e) };
  }
}

/** Остановить запись. Пустую запись база превращает в отмену. */
/*
  Проверка входа стоит в каждом действии записи отдельно.

  Раньше эти четыре опирались только на политики в базе: RPC вызываются
  от имени пользователя, и чужую запись Postgres не отдаст. Защита
  рабочая, но единственная, а результат RPC даже не читался, поэтому
  отказ выглядел как успех. Проверка в коде ставит барьер раньше и
  делает отказ видимым.
*/
export async function finishRecordingAction(formData: FormData): Promise<void> {
  const sessionId = String(formData.get("sessionId") ?? "");
  if (!этоUuid(sessionId)) return;

  const supabase = await getServerSupabase();
  await requireFarmId(supabase);
  const { error } = await supabase.rpc("finish_recording", { session_id: sessionId });
  if (error) console.error("[enroll] finish_recording", error);
  refresh();
}

/**
 * Отменить запись.
 *
 * Заведённое ради неё животное база удалит, если эталонов так и не
 * появилось. Иначе каждая передумка оставляла бы в списке пустую
 * строку, и через месяц там сорок «Зорек», которых никто не заводил.
 */
export async function cancelRecordingAction(formData: FormData): Promise<void> {
  const sessionId = String(formData.get("sessionId") ?? "");
  if (!этоUuid(sessionId)) return;

  const supabase = await getServerSupabase();
  await requireFarmId(supabase);
  const { error } = await supabase.rpc("cancel_recording", { session_id: sessionId });
  if (error) console.error("[enroll] cancel_recording", error);
  refresh();
}

/**
 * Пропустить ракурс, который животное не показывает.
 *
 * Без этого строгое требование всех четырёх превращает запись в тупик:
 * человек крутит животное, оно не идёт, счётчик стоит.
 */
export async function skipRecordingViewAction(formData: FormData): Promise<void> {
  const sessionId = String(formData.get("sessionId") ?? "");
  if (!этоUuid(sessionId)) return;

  const supabase = await getServerSupabase();
  await requireFarmId(supabase);
  const { error } = await supabase.rpc("skip_recording_view", { session_id: sessionId });
  if (error) console.error("[enroll] skip_recording_view", error);
  refresh();
}

/** Состояние идущей записи — для обновления счётчика на экране. */
export async function pollRecordingAction(): Promise<RecordingSession | null> {
  try {
    const supabase = await getServerSupabase();
    const farmId = await requireFarmId(supabase);

    const { data } = await supabase
      .from("active_recording")
      .select("id, camera_id, camera_ids, animal_id, label, captured, needed, target, per_camera, captured_by, per_view, views_order, views_done, views_skipped, awaiting_view, hint, started_at, expires_at")
      .eq("farm_id", farmId)
      .limit(1)
      .maybeSingle();

    return (data as RecordingSession | null) ?? null;
  } catch {
    return null;
  }
}

export async function renameAnimalAction(formData: FormData): Promise<void> {
  const animalId = String(formData.get("animalId") ?? "");
  const label = String(formData.get("label") ?? "").trim();
  // Предел длины: кличка уезжает в заголовки таблиц и в текст тревог,
  // а строка на тысячу знаков ломает и то, и другое
  if (!этоUuid(animalId) || !label || label.length > 80) return;

  const supabase = await getServerSupabase();
  await requireFarmId(supabase);
  const { error } = await supabase.rpc("rename_animal", {
    target_animal_id: animalId,
    new_label: label,
  });
  if (error) console.error("[enroll] rename_animal", error);
  refresh();
}

/**
 * Удалить животное.
 *
 * Вместе с ним уходят эталоны — иначе в базе остались бы векторы без
 * хозяина, и система продолжала бы узнавать «того, кого нет».
 */
export async function deleteAnimalAction(formData: FormData): Promise<void> {
  const animalId = String(formData.get("animalId") ?? "");
  if (!этоUuid(animalId)) return;

  const supabase = await getServerSupabase();
  const farmId = await requireFarmId(supabase);
  await supabase.from("animals").delete().eq("id", animalId).eq("farm_id", farmId);
  refresh();
}
