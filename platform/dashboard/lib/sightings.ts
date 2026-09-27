import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Встреча животного: кто, где и когда.
 *
 * Кадр здесь больше не хранится. Раньше система складывала снимок
 * каждого прохода мимо камеры в очередь «ждут имени», и человек должен
 * был опознавать животных на глаз. Очередь не кончалась, а эталоны из
 * неё были догадками — теперь животное записывается с камеры, и сюда
 * попадают только узнанные.
 */
export type SightingRow = {
  id: string;
  camera_id: string;
  animal_id: string | null;
  track_id: number;
  confidence: number | null;
  occurred_at: string;
};

export type AnimalRow = {
  id: string;
  label: string;
  created_at: string;
};

export async function getAnimals(
  client: SupabaseClient,
  farmId: string
): Promise<AnimalRow[]> {
  const { data, error } = await client
    .from("animals")
    .select("id, label, created_at")
    .eq("farm_id", farmId)
    .order("label", { ascending: true });

  if (error) throw new Error(`Не удалось загрузить животных: ${error.message}`);
  return (data as AnimalRow[]) ?? [];
}

export async function getSightings(
  client: SupabaseClient,
  farmId: string,
  options: { limit?: number } = {}
): Promise<SightingRow[]> {
  const query = client
    .from("sightings")
    .select("id, camera_id, animal_id, track_id, confidence, occurred_at")
    .eq("farm_id", farmId);


  const { data, error } = await query
    .order("occurred_at", { ascending: false })
    .limit(options.limit ?? 60);

  if (error) throw new Error(`Не удалось загрузить встречи: ${error.message}`);
  return (data as SightingRow[]) ?? [];
}

export type AnimalSummary = {
  animalId: string;
  label: string;
  sightings: number;
  lastSeenAt: string | null;
};

/** Сводка по животным: сколько раз попадалось и когда в последний раз. */
export function summariseAnimals(
  animals: AnimalRow[],
  sightings: SightingRow[]
): AnimalSummary[] {
  const counts = new Map<string, { count: number; last: string | null }>();

  for (const sighting of sightings) {
    if (!sighting.animal_id) continue;
    const existing = counts.get(sighting.animal_id);
    if (existing) {
      existing.count += 1;
      if (!existing.last || sighting.occurred_at > existing.last) {
        existing.last = sighting.occurred_at;
      }
    } else {
      counts.set(sighting.animal_id, { count: 1, last: sighting.occurred_at });
    }
  }

  return animals
    .map((animal) => ({
      animalId: animal.id,
      label: animal.label,
      sightings: counts.get(animal.id)?.count ?? 0,
      lastSeenAt: counts.get(animal.id)?.last ?? null,
    }))
    .sort((a, b) => a.label.localeCompare(b.label, "ru"));
}
