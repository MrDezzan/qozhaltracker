import { PLACEMENT_INFO } from "../../../lib/cameras";
import { describeGuardWindow } from "../../../lib/settings";
import { safeTimeZone, zoneOffsetLabel } from "../../../lib/time";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card, CardHeader } from "../../../components/ui/Card";
import { Page } from "../../../components/ui/Page";
import {
  DEMO_CAMERAS,
  DEMO_FARM,
  DEMO_PLACEMENT,
} from "../../../lib/demo/farm";

export const dynamic = "force-dynamic";

/**
 * Настройки хозяйства, доступные для просмотра.
 *
 * Формы сохранения здесь не выводятся: они пишут в базу, а раздел
 * показа к базе не подключён. Показать настройку и не дать её сохранить
 * честнее, чем поставить кнопку, которая отвечает ошибкой.
 */

const СРОКИ = [
  { название: "События и визиты", срок: "18 месяцев" },
  { название: "Кадры без клички", срок: "30 дней" },
  { название: "Кадры предпросмотра", срок: "7 дней" },
];

export default function DemoSettings() {
  const timeZone = safeTimeZone(DEMO_FARM.timezone);

  return (
    <Page>
      <PageHeader title="Настройки" description={DEMO_FARM.name} />

      <div className="space-y-5 sm:space-y-6">
        <div className="grid items-start gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="Охрана территории"
              description="Когда человек в кадре считается посторонним"
            />
            <div className="px-5 pb-6 sm:px-6">
              <p className="text-[length:var(--text-base)] text-ink">
                Охрана {describeGuardWindow("21:00", "06:00")}
              </p>
              <p className="mt-1.5 text-[length:var(--text-sm)] text-muted">
                Человек в кадре вне этих часов отмечается как «Внимание».
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Часовой пояс"
              description={`Сейчас ${zoneOffsetLabel(timeZone)}`}
            />
            <div className="px-5 pb-6 sm:px-6">
              <p className="text-[length:var(--text-base)] text-ink">
                Алматы, Астана, Караганда (UTC+5)
              </p>
              <p className="mt-1.5 text-[length:var(--text-sm)] text-muted">
                По этому поясу строятся все графики по часам.
              </p>
            </div>
          </Card>
        </div>

        <Card>
          <CardHeader title="Назначение камер" />
          <div className="px-5 pb-6 sm:px-6">
            <ul className="divide-y divide-line-soft rounded-[var(--radius-md)] border border-line">
              {DEMO_CAMERAS.map((камера, индекс) => {
                const место = PLACEMENT_INFO[DEMO_PLACEMENT[камера.id]];
                return (
                  <li key={камера.id} className="px-4 py-3">
                    <div className="flex items-baseline justify-between gap-4">
                      <span className="truncate text-[length:var(--text-sm)] text-ink">
                        <span className="tabular">№{индекс + 1}</span>{" "}
                        {камера.name}
                      </span>
                      <span className="shrink-0 text-[length:var(--text-sm)] text-muted">
                        {место.name}
                      </span>
                    </div>
                    <p className="mt-1 text-[length:var(--text-xs)] text-faint">
                      {место.gives}
                    </p>
                  </li>
                );
              })}
            </ul>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Хранение данных"
            description="Сроки хранения записей"
          />
          <div className="px-5 pb-6 sm:px-6">
            <ul className="divide-y divide-line-soft rounded-[var(--radius-md)] border border-line">
              {СРОКИ.map((строка) => (
                <li
                  key={строка.название}
                  className="flex items-baseline justify-between gap-4 px-4 py-3 text-[length:var(--text-sm)]"
                >
                  <span className="text-ink">{строка.название}</span>
                  <span className="shrink-0 tabular text-muted">
                    {строка.срок}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>
    </Page>
  );
}
