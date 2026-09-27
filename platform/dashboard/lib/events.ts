import { SupabaseClient } from "@supabase/supabase-js";
import { EventRow } from "./formatters";

/**
 * События конкретной фермы.
 *
 * Фильтр по ферме обязателен, а не «и так отсечёт RLS»: у админа права
 * шире, и без фильтра ему пришли бы события всех ферм разом.
 */
export async function getRecentEvents(
  client: SupabaseClient,
  farmId: string,
  limit = 200
): Promise<EventRow[]> {
  const { data, error } = await client
    .from("events")
    .select("id, camera_id, animal_id, event_type, payload, occurred_at")
    .eq("farm_id", farmId)
    .order("occurred_at", { ascending: false })
    .limit(limit);

  if (error) {
    throw new Error(`Не удалось загрузить события: ${error.message}`);
  }
  return (data as EventRow[]) ?? [];
}

/**
 * События за окно времени, а не «последние N штук».
 *
 * ЗАЧЕМ ОТДЕЛЬНЫЙ ЗАПРОС
 *
 * Суточные показатели на экране фермы считались по `getRecentEvents`,
 * то есть по двумстам последним событиям. Подпись говорила «за сутки», а
 * на ферме с пятью камерами двести событий набегают за двадцать минут:
 * «время у кормушек за сутки» показывало двадцать минут, и заметить это
 * можно было только сравнив с журналом вручную.
 *
 * Потолок всё равно нужен: на большой ферме за сутки набирается десятки
 * тысяч событий, и тянуть их все в браузер незачем. Но теперь он
 * срабатывает как защита от перегрузки, а не как определение слова
 * «сутки».
 *
 * Индекс под этот запрос — миграция 0053, по (farm_id, occurred_at).
 */
export async function getEventsSince(
  client: SupabaseClient,
  farmId: string,
  since: Date,
  limit = 20_000
): Promise<EventRow[]> {
  const { data, error } = await client
    .from("events")
    .select("id, camera_id, animal_id, event_type, payload, occurred_at")
    .eq("farm_id", farmId)
    .gte("occurred_at", since.toISOString())
    .order("occurred_at", { ascending: false })
    .limit(limit);

  if (error) {
    throw new Error(`Не удалось загрузить события: ${error.message}`);
  }
  return (data as EventRow[]) ?? [];
}
