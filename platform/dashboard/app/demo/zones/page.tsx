import { ZONE_KIND_LABELS } from "../../../lib/zones";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card, CardHeader } from "../../../components/ui/Card";
import { Page } from "../../../components/ui/Page";
import { DEMO_CAMERAS, DEMO_ZONES } from "../../../lib/demo/farm";
import { demoSnapshots } from "../../../lib/demo/events";
import { найденныеКадры } from "../../../lib/demo/frames";

export const dynamic = "force-dynamic";

/**
 * Камеры и заданные на них зоны.
 *
 * Редактор зон здесь не открывается: он пишет в базу, а раздел показа к
 * базе не подключён. Вместо него кадр и перечень зон камеры — того, что
 * видно на экране, достаточно, чтобы понять, как это устроено.
 */
export default function DemoZones() {
  const now = new Date();
  const snapshots = demoSnapshots(now, найденныеКадры());
  const кадрПоКамере = new Map(snapshots.map((s) => [s.cameraId, s]));

  return (
    <Page>
      <PageHeader
        title="Камеры"
        description="Разметка кормушек и поилок на кадре"
      />

      <div className="space-y-5 sm:space-y-6">
        {DEMO_CAMERAS.map((камера, индекс) => {
          const зоны = DEMO_ZONES.filter((z) => z.cameraId === камера.id);
          const кадр = кадрПоКамере.get(камера.id);

          return (
            <Card key={камера.id}>
              <CardHeader
                title={`№${индекс + 1} ${камера.name}`}
                description={
                  зоны.length === 0
                    ? "Зоны не заданы"
                    : зоны
                        .map((z) => `${z.name} (${ZONE_KIND_LABELS[z.kind]})`)
                        .join(", ")
                }
              />

              <div className="space-y-4 px-5 pb-6 sm:px-6">
                {кадр?.url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={кадр.url}
                    alt={`Кадр с камеры №${индекс + 1}, ${камера.name}`}
                    className="w-full rounded-[var(--radius-lg)] border border-line"
                  />
                ) : (
                  <p className="rounded-[var(--radius-lg)] border border-line bg-soft px-4 py-3 text-[length:var(--text-sm)] text-muted">
                    Сигнал с камеры не поступает. Разметка возможна после
                    восстановления связи.
                  </p>
                )}

                {зоны.length > 0 && (
                  <ul className="divide-y divide-line-soft rounded-[var(--radius-md)] border border-line">
                    {зоны.map((зона) => (
                      <li
                        key={зона.id}
                        className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-[length:var(--text-sm)]"
                      >
                        <span className="truncate text-ink">
                          {зона.name}
                          <span className="text-faint">
                            {" "}
                            · {ZONE_KIND_LABELS[зона.kind]}
                          </span>
                        </span>
                        <span className="shrink-0 tabular text-muted">
                          {зона.visits > 0
                            ? `${зона.visits} подходов за сутки`
                            : "подходов не зафиксировано"}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </Page>
  );
}
