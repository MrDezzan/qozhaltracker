import Link from "next/link";
import { FarmOverviewRow } from "../lib/adminData";
import { isDeviceOffline } from "../lib/adminGuard";
import { StatusBadge } from "./ui/Badge";
import { EmptyState } from "./ui/EmptyState";
import { Button } from "./ui/Button";
import { timeAgo, formatNumber } from "../lib/format";

type Props = {
  farms: FarmOverviewRow[];
  now?: Date;
};

export function FarmsTable({ farms, now = new Date() }: Props) {
  if (farms.length === 0) {
    return (
      <EmptyState
        title="Ферм пока нет"
        hint="Логин и пароль формируются автоматически."
        action={
          <Link href="/admin/farms/new">
            <Button>Создать ферму</Button>
          </Link>
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[560px]">
      <thead>
        <tr className="text-left text-muted border-b border-line">
          <th className="font-normal px-6 py-3">Ферма</th>
          <th className="font-normal px-6 py-3">Связь</th>
          <th className="font-normal px-6 py-3 text-right">Камер</th>
          <th className="font-normal px-6 py-3 text-right">Событий за сутки</th>
          <th className="font-normal px-6 py-3">Последнее событие</th>
        </tr>
      </thead>
      <tbody>
        {farms.map((farm) => {
          const offline = isDeviceOffline(farm.device_last_seen, now);
          return (
            <tr
              key={farm.farm_id}
              className="border-b border-line-soft last:border-0 hover:bg-soft/70 transition-colors"
            >
              <td className="px-6 py-4">
                <Link
                  href={`/admin/farms/${farm.farm_id}`}
                  className="font-medium text-ink hover:text-ink transition-colors"
                >
                  {farm.farm_name}
                </Link>
              </td>
              <td className="px-6 py-4">
                <StatusBadge tone={offline ? "offline" : "online"}>
                  {offline ? "Офлайн" : "Онлайн"}
                </StatusBadge>
              </td>
              <td className="px-6 py-4 text-right tabular text-muted">
                {farm.cameras_count}
              </td>
              <td className="px-6 py-4 text-right tabular text-muted">
                {formatNumber(Number(farm.events_24h ?? 0))}
              </td>
              <td className="px-6 py-4 text-muted">
                {farm.last_event_at ? timeAgo(farm.last_event_at, now) : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
      </table>
    </div>
  );
}
