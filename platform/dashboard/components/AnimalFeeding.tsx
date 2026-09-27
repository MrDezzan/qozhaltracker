import {
  describeGrowth,
  describeMeals,
  missedFeedingStreak,
  type AnimalDay,
  type WeekChange,
} from "../lib/animalDaily";

/**
 * Кормление и рост животного по дням.
 *
 * Столбики рисуются рамками, без библиотеки графиков: одна зависимость
 * ради одной картинки не окупается, а на телефоне такой график ещё и
 * читается хуже.
 */
export function AnimalFeeding({
  rows,
  change,
}: {
  rows: AnimalDay[];
  change: WeekChange | null;
}) {
  const missed = missedFeedingStreak(rows);
  const maxMeals = Math.max(1, ...rows.map((r) => r.feeder_visits));
  // Последние две недели: месяц столбиков на телефоне не читается
  const shown = rows.slice(-14);

  return (
    <div className="p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
        <h2 className="text-base font-medium text-ink">Кормление и рост</h2>
        {missed > 0 && (
          <span className="text-sm text-trouble">
            {missed === 1
              ? "вчера не подходил к корму"
              : `не подходит к корму ${missed} дн.`}
          </span>
        )}
      </div>

      <div className="grid sm:grid-cols-2 gap-4 mb-5">
        <div className="rounded-xl border border-line px-4 py-3">
          <div className="text-sm text-muted">Подходы к корму</div>
          <div className="text-sm text-ink mt-1">{describeMeals(change)}</div>
        </div>
        <div className="rounded-xl border border-line px-4 py-3">
          <div className="text-sm text-muted">Размер силуэта</div>
          <div className="text-sm text-ink mt-1">{describeGrowth(change)}</div>
        </div>
      </div>

      {shown.length > 0 && (
        <>
          <div className="flex items-end gap-1 h-24">
            {shown.map((row) => {
              const height = Math.round((row.feeder_visits / maxMeals) * 100);
              const empty = row.feeder_visits === 0;
              return (
                <div
                  key={row.day}
                  className="flex-1 flex flex-col justify-end h-full"
                  title={`${row.day}: ${row.feeder_visits} подходов, ${Math.round(row.feeder_seconds / 60)} мин у корма`}
                >
                  {/*
                    День без подходов рисуется тонкой красной чертой, а не
                    пустотой. Пустое место читается как «нет данных», а это
                    ровно то, о чём система обязана сказать
                  */}
                  <div
                    className={
                      empty
                        ? "w-full rounded-sm bg-trouble"
                        : "w-full rounded-sm bg-calm"
                    }
                    style={{ height: empty ? "3px" : `${Math.max(height, 6)}%` }}
                  />
                </div>
              );
            })}
          </div>

          <div className="flex justify-between text-xs text-faint mt-1.5">
            <span>{formatDay(shown[0].day)}</span>
            <span>подходов к корму за день</span>
            <span>{formatDay(shown[shown.length - 1].day)}</span>
          </div>
        </>
      )}

      <p className="text-xs text-faint mt-4 leading-relaxed">
        Рост показан в процентах от размера силуэта, а не в килограммах:
        вес в килограммах считается по формуле, которую подбирают по
        контрольным взвешиваниям. Пока их нет, проценты — единственное
        честное число.
      </p>
    </div>
  );
}

function formatDay(day: string): string {
  const date = new Date(day);
  return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}
