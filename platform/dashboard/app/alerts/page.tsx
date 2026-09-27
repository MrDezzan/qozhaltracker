import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { getTermsStatus } from "../../lib/terms";
import {
  countBySeverity,
  getOpenAlerts,
  getRecentAlertHistory,
} from "../../lib/alerts";
import { getAnimals } from "../../lib/sightings";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card, CardHeader } from "../../components/ui/Card";
import { StatTile } from "../../components/ui/StatTile";
import { CollapsibleCard } from "../../components/ui/CollapsibleCard";
import { AlertsFeed } from "../../components/AlertsFeed";
import { RealtimeSync } from "../../components/RealtimeSync";
import { DetectNowButton } from "../../components/DetectNowButton";
import { Page } from "../../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function AlertsPage() {
  const supabase = await getServerSupabase();

  let farmId: string;
  try {
    farmId = await requireFarmId(supabase);
  } catch {
    redirect("/login");
  }

  const terms = await getTermsStatus(supabase);
  if (!terms.accepted) redirect("/terms");

  const [open, history, animals] = await Promise.all([
    getOpenAlerts(supabase, farmId),
    getRecentAlertHistory(supabase, farmId, 30),
    getAnimals(supabase, farmId),
  ]);

  const animalNames = Object.fromEntries(animals.map((a) => [a.id, a.label]));
  const counts = countBySeverity(open);

  return (
    <Page>
      <PageHeader
        title="Тревоги"
        description="Посторонние в зоне охраны"
      />

      <div className="mb-5">
        <RealtimeSync farmId={farmId} />
      </div>

      <div className="grid grid-cols-3 gap-3 sm:gap-4 mb-5 sm:mb-6">
        <StatTile label="Срочно" value={counts.danger} />
        <StatTile label="Внимание" value={counts.warning} />
        <StatTile label="К сведению" value={counts.info} />
      </div>

      <div className="space-y-5 sm:space-y-6">
        <Card>
          <CardHeader
            title="Активные тревоги"
            description="Закрываются при уходе человека из кадра"
            action={<DetectNowButton />}
          />
          <AlertsFeed alerts={open} animalNames={animalNames} />
        </Card>


        <CollapsibleCard
          title="Закрытые тревоги"
          description="История за 30 дней"
          defaultOpen={false}
        >
          <AlertsFeed alerts={history} animalNames={animalNames} showAdvice={false} />
        </CollapsibleCard>
      </div>
    </Page>
  );
}
