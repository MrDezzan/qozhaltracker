import { bucketHeadcountByMinute } from "../../lib/formatters";
import {
  activityByHour,
  assessFarmCondition,
  compareWithPreviousDay,
  withinHours,
} from "../../lib/analytics";
import { summariseZoneVisits, formatDuration } from "../../lib/feeding";
import { safeTimeZone, zoneOffsetLabel } from "../../lib/time";
import { EventsTable } from "../../components/EventsTable";
import { HeadcountChart } from "../../components/HeadcountChart";
import { HourlyChart } from "../../components/HourlyChart";
import { FeedingTable } from "../../components/FeedingTable";
import { AlertsFeed } from "../../components/AlertsFeed";
import { CameraSnapshots } from "../../components/CameraSnapshots";
import { FarmStatus } from "../../components/FarmStatus";
import { StatTile } from "../../components/ui/StatTile";
import { Card, CardHeader } from "../../components/ui/Card";
import { CollapsibleCard } from "../../components/ui/CollapsibleCard";
import { Page } from "../../components/ui/Page";
import {
  DEMO_ANIMAL_NAMES,
  DEMO_CAMERAS,
  DEMO_CAMERA_NAMES,
  DEMO_FARM,
  DEMO_ZONES,
} from "../../lib/demo/farm";
import { demoAlerts, demoEvents, demoSnapshots } from "../../lib/demo/events";
import { найденныеКадры } from "../../lib/demo/frames";

/**
 * Сводка хозяйства.
 *
 * Порядок блоков и все расчёты те же, что на живой ферме: страница
 * отличается только источником данных. Заводить отдельную вёрстку для
 * показа нельзя — она разойдётся с настоящей на второй правке, и
 * расхождение обнаружится в самый неподходящий момент.
 */
export const dynamic = "force-dynamic";

export default function DemoDashboard() {
  const now = new Date();
  const timeZone = safeTimeZone(DEMO_FARM.timezone);

  const events = demoEvents(now);
  const { open } = demoAlerts(now);
  const snapshots = demoSnapshots(now, найденныеКадры());

  // Показатели с подписью «за сутки» считаются по суткам, а не по всему,
  // что есть в наборе: в наборе двое суток, они нужны для сравнения с
  // вчерашним днём
  const сутки = withinHours(events, now, 24);

  const headcountPoints = bucketHeadcountByMinute([...сутки].reverse());
  const lastPoint = headcountPoints[headcountPoints.length - 1];
  // График показывает последние часы: полторы тысячи столбиков за сутки
  // не читаются и рисуются заметно дольше. Максимум при этом считается
  // по суткам — иначе подпись плитки была бы неправдой
  const headcountRecent = bucketHeadcountByMinute(
    [...withinHours(events, now, 4)].reverse(),
  );
  const peak = headcountPoints.reduce((max, p) => Math.max(max, p.count), 0);

  const zoneSummaries = summariseZoneVisits(сутки);
  const feedingSeconds = zoneSummaries
    .filter((z) => z.zoneKind === "feeder")
    .reduce((sum, z) => sum + z.totalSeconds, 0);

  const hourly = activityByHour(сутки, timeZone);
  const feedingComparison = compareWithPreviousDay(events, now);

  const eventsToday = сутки.length;

  const condition = assessFarmCondition({
    deviceOnline: true,
    camerasCount: DEMO_CAMERAS.length,
    zonesConfigured: DEMO_ZONES.length > 0,
    eventsToday,
    feeding: feedingComparison,
  });

  return (
    <Page>
      <FarmStatus condition={condition} farmName={DEMO_FARM.name} />

      <div className="mt-5">
        <Card className="border-trouble-line">
          <CardHeader
            title="Открытые тревоги"
            description="Требуют решения"
          />
          <AlertsFeed
            alerts={open}
            animalNames={DEMO_ANIMAL_NAMES}
            limit={4}
            moreHref="/demo/alerts"
            readOnly
          />
        </Card>
      </div>

      <div className="mt-5 space-y-5">
        <Card>
          <div className="px-5 py-5 sm:px-6 sm:py-6">
            <CameraSnapshots snapshots={snapshots} now={now} />
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
          <StatTile
            label="Голов в кадре"
            value={lastPoint ? lastPoint.count : 0}
            hint="одновременно, по всем камерам"
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
          <EventsTable
            events={events}
            cameraNames={DEMO_CAMERA_NAMES}
            timeZone={timeZone}
          />
        </CollapsibleCard>
      </div>
    </Page>
  );
}
