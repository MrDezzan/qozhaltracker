import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { findFarmId } from "../../lib/auth";
import { getFarmCameras } from "../../lib/cameras";
import { getZones, ZONE_KIND_LABELS } from "../../lib/zones";
import { getCameraSnapshots } from "../../lib/snapshots";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { FarmZoneEditor } from "../../components/FarmZoneEditor";
import { deleteFarmZoneAction } from "./actions";
import { CameraCalibration } from "../../components/CameraCalibration";
import type { Calibration } from "../../lib/calibration";
import { Page } from "../../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function ZonesPage() {
  const supabase = await getServerSupabase();
  const { data } = await supabase.auth.getSession();
  if (!data.session) redirect("/login");

  const farmId = await findFarmId(supabase);
  if (!farmId) {
    return (
      <Page>
        <PageHeader
          title="Камеры"
          description="Раздел доступен владельцу хозяйства"
        />
        <Card>
          <EmptyState
            title="Ферма не привязана"
            hint="Это учётная запись администратора. Войдите под фермой."
          />
        </Card>
      </Page>
    );
  }

  const cameras = await getFarmCameras(supabase, farmId);
  const snapshots = await getCameraSnapshots(supabase, farmId, cameras);
  const zones = await getZones(supabase, farmId);

  const snapshotByCamera = new Map(snapshots.map((s) => [s.cameraId, s]));

  return (
    <Page>
      <PageHeader
        title="Камеры"
        description="Разметка кормушек и поилок на кадре"
      />

      <div className="mt-5 sm:mt-6 space-y-5 sm:space-y-6">
        {cameras.length === 0 ? (
          <Card>
            <EmptyState
              title="Камер пока нет"
              hint="Камеры подключаем мы при установке."
            />
          </Card>
        ) : (
          cameras.map((camera) => {
            const cameraZones = zones.filter((z) => z.camera_id === camera.id);
            const snapshot = snapshotByCamera.get(camera.id);

            return (
              <Card key={camera.id}>
                <CardHeader
                  title={camera.name}
                  description={
                    cameraZones.length === 0
                      ? "Зоны кормления не заданы, время не учитывается"
                      : cameraZones
                          .map((z) => `${z.name} (${ZONE_KIND_LABELS[z.kind]})`)
                          .join(", ")
                  }
                />
                <div className="px-5 sm:px-6 pb-6 space-y-4">
                  <CameraCalibration
                    cameraId={camera.id}
                    cameraName={camera.name}
                    snapshotUrl={snapshot?.liveUrl ?? null}
                    calibration={camera as unknown as Calibration}
                  />

                  <FarmZoneEditor
                    farmId={farmId}
                    cameraId={camera.id}
                    cameraName={camera.name}
                    snapshotUrl={snapshot?.liveUrl ?? null}
                    zones={cameraZones}
                  />

                  {cameraZones.length > 0 && (
                    <ul className="divide-y divide-line-soft border border-line rounded-lg">
                      {cameraZones.map((zone) => (
                        <li
                          key={zone.id}
                          className="px-4 py-2.5 flex items-center justify-between gap-4"
                        >
                          <span className="text-sm text-muted truncate">
                            {zone.name}
                            <span className="text-faint">
                              {" "}
                              · {ZONE_KIND_LABELS[zone.kind]}
                            </span>
                          </span>
                          <form action={deleteFarmZoneAction}>
                            <input type="hidden" name="zoneId" value={zone.id} />
                            <button
                              type="submit"
                              className="text-sm text-faint hover:text-trouble transition-colors shrink-0"
                            >
                              Удалить
                            </button>
                          </form>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Card>
            );
          })
        )}
      </div>

      <p className="text-xs text-faint leading-relaxed mt-6">
        Удаление зоны не затрагивает записанную историю.
      </p>
    </Page>
  );
}
