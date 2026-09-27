import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { getAnimals, getSightings, summariseAnimals } from "../../lib/sightings";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card, CardHeader } from "../../components/ui/Card";
import { WeightPanel } from "../../components/WeightPanel";
import { AnimalList } from "../../components/AnimalList";
import {
  ActiveRecording,
  RecordingGuide,
  StartRecording,
} from "../../components/AnimalRecording";
import {
  getActiveRecording,
  getLastRecording,
  getReadiness,
} from "../../lib/enrollment";
import { LastRecordingNote } from "../../components/LastRecording";
import { getFarmCameras } from "../../lib/cameras";
import { getActivity } from "../../lib/activity";
import { getTermsStatus } from "../../lib/terms";
import { countWeighings, getDailyGains, getWeightEstimates, getWeightModel } from "../../lib/weights";
import { getWeightAccuracy } from "../../lib/accuracy";
import { WeightAccuracyPanel } from "../../components/WeightAccuracyPanel";
import { Page } from "../../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function AnimalsPage() {
  const supabase = await getServerSupabase();

  let farmId: string;
  try {
    farmId = await requireFarmId(supabase);
  } catch {
    redirect("/login");
  }

  const terms = await getTermsStatus(supabase);
  if (!terms.accepted) redirect("/terms");

  const [
    animals,
    sightings,
    cameras,
    session,
    readinessByAnimal,
    weightModel,
    weightEstimates,
    dailyGains,
    weighingsDone,
    accuracy,
    activityByAnimal,
    lastRecording,
  ] = await Promise.all([
    getAnimals(supabase, farmId),
    getSightings(supabase, farmId, { limit: 120 }),
    getFarmCameras(supabase, farmId),
    getActiveRecording(supabase, farmId),
    getReadiness(supabase, farmId),
    getWeightModel(supabase, farmId),
    getWeightEstimates(supabase, farmId),
    getDailyGains(supabase, farmId),
    countWeighings(supabase, farmId),
    getWeightAccuracy(supabase, farmId),
    getActivity(supabase, farmId),
    getLastRecording(supabase, farmId),
  ]);

  const summaries = summariseAnimals(animals, sightings);
  const summaryByAnimal = new Map(summaries.map((s) => [s.animalId, s]));
  const weightByAnimal = new Map(
    weightEstimates.map((e) => [e.animal_id, e.estimated_weight_kg])
  );
  const gainByAnimal = new Map(dailyGains.map((g) => [g.animal_id, g.daily_gain_kg]));

  const rows = animals.map((animal) => ({
    id: animal.id,
    label: animal.label,
    readiness: readinessByAnimal.get(animal.id),
    sightings: summaryByAnimal.get(animal.id)?.sightings ?? 0,
    lastSeenAt: summaryByAnimal.get(animal.id)?.lastSeenAt ?? null,
    weightKg: weightByAnimal.get(animal.id) ?? null,
    dailyGainKg: gainByAnimal.get(animal.id) ?? null,
    activity: activityByAnimal.get(animal.id),
  }));

  return (
    <Page>
      <PageHeader
        title="Поголовье"
        description="Животные, которых распознаёт система"
        action={
          session ? undefined : (
            <StartRecording
              cameras={cameras.map((c) => ({ id: c.id, name: c.name }))}
              existingLabels={animals.map((a) => a.label)}
            />
          )
        }
      />

      {session ? (
        <div className="mb-5">
          <ActiveRecording
            session={session}
            cameras={cameras.map((c) => ({ id: c.id, name: c.name }))}
          />
        </div>
      ) : (
        lastRecording && (
          <div className="mb-5">
            <LastRecordingNote last={lastRecording} />
          </div>
        )
      )}

      {rows.length === 0 ? (
        <Card>
          <div className="px-5 sm:px-6 py-8 max-w-lg mx-auto text-center space-y-4">
            <p className="text-base text-ink">Поголовье не заведено</p>
            <RecordingGuide />
          </div>
        </Card>
      ) : (
        <div className="space-y-5">
          <Card>
            <AnimalList rows={rows} />
          </Card>

          {/* Взвешивание и точность рядом: это одна тема — откуда
              берутся килограммы и насколько им верить */}
          <div className="grid gap-5 lg:grid-cols-2 items-start">
            <Card>
              <CardHeader title="Взвесили на весах" />
              <WeightPanel
                animals={summaries.map((a) => ({ animalId: a.animalId, label: a.label }))}
                model={weightModel}
                weighingsDone={weighingsDone}
              />
            </Card>

            <Card>
              <CardHeader title="Точность веса" />
              <WeightAccuracyPanel accuracy={accuracy} />
            </Card>
          </div>
        </div>
      )}
    </Page>
  );
}
