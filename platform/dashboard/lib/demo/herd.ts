import { AnimalRow } from "../../components/AnimalList";
import { ActivityRow } from "../activity";
import { DEMO_ANIMALS } from "./farm";

/**
 * Поголовье для экрана «Поголовье».
 *
 * Числа не взяты из головы: вес 380–520 кг и привес 0.7–1.1 кг в сутки
 * это обычный диапазон для казахской белоголовой на откорме, а
 * пройденное за сутки расстояние 1.4–3.2 км — то, что даёт стадо на
 * выгуле. Показ, где корова весит 900 кг и проходит 20 км, ломает
 * доверие к остальным цифрам на экране.
 */
function ряд(индекс: number, now: Date): AnimalRow {
  const животное = DEMO_ANIMALS[индекс];
  const шаг = (индекс * 37) % 100;

  const вес = 380 + Math.round((шаг / 100) * 140);
  const привес = 0.7 + ((индекс * 13) % 40) / 100;
  const метры = 1400 + ((индекс * 271) % 1800);

  // Одно животное из двадцати четырёх ходит меньше обычного: это и есть
  // то, ради чего систему покупают, и на экране это должно быть видно
  const проблемное = индекс === 8;
  const своя = проблемное ? 0.58 : 0.92 + ((индекс * 7) % 20) / 100;

  const активность: ActivityRow = {
    animal_id: животное.id,
    label: животное.label,
    day: now.toISOString().slice(0, 10),
    meters: проблемное ? Math.round(метры * 0.55) : метры,
    seconds_visible: 5400 + ((индекс * 97) % 3600),
    baseline_meters: метры,
    ratio_to_own: своя,
    ratio_to_herd: 0.98,
    days_known: 26 + (индекс % 9),
  };

  const виделиМинутНазад = 3 + ((индекс * 17) % 180);

  return {
    id: животное.id,
    label: животное.label,
    readiness: {
      animal_id: животное.id,
      // Двум животным ракурсов не хватает: так на экране видно, что
      // узнавание набирается постепенно, а не включается разом
      embeddings: индекс === 20 ? 4 : индекс === 21 ? 7 : 14 + (индекс % 6),
      last_recorded_at: new Date(
        now.getTime() - (2 + (индекс % 11)) * 86400_000,
      ).toISOString(),
    },
    sightings: 40 + ((индекс * 53) % 220),
    lastSeenAt: new Date(now.getTime() - виделиМинутНазад * 60_000).toISOString(),
    weightKg: вес,
    dailyGainKg: Number(привес.toFixed(2)),
    activity: активность,
  };
}

export function demoHerd(now: Date): AnimalRow[] {
  return DEMO_ANIMALS.map((_, индекс) => ряд(индекс, now));
}
