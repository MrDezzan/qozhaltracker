import { getServerSupabase } from "../../../lib/supabaseServer";
import { PageHeader } from "../../../components/ui/PageHeader";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TrainingReview } from "../../../components/TrainingReview";
import {
  collectionAdvice,
  getNextFrame,
  getTrainingFrameUrl,
  getTrainingSummary,
  usableForLabelling,
} from "../../../lib/training";

export const dynamic = "force-dynamic";

export default async function TrainingPage() {
  const supabase = await getServerSupabase();

  const [frame, summary] = await Promise.all([
    getNextFrame(supabase),
    getTrainingSummary(supabase),
  ]);

  const imageUrl = frame ? await getTrainingFrameUrl(supabase, frame.path) : null;
  const collected = summary.reduce((sum, row) => sum + Number(row.total ?? 0), 0);

  return (
    <main>
      <PageHeader
        title="Отбраковка кадров"
        description="Какие кадры отдавать в разметку"
      />

      {frame ? (
        <Card className="p-5">
          <TrainingReview frame={frame} imageUrl={imageUrl} />
        </Card>
      ) : (
        <Card>
          <EmptyState
            title={collected > 0 ? "Всё разобрано" : "Кадров пока нет"}
            hint={
              collected > 0
                ? "Новые кадры появятся, пока идёт сбор на ферме."
                : "Сбор включается на ферме: TRAINING_COLLECT_UNTIL в cv-service/.env. Первые кадры придут за полчаса."
            }
          />
        </Card>
      )}

      {summary.length > 0 && (
        <Card className="mt-6 p-5">
          <h2 className="text-sm font-medium text-ink mb-3">Собрано</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="font-normal pb-2 pr-4">Ферма</th>
                  <th className="font-normal pb-2 pr-4 text-right">Всего</th>
                  <th className="font-normal pb-2 pr-4 text-right">Не смотрели</th>
                  <th className="font-normal pb-2 pr-4 text-right">С ошибками</th>
                  <th className="font-normal pb-2 pr-4 text-right">Дней</th>
                  <th className="font-normal pb-2">Что дальше</th>
                </tr>
              </thead>
              <tbody>
                {summary.map((row) => (
                  <tr key={row.farm_id} className="border-t border-line-soft">
                    <td className="py-2 pr-4 text-ink">{row.farm_name}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{row.total}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{row.pending}</td>
                    {/*
                      Главное число таблицы. `merged` и `missed` — это
                      кадры, на которых модель ошиблась, и только они
                      учат её тому, чего она не умеет. Кадров может быть
                      собрано десять тысяч, а полезных — двадцать
                    */}
                    <td className="py-2 pr-4 text-right tabular-nums font-medium text-ink">
                      {usableForLabelling(row)}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{row.days}</td>
                    <td className="py-2 text-muted">{collectionAdvice(row)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card className="mt-6 p-5">
        <h2 className="text-sm font-medium text-ink mb-3">
          Что здесь происходит
        </h2>

        <div className="text-sm text-muted space-y-3 leading-relaxed max-w-2xl">
          <p>
            Устройство на ферме отбирает кадры, где модель могла ошибиться:
            животные стоят вплотную, счётчик резко скакнул, уверенность низкая.
            Каждый четвёртый берётся обычный, без них модель разучится работать
            в лёгких условиях.
          </p>

          <p>
            Ваша задача здесь: <strong className="text-ink">только
            сказать, права модель или нет</strong>. Обводить ничего не нужно:
            это делается потом, в отдельной программе и обычно не вами. Смысл
            отбраковки в том, чтобы не платить разметчику за кадры, на которых
            всё и так правильно.
          </p>

          <p>
            Зелёная рамка: модель уверена, жёлтая: сомневалась. Смотреть надо
            не на цвет, а на то, совпадают ли рамки с животными.
          </p>

          <div>
            <p className="mb-1.5">Спорные случаи:</p>
            <ul className="space-y-1 list-disc pl-5">
              <li>
                животное видно меньше чем на треть, это не «пропустила», так и
                должно быть;
              </li>
              <li>
                одна ошибка важнее остальных: если и слиплись, и пропустила,
                отмечайте «Слиплись», это тяжелее для подсчёта;
              </li>
              <li>
                сомневаетесь, ставьте «Верно». Лишний кадр в разметке стоит денег,
                пропущенная ошибка стоит одного кадра из тысячи.
              </li>
            </ul>
          </div>

          <p className="text-muted">
            Клавиши 1–4 работают без мыши. На тысяче кадров это разница между
            получасом и половиной дня.
          </p>
        </div>
      </Card>
    </main>
  );
}
