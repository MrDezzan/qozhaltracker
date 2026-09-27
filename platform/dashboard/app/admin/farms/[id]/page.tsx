import Link from "next/link";
import { notFound } from "next/navigation";
import { getServerSupabase } from "../../../../lib/supabaseServer";
import { getCameras, maskStreamUrl } from "../../../../lib/adminData";
import { isDeviceOffline } from "../../../../lib/adminGuard";
import { AddCameraForm } from "../../../../components/AddCameraForm";
import { deleteCameraAction } from "./actions";
import { PageHeader } from "../../../../components/ui/PageHeader";
import { Card, CardHeader, CardBody } from "../../../../components/ui/Card";
import { StatusBadge } from "../../../../components/ui/Badge";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { timeAgo, formatNumber } from "../../../../lib/format";
import { getRecentEvents } from "../../../../lib/events";
import { bucketHeadcountByMinute } from "../../../../lib/formatters";
import { summariseZoneVisits, formatDuration } from "../../../../lib/feeding";
import { HeadcountChart } from "../../../../components/HeadcountChart";
import { FeedingTable } from "../../../../components/FeedingTable";
import { EventsTable } from "../../../../components/EventsTable";
import { CameraSnapshots } from "../../../../components/CameraSnapshots";
import { StatTile } from "../../../../components/ui/StatTile";
import { CollapsibleCard } from "../../../../components/ui/CollapsibleCard";
import { FarmCredentials } from "../../../../components/FarmCredentials";
import { getCameraSnapshots } from "../../../../lib/snapshots";
import { getZones, ZONE_KIND_LABELS } from "../../../../lib/zones";
import { ZoneEditor } from "../../../../components/ZoneEditor";
import { deleteZoneAction } from "./zoneActions";
import { CameraSettings, PlacementBadge } from "../../../../components/CameraSettings";

export const dynamic = "force-dynamic";

