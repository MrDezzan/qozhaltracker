import { countBySeverity } from "../../../lib/alerts";
import { AlertsFeed } from "../../../components/AlertsFeed";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card, CardHeader } from "../../../components/ui/Card";
import { StatTile } from "../../../components/ui/StatTile";
import { CollapsibleCard } from "../../../components/ui/CollapsibleCard";
import { Page } from "../../../components/ui/Page";
import { demoAlerts } from "../../../lib/demo/events";
import { DEMO_ANIMAL_NAMES } from "../../../lib/demo/farm";

export const dynamic = "force-dynamic";

export default function DemoAlerts() {
  const { open, history } = demoAlerts(new Date());
  const counts = countBySeverity(open);

  return (
    <Page>
      <PageHeader title="Тревоги" description="Посторонние в зоне охраны" />

      <div className="mb-5 grid grid-cols-3 gap-3 sm:mb-6 sm:gap-4">
        <StatTile label="Срочно" value={counts.danger} />
        <StatTile label="Внимание" value={counts.warning} />
        <StatTile label="К сведению" value={counts.info} />
      </div>

      <div className="space-y-5 sm:space-y-6">
        <Card>
          <CardHeader
            title="Активные тревоги"
            description="Закрываются при уходе человека из кадра"
          />
          <AlertsFeed alerts={open} animalNames={DEMO_ANIMAL_NAMES} readOnly />
        </Card>

        <CollapsibleCard
          title="Закрытые тревоги"
          description="История за 30 дней"
          defaultOpen={false}
        >
          <AlertsFeed
            alerts={history}
            animalNames={DEMO_ANIMAL_NAMES}
            showAdvice={false}
            readOnly
          />
        </CollapsibleCard>
      </div>
    </Page>
  );
}
