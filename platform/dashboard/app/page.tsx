import { redirect } from "next/navigation";
import { getServerSupabase } from "../lib/supabaseServer";
import { requireFarmId, НЕ_ВОШЁЛ } from "../lib/auth";
import { getRole } from "../lib/adminGuard";
import { getRecentEvents, getEventsSince } from "../lib/events";
import { bucketHeadcountByMinute } from "../lib/formatters";
import { EventsTable } from "../components/EventsTable";
import { HeadcountChart } from "../components/HeadcountChart";
import { StatTile } from "../components/ui/StatTile";
import { Card, CardHeader } from "../components/ui/Card";
import { CollapsibleCard } from "../components/ui/CollapsibleCard";
import { FarmStatus } from "../components/FarmStatus";
import { HourlyChart } from "../components/HourlyChart";
import {
  activityByHour,
  compareWithPreviousDay,
  assessFarmCondition,
  withinHours,
} from "../lib/analytics";
import { getAnimals } from "../lib/sightings";
import { isDeviceOffline } from "../lib/adminGuard";
import { CameraSnapshots } from "../components/CameraSnapshots";
import { RealtimeSync } from "../components/RealtimeSync";
import { AlertsFeed } from "../components/AlertsFeed";
import { getOpenAlerts } from "../lib/alerts";
import { getCameraSnapshots } from "../lib/snapshots";
import { remoteStreamEnabled } from "../lib/remoteStream";
import { FeedingTable } from "../components/FeedingTable";
import { summariseZoneVisits, formatDuration } from "../lib/feeding";
import { getTermsStatus } from "../lib/terms";
import { safeTimeZone, zoneOffsetLabel, timeInZone } from "../lib/time";
import { Page } from "../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = await getServerSupabase();
  const now = new Date();

  let farmId: string | null = null;
  let farmError: string | null = null;
  try {
    farmId = await requireFarmId(supabase);
  } catch (e) {
    farmError = e instanceof Error ? e.message : String(e);
  }

  if (farmError === НЕ_ВОШЁЛ) {
    redirect("/login");
  }

  const role = await getRole(supabase);

  // Условия принимаются до первого показа данных: съёмка людей требует
  // оформления, и заказчик должен знать об этом раньше, чем начнёт работать
  const terms = await getTermsStatus(supabase);
  if (!terms.accepted) {
    redirect("/terms");
  }

  if (farmError) {
    // Админ без своей фермы — обычная ситуация, ведём его в панель
    if (role === "admin") {
      redirect("/admin");
    }
    return (
      <div className="max-w-md mx-auto px-6 py-20">
        <div className="bg-surface border border-line rounded-xl px-6 py-6">
          <h1 className="text-base font-medium text-ink">Ферма не подключена</h1>
          <p className="text-sm text-muted mt-2 leading-relaxed">
            К вашей учётной записи ферма не привязана. Обратитесь в
            техническую поддержку.
          </p>
        </div>
      </div>
    );
  }

  const [
    events,
    dayEvents,
    farmResult,
    camerasResult,
    devicesResult,
    zonesResult,
    animals,
    alerts,
  ] =
    await Promise.all([
      getRecentEvents(supabase, farmId!),
      // Суточные показатели считаются по окну времени, а не по последним
      // двумстам событиям: подпись «за сутки» должна быть правдой
      getEventsSince(supabase, farmId!, new Date(now.getTime() - 48 * 3600_000)),
      supabase.from("farms").select("name, timezone").eq("id", farmId).single(),
      supabase.from("cameras").select("id, name, stream_url").eq("farm_id", farmId),
      supabase.from("devices").select("last_seen_at").eq("farm_id", farmId),
      supabase.from("zones").select("id").eq("farm_id", farmId),
      getAnimals(supabase, farmId!),
      getOpenAlerts(supabase, farmId!),
    ]);

  const farmName = farmResult.data?.name ?? "Ферма";
  // Всё, что показывается по часам, считается по времени фермы, а не сервера:
  // сервер живёт по UTC, и без этого график уезжал на пять часов
  const timeZone = safeTimeZone(farmResult.data?.timezone);
  const cameras = camerasResult.data ?? [];
  const cameraNames = Object.fromEntries(cameras.map((c) => [c.id, c.name]));

  const snapshots = await getCameraSnapshots(supabase, farmId!, cameras);

  const сутки = withinHours(dayEvents, now, 24);

  const headcountPoints = bucketHeadcountByMinute([...сутки].reverse());
  const lastPoint = headcountPoints[headcountPoints.length - 1];
  // График показывает последние часы: полторы тысячи столбиков за сутки
  // не читаются и рисуются заметно дольше. Максимум при этом считается
  // по суткам — иначе подпись плитки была бы неправдой
  const headcountRecent = bucketHeadcountByMinute(
    [...withinHours(dayEvents, now, 4)].reverse(),
  );
  const eventsToday = сутки.length;
  const peak = headcountPoints.reduce((max, p) => Math.max(max, p.count), 0);
  const zoneSummaries = summariseZoneVisits(сутки);
  const feedingSeconds = zoneSummaries
    .filter((z) => z.zoneKind === "feeder")
    .reduce((sum, z) => sum + z.totalSeconds, 0);

  const devices = devicesResult.data ?? [];
  const deviceOnline = devices.some((d) => !isDeviceOffline(d.last_seen_at, now));
  const hourly = activityByHour(сутки, timeZone);
  const feedingComparison = compareWithPreviousDay(dayEvents, now);
  const condition = assessFarmCondition({
    deviceOnline,
    camerasCount: cameras.length,
    zonesConfigured: (zonesResult.data ?? []).length > 0,
    eventsToday,
    feeding: feedingComparison,
  });
  const animalNames = Object.fromEntries(animals.map((a) => [a.id, a.label]));

  return (
    <Page>
      {/*
        Порядок на экране — это порядок вопросов, с которыми его
        открывают, а не порядок разделов в системе.

        1. Всё ли в порядке.          Ответ, а не показатели.
        2. Кто чужой на территории.   Единственное, что срочно.
        3. Что видно на камерах.      Понятнее всех цифр вместе взятых.
        4. Три числа за день.
        5. Разборы.                   Свёрнуты: их открывают редко.

        Раньше сверху стояли название фермы и строка «что происходит на
        ферме прямо сейчас» — то есть половина первого экрана телефона
        уходила на то, чтобы сообщить человеку, где он находится. Он и
        так знает: он сам сюда зашёл.
      */}
      <FarmStatus condition={condition} farmName={farmName} />

      <div className="mt-4">
        <RealtimeSync farmId={farmId!} />
      </div>

      {alerts.length > 0 && (
        <div className="mt-5">
          <Card className="border-trouble-line">
            <CardHeader
              title="Открытые тревоги"
              description="Требуют решения"
            />
            <AlertsFeed alerts={alerts} animalNames={animalNames} limit={4} />
          </Card>
        </div>
      )}

      <div className="mt-5 space-y-5">
        {/* Заголовок рисует сам блок трансляции: он меняется вместе с
            выбранной камерой, а шапка карточки собирается на сервере и
            о выборе не знает */}
        <Card>
          <div className="px-5 py-5 sm:px-6 sm:py-6">
            <CameraSnapshots
              snapshots={snapshots}
              now={now}
              remoteAvailable={remoteStreamEnabled()}
            />
          </div>
        </Card>

        {/* Два столбца на телефоне, три на широком экране: три плитки в
            ряд на 375 пикселях дают число шрифтом в спичку */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
          <StatTile
            label="Голов в кадре"
            value={lastPoint ? lastPoint.count : 0}
            hint={
              lastPoint
                ? `в ${timeInZone(lastPoint.bucketStart, timeZone)}`
                : "нет данных"
            }
          />
          <StatTile label="Максимум за сутки" value={peak} />
          <StatTile
            label="Время у кормушек"
            value={feedingSeconds > 0 ? formatDuration(feedingSeconds) : "—"}
            hint={
              feedingComparison.changePercent !== null
                ? `${feedingComparison.changePercent > 0 ? "больше" : "меньше"} вчерашнего на ${Math.abs(feedingComparison.changePercent)}%`
                : "вчера данных не было"
            }
          />
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="Поголовье в кадре"
              description="По минутам, за последние часы"
            />
            <div className="px-5 pb-6 sm:px-6">
              <HeadcountChart points={headcountRecent} timeZone={timeZone} />
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Кормушки и поилки"
              description="Время у каждой зоны за сутки"
            />
            <FeedingTable zones={zoneSummaries} />
          </Card>
        </div>

        <CollapsibleCard
          title="Подходы по часам"
          description={`По часам, время фермы ${zoneOffsetLabel(timeZone, now)}`}
          defaultOpen={false}
        >
          <div className="pb-1">
            <HourlyChart points={hourly} />
          </div>
        </CollapsibleCard>

        <CollapsibleCard
          title="Журнал событий"
          description="По каждому животному"
          defaultOpen={false}
        >
          <EventsTable events={events} cameraNames={cameraNames} timeZone={timeZone} />
        </CollapsibleCard>
      </div>
    </Page>
  );
}
