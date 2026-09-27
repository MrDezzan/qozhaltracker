import Link from "next/link";
import { getServerSupabase } from "../../lib/supabaseServer";
import { getFarmOverview } from "../../lib/adminData";
import { isDeviceOffline } from "../../lib/adminGuard";
import { FarmsTable } from "../../components/FarmsTable";
import { PageHeader } from "../../components/ui/PageHeader";
import { StatTile } from "../../components/ui/StatTile";
import { Card } from "../../components/ui/Card";
import { Button } from "../../components/ui/Button";
import { formatNumber, plural } from "../../lib/format";

export const dynamic = "force-dynamic";

export default async function AdminHomePage() {
  const supabase = await getServerSupabase();
  const farms = await getFarmOverview(supabase);
  const now = new Date();

  const offlineFarms = farms.filter((f) => isDeviceOffline(f.device_last_seen, now));
  const totalCameras = farms.reduce((sum, f) => sum + Number(f.cameras_count ?? 0), 0);
  const totalEvents = farms.reduce((sum, f) => sum + Number(f.events_24h ?? 0), 0);

  return (
    <main>
      <PageHeader
        title="Фермы"
        description="Состояние подключённых хозяйств"
        action={
          <Link href="/admin/farms/new">
            <Button>Создать ферму</Button>
          </Link>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile label="Ферм подключено" value={farms.length} />
        <StatTile
          label="На связи"
          value={`${farms.length - offlineFarms.length} из ${farms.length}`}
          hint={
            offlineFarms.length > 0
              ? `${offlineFarms.length} не ${plural(offlineFarms.length, "отвечает", "отвечают", "отвечают")}`
              : "все в порядке"
          }
        />
        <StatTile label="Камер всего" value={totalCameras} />
        <StatTile label="Событий за сутки" value={formatNumber(totalEvents)} />
      </div>

      {offlineFarms.length > 0 && (
        <div className="mb-6 rounded-xl border border-line bg-surface px-5 py-4">
          <div className="flex gap-3">
            <span
              aria-hidden
              className="mt-1.5 inline-block w-1.5 h-1.5 rounded-full bg-watch shrink-0"
            />
            <div>
              <p className="text-sm font-medium text-ink">
                {offlineFarms.length}{" "}
                {plural(offlineFarms.length, "ферма", "фермы", "ферм")} не выходит на связь
              </p>
              <p className="text-sm text-muted mt-1">
                {offlineFarms.map((f) => f.farm_name).join(", ")}. Проверьте питание мини-ПК
                и интернет на месте.
              </p>
            </div>
          </div>
        </div>
      )}

      <Card>
        <FarmsTable farms={farms} now={now} />
      </Card>
    </main>
  );
}
