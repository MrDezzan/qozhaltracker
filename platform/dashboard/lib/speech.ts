/**
 * Голосовые подсказки во время записи.
 *
 * Человек стоит у загона и ведёт животное. Смотреть на экран ему некогда
 * — обе руки заняты, а глаза на животном. Голос здесь не украшение, а
 * единственный способ сказать «теперь в другую сторону» вовремя.
 *
 * Синтез — встроенный в браузер. Ничего не скачивается, интернет не
 * нужен, русский голос есть и в Android, и в iOS.
 */

/**
 * Одно и то же вслух дважды подряд — раздражает сильнее, чем молчание.
 *
 * Поэтому фраза произносится, только если она изменилась либо если
 * прошло достаточно времени, чтобы повтор воспринимался как напоминание,
 * а не как заедание.
 */
export const REPEAT_AFTER_MS = 15_000;

export type SpeechMemory = {
  said: string;
  at: number;
};

export function shouldSpeak(
  phrase: string,
  memory: SpeechMemory | null,
  now: number
): boolean {
  if (!phrase.trim()) return false;
  if (!memory) return true;
  if (memory.said !== phrase) return true;
  return now - memory.at >= REPEAT_AFTER_MS;
}

/** Есть ли в браузере синтез речи. На старых и на части встроенных — нет. */
export function speechAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/**
 * Произносит фразу, прерывая предыдущую.
 *
 * Прерывание намеренно: если животное уже показало ракурс, пока голос
 * договаривал прежнюю подсказку, дослушивать её незачем — она устарела.
 */
export function speak(phrase: string, rate = 1.0): void {
  if (!speechAvailable() || !phrase.trim()) return;

  try {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(phrase);
    utterance.lang = "ru-RU";
    utterance.rate = rate;
    window.speechSynthesis.speak(utterance);
  } catch {
    // Синтез — приятное дополнение, а не условие работы. Всё, что он
    // говорит, написано на экране теми же словами
  }
}

/** Замолчать. Нужно, когда запись закончилась или её отменили. */
export function hush(): void {
  if (!speechAvailable()) return;
  try {
    window.speechSynthesis.cancel();
  } catch {
    // см. выше
  }
}
