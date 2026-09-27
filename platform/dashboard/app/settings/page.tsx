import { redirect } from "next/navigation";
import { getServerSupabase } from "../../lib/supabaseServer";
import { requireFarmId } from "../../lib/auth";
import { getTermsStatus } from "../../lib/terms";
import { getAlertSettings, getRetentionPolicy } from "../../lib/settings";
import { getFarmCameras, PLACEMENT_INFO, measuresWeight } from "../../lib/cameras";
import { PageHeader } from "../../components/ui/PageHeader";
import { Card, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import {
  GuardWindowForm,
  RetentionForm,
  TimezoneForm,
} from "../../components/FarmSettingsForms";
import { safeTimeZone, zoneOffsetLabel } from "../../lib/time";
import { Page } from "../../components/ui/Page";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const supabase = await getServerSupabase();

  let farmId: string;
  try {
    farmId = await requireFarmId(supabase);
  } catch {
    redirect("/login");
  }

  const terms = await getTermsStatus(supabase);
  if (!terms.accepted) redirect("/terms");

  const [farmResult, alertSettings, retention, cameras] = await Promise.all([
    supabase.from("farms").select("name, timezone").eq("id", farmId).single(),
    getAlertSettings(supabase, farmId),
    getRetentionPolicy(supabase, farmId),
    getFarmCameras(supabase, farmId),
  ]);

  const timeZone = safeTimeZone(farmResult.data?.timezone);
  const overheadCount = cameras.filter((c) => measuresWeight(c.placement)).length;

  return (
    <Page>
      <PageHeader
        title="Настройки"
        description={farmResult.data?.name ?? undefined}
      />

      <div className="space-y-5 sm:space-y-6">


        <div className="grid gap-5 lg:grid-cols-2 items-start">
          <Card>
            <CardHeader
              title="Охрана территории"
              description="Когда человек в кадре считается посторонним"
            />
            <GuardWindowForm settings={alertSettings} />
          </Card>

          <Card>
            <CardHeader
              title="Часовой пояс"
              description={`Сейчас ${zoneOffsetLabel(timeZone)}`}
            />
            <TimezoneForm timezone={timeZone} />
          </Card>
        </div>

        <Card>
          <CardHeader
            title="Назначение камер"
          />
          <div className="px-5 sm:px-6 pb-6">
            {cameras.length === 0 ? (
              <EmptyState
                title="Камер пока нет"
                hint="Камеры подключаем мы при установке."
              />
            ) : (
              <>
                <ul className="divide-y divide-line-soft border border-line rounded-lg">
                  {cameras.map((camera) => {
                    const info = PLACEMENT_INFO[camera.placement];
                    return (
                      <li key={camera.id} className="px-4 py-3">
                        <div className="flex items-baseline justify-between gap-4">
                          <span className="text-sm text-ink truncate">
                            {camera.name}
                          </span>
                          <span className="text-sm text-muted shrink-0">
                            {info?.name ?? "не указано"}
                          </span>
                        </div>
                        {info && (
                          <p className="text-xs text-faint mt-1 leading-relaxed">
                            {info.gives}
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {overheadCount === 0 && (
                  <p className="text-sm text-watch mt-4 leading-relaxed">
                    Вес не рассчитывается: ни одна камера не установлена над
                    животными. Обратитесь в техническую поддержку.
                  </p>
                )}
              </>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Хранение данных"
            description="Сроки хранения записей"
          />
          <RetentionForm retention={retention} />
        </Card>
      </div>
    </Page>
  );
}
