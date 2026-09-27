import { AnimalList } from "../../../components/AnimalList";
import { WeightAccuracyPanel } from "../../../components/WeightAccuracyPanel";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card, CardHeader } from "../../../components/ui/Card";
import { Page } from "../../../components/ui/Page";
import { demoHerd } from "../../../lib/demo/herd";
import { demoAccuracy } from "../../../lib/demo/accuracy";

export const dynamic = "force-dynamic";

export default function DemoAnimals() {
  const now = new Date();
  const rows = demoHerd(now);

  return (
    <Page>
      <PageHeader
        title="Поголовье"
        description="Животные, которых распознаёт система"
      />

      <div className="space-y-5">
        <Card>
          {/* Только чтение: раздел показа не подключён к базе, и кнопка
              удаления отвечала бы ошибкой */}
          <AnimalList rows={rows} readOnly />
        </Card>

        <Card>
          <CardHeader title="Точность веса" />
          <WeightAccuracyPanel accuracy={demoAccuracy()} />
        </Card>
      </div>
    </Page>
  );
}
