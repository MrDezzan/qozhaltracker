/** «5 минут назад» вместо сырой даты — читается быстрее при беглом взгляде. */
export function timeAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "—";
  const diffMs = now.getTime() - new Date(iso).getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 0) return "только что";
  if (diffSec < 60) return "только что";

  const minutes = Math.floor(diffSec / 60);
  if (minutes < 60) return `${minutes} ${plural(minutes, "минуту", "минуты", "минут")} назад`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${plural(hours, "час", "часа", "часов")} назад`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} ${plural(days, "день", "дня", "дней")} назад`;

  return new Date(iso).toLocaleDateString("ru-RU");
}

/** Русские окончания: 1 минуту, 2 минуты, 5 минут. */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

/** 12345 → «12 345», чтобы крупные числа читались с одного взгляда. */
export function formatNumber(n: number): string {
  return new Intl.NumberFormat("ru-RU").format(n);
}