export default async function FarmDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await getServerSupabase();
  const now = new Date();

  const { data: farm } = await supabase
    .from("farms")
    .select("id, name, created_at")
    .eq("id", id)
    .single();

  if (!farm) notFound();

  const [cameras, devicesResult] = await Promise.all([
    getCameras(supabase, id),
    supabase.from("devices").select("id, name, login, last_seen_at").eq("farm_id", id),
  ]);

  const devices = devicesResult.data ?? [];
  const snapshots = await getCameraSnapshots(
    supabase,
    id,
    cameras.map((c) => ({ id: c.id, name: c.name, stream_url: c.stream_url }))
  );

  const events = await getRecentEvents(supabase, id);
  const cameraNames = Object.fromEntries(cameras.map((c) => [c.id, c.name]));
  const headcountPoints = bucketHeadcountByMinute([...events].reverse());
  const zoneSummaries = summariseZoneVisits(events);
  const feedingSeconds = zoneSummaries
    .filter((z) => z.zoneKind === "feeder")
    .reduce((sum, z) => sum + z.totalSeconds, 0);
  const peak = headcountPoints.reduce((max, p) => Math.max(max, p.count), 0);

  const zonesByCamera = Object.fromEntries(
    await Promise.all(
      cameras.map(async (camera) => [camera.id, await getZones(supabase, camera.id)] as const)
    )
  );

  return (
    <main className="space-y-6">
      <PageHeader
        title={farm.name}
        description={`Подключена ${new Date(farm.created_at).toLocaleDateString("ru-RU")}`}
        breadcrumb={
          <Link href="/admin" className="text-muted hover:text-ink transition-colors">
            ← Все фермы
          </Link>
        }
      />

      <Card>
        <CardHeader
          title="Устройство"
          description="Мини-ПК на ферме, который обрабатывает видео"
        />
        {devices.length === 0 ? (
          <EmptyState
            title="Устройств нет"
            hint="Устройство создаётся вместе с фермой."
          />
        ) : (
          <ul className="border-t border-line">
            {devices.map((d) => {
              const offline = isDeviceOffline(d.last_seen_at, now);
              return (
                <li
                  key={d.id}
                  className="flex items-center gap-5 px-6 py-4 border-b border-line-soft last:border-0"
                >
                  <StatusBadge tone={offline ? "offline" : "online"}>
                    {offline ? "Офлайн" : "Онлайн"}
                  </StatusBadge>
                  <div className="min-w-0">
                    <div className="text-sm text-ink">{d.name}</div>
                    <code className="text-xs text-faint">{d.login}</code>
                  </div>
                  <div className="ml-auto text-sm text-muted text-right">
                    {d.last_seen_at
                      ? `на связи ${timeAgo(d.last_seen_at, now)}`
                      : "ни разу не выходило на связь"}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatTile label="Камер" value={cameras.length} />
        <StatTile label="Максимум голов" value={peak} />
        <StatTile
          label="Время у кормушки"
          value={feedingSeconds > 0 ? formatDuration(feedingSeconds) : "—"}
          hint={feedingSeconds > 0 ? "суммарно по стаду" : "зоны не настроены"}
        />
        <StatTile label="Событий" value={formatNumber(events.length)} />
      </div>

      <Card>
        <CardHeader
          title="Поголовье по времени"
          description="То же, что видит владелец фермы"
        />
        <div className="px-6 pb-6">
          <HeadcountChart points={headcountPoints} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Кормушки и поилки" />
        <FeedingTable zones={zoneSummaries} />
      </Card>

      {cameras.length > 0 && (
        <Card>
          <div className="px-6 py-6">
            <CameraSnapshots snapshots={snapshots} now={now} />
          </div>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Камеры"
          description={
            cameras.length > 0
              ? "Устройство подхватит изменения при следующем запуске"
              : undefined
          }
        />
        {cameras.length === 0 ? (
          <EmptyState
            title="Камер пока нет"
            hint="Добавьте камеру ниже. Ехать на ферму для этого не нужно."
          />
        ) : (
          <ul className="border-t border-line divide-y divide-line-soft">
            {cameras.map((camera) => (
              <li key={camera.id} className="px-6 py-4">
                <div className="flex items-start justify-between gap-6">
                  <div className="min-w-0">
                    <div className="text-sm text-ink">{camera.name}</div>
                    <code className="block text-xs text-muted mt-1 truncate">
                      {maskStreamUrl(camera.source_uri)}
                    </code>
                  </div>
                  <div className="shrink-0 text-right">
                    <PlacementBadge placement={camera.placement} />
                  </div>
                  <div className="shrink-0 flex items-center gap-4">
                    {/* Только поля из Props, а не camera целиком: в строке
                        лежит source_uri с паролем от камеры, и передача
                        объекта целиком отправляла бы его в браузер в
                        полезной нагрузке, хотя компонент его не просит */}
                    <CameraSettings
                      farmId={id}
                      camera={{
                        id: camera.id,
                        name: camera.name,
                        placement: camera.placement,
                        stream_url: camera.stream_url,
                        security_enabled: camera.security_enabled,
                      }}
                    />
                    <form action={deleteCameraAction}>
                      <input type="hidden" name="farmId" value={id} />
                      <input type="hidden" name="cameraId" value={camera.id} />
                      <button
                        type="submit"
                        className="text-sm text-faint hover:text-trouble transition-colors"
                      >
                        Удалить
                      </button>
                    </form>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {cameras.map((camera) => {
        const snapshot = snapshots.find((s) => s.cameraId === camera.id);
        const zones = zonesByCamera[camera.id] ?? [];
        return (
          <Card key={camera.id}>
            <CardHeader
              title={`Зоны: ${camera.name}`}
              description="Обведите кормушку: посчитаем время у неё"
            />
            <CardBody>
              {zones.length > 0 && (
                <ul className="mb-4 divide-y divide-line-soft border border-line rounded-lg">
                  {zones.map((zone) => (
                    <li key={zone.id} className="flex items-center gap-4 px-4 py-3">
                      <span className="text-sm text-ink">{zone.name}</span>
                      <span className="text-sm text-muted">
                        {ZONE_KIND_LABELS[zone.kind] ?? zone.kind}
                      </span>
                      <form action={deleteZoneAction} className="ml-auto">
                        <input type="hidden" name="farmId" value={id} />
                        <input type="hidden" name="zoneId" value={zone.id} />
                        <button
                          type="submit"
                          className="text-sm text-faint hover:text-trouble transition-colors"
                        >
                          Удалить
                        </button>
                      </form>
                    </li>
                  ))}
                </ul>
              )}
              <ZoneEditor
                farmId={id}
                cameraId={camera.id}
                cameraName={camera.name}
                snapshotUrl={snapshot?.url ?? null}
                zones={zones}
              />
            </CardBody>
          </Card>
        );
      })}

      <CollapsibleCard
        title="Доступы"
        description="Выпустить новый пароль для клиента или устройства"
        defaultOpen={false}
      >
        <div className="px-6 pb-6">
          <FarmCredentials farmId={id} farmName={farm.name} />
        </div>
      </CollapsibleCard>

      <CollapsibleCard
        title="Последние события"
        description={events.length > 0 ? `Показано ${events.length}` : undefined}
        defaultOpen={false}
      >
        <EventsTable events={events} cameraNames={cameraNames} />
      </CollapsibleCard>

      <Card>
        <CardHeader title="Добавить камеру" />
        <CardBody>
          <AddCameraForm farmId={id} />
        </CardBody>
      </Card>
    </main>
  );
}
