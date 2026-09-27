import { notFound, redirect } from "next/navigation";
import Link from "next/link";
import { getServerSupabase } from "../../../lib/supabaseServer";
import { requireFarmId } from "../../../lib/auth";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card, CardHeader } from "../../../components/ui/Card";
import { StatTile } from "../../../components/ui/StatTile";
import { getTermsStatus } from "../../../lib/terms";
import { getReadiness, readiness } from "../../../lib/enrollment";
import {
  activityVerdict,
  describeVisits,
  formatMeters,
  getActivity,
  getActivityHistory,
  getZoneVisitsByAnimal,
} from "../../../lib/activity";
import {
  formatGain,
  formatWeight,
  getDailyGains,
  getWeightEstimates,
} from "../../../lib/weights";
import { ActivityHistory } from "../../../components/ActivityHistory";
import { AnimalFeeding } from "../../../components/AnimalFeeding";
import { getAnimalDaily, getWeekChange } from "../../../lib/animalDaily";
import { RenameAnimal } from "../../../components/RenameAnimal";
import { RecordAgain } from "../../../components/AnimalRecording";
import { getFarmCameras } from "../../../lib/cameras";
import { timeAgo } from "../../../lib/format";
import { Page } from "../../../components/ui/Page";

export const dynamic = "force-dynamic";

const LEVEL_STYLE: Record<string, string> = {
  normal: "border-line bg-soft",
  low: "border-watch/30 bg-watch-bg/60",
  high: "border-watch/30 bg-watch-bg/60",
  unknown: "border-line bg-soft",
};

/**
 * Карточка животного: вся его история в одном месте.
 *
 * До неё данные о животном были размазаны: вес — в одной таблице,
 * активность — в другой, кормление считалось по стаду целиком. Ответить
 * на простой вопрос «что не так с Зорькой» было негде.
 */
export default async function AnimalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await getServerSupabase();

  let farmId: string;
  try {
    farmId = await requireFarmId(supabase);
  } catch {
    redirect("/login");
  }

  const terms = await getTermsStatus(supabase);
  if (!terms.accepted) redirect("/terms");

  const { data: animal } = await supabase
    .from("animals")
    .select("id, label, created_at")
    .eq("id", id)
    .eq("farm_id", farmId)
    .maybeSingle();

  if (!animal) notFound();

  const [
    readinessByAnimal,
    activityByAnimal,
    history,
    visitsByAnimal,
    estimates,
    gains,
    seenResult,
    daily,
    weekChange,
  ] = await Promise.all([
    getReadiness(supabase, farmId),
    getActivity(supabase, farmId),
    getActivityHistory(supabase, id, 30),
    getZoneVisitsByAnimal(supabase, farmId, 1),
    getWeightEstimates(supabase, farmId),
    getDailyGains(supabase, farmId),
    supabase
      .from("sightings")
      .select("occurred_at")
      .eq("animal_id", id)
      .order("occurred_at", { ascending: false })
      .limit(1),
    getAnimalDaily(supabase, id, 30),
    getWeekChange(supabase, id),
  ]);

  // С каких камер животное записано. Общего числа эталонов мало:
  // двенадцать штук, все с боковой камеры, означают, что верхняя это
  // животное не узнаёт — а обмер силуэта берётся только с неё, и без
  // узнавания он ложится ничей
  const [cameras, storedResult] = await Promise.all([
    getFarmCameras(supabase, farmId),
    supabase.from("animal_embeddings").select("camera_id").eq("animal_id", id),
  ]);

  const byCamera = new Map<string, number>();
  for (const row of storedResult.data ?? []) {
    const key = String((row as { camera_id: string | null }).camera_id ?? "");
    if (key) byCamera.set(key, (byCamera.get(key) ?? 0) + 1);
  }

  const status = readiness(readinessByAnimal.get(id));
  const activity = activityByAnimal.get(id);
  const move = activityVerdict(activity);
  const weight = estimates.find((e) => e.animal_id === id);
  const gain = gains.find((g) => g.animal_id === id);
  const lastSeen = seenResult.data?.[0]?.occurred_at ?? null;

  return (
    <Page width="narrow">
      <Link
        href="/animals"
        className="text-sm text-muted hover:text-ink transition-colors"
      >
        ← Всё поголовье
      </Link>

      <div className="mt-3">
        <PageHeader
          title={animal.label}
          description={
            lastSeen ? `Последний раз видели ${timeAgo(lastSeen)}` : "Ещё не видели в кадре"
          }
          action={<RenameAnimal animalId={animal.id} label={animal.label} />}
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-5 sm:mb-6">
        <StatTile
          label="Вес"
          value={formatWeight(weight?.estimated_weight_kg ?? null)}
          hint={weight ? "по камере" : "нет данных"}
        />
        <StatTile
          label="Привес"
          value={formatGain(gain?.daily_gain_kg ?? null)}
        />
        <StatTile
          label="Прошло за сутки"
          value={formatMeters(activity?.meters)}
          hint="на глазах у камеры"
        />
        <StatTile
          label="Узнавание"
          value={status.ready ? "есть" : "нет"}
          hint={status.ready ? undefined : "проведите мимо камеры"}
        />
      </div>

      <div className="space-y-5 sm:space-y-6">
        <Card>
          <CardHeader
            title="Движение"
            description="Сколько прошло на глазах у камеры"
          />
          <div className="px-5 sm:px-6 pb-6 space-y-4">
            <div className={`rounded-lg border px-4 py-3 ${LEVEL_STYLE[move.level]}`}>
              <p className="text-sm font-medium text-ink">{move.headline}</p>
              <p className="text-sm text-muted mt-1 leading-relaxed">
                {move.detail}
              </p>
            </div>

            <ActivityHistory points={history} />
          </div>
        </Card>

        <Card>
          <AnimalFeeding rows={daily} change={weekChange} />
        </Card>

        <div className="grid gap-5 lg:grid-cols-2 items-start">
          <Card>
            <CardHeader
              title="Корм и вода"
              description="За сутки"
            />
            <div className="px-5 sm:px-6 pb-6">
              <p className="text-sm text-muted leading-relaxed">
                {describeVisits(visitsByAnimal.get(id)) || "Подходов не было"}
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader title="Узнавание" />
            <div className="px-5 sm:px-6 pb-6 space-y-3">
              <p
                className={`text-sm ${
                  status.ready ? "text-calm" : "text-watch"
                }`}
              >
                {status.line}
              </p>

              {cameras.length > 1 && (
                <ul className="space-y-1">
                  {cameras.map((camera) => {
                    const stored = byCamera.get(camera.id) ?? 0;
                    return (
                      <li
                        key={camera.id}
                        className={`flex items-center gap-2 text-sm ${
                          stored > 0 ? "text-muted" : "text-watch"
                        }`}
                      >
                        <span aria-hidden className="w-3 text-center">
                          {stored > 0 ? "✓" : "○"}
                        </span>
                        {camera.name}
                        <span className="text-muted tabular-nums">
                          {stored > 0 ? `${stored} ракурсов` : "не записано"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}

              <p className="text-sm text-muted leading-relaxed">
                Камера узнаёт животное только по своим ракурсам: сверху видна
                спина, сбоку профиль. Не записана — не узнает, и вес с неё
                останется ничьим.
              </p>

              <RecordAgain
                animalId={animal.id}
                label={animal.label}
                cameras={cameras.map((c) => ({ id: c.id, name: c.name }))}
              />
            </div>
          </Card>
        </div>
      </div>
    </Page>
  );
}
