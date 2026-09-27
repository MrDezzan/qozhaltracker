/**
 * Раскладка сетки камер.
 *
 * Вынесено из компонента, потому что здесь легко ошибиться незаметно:
 * на тридцати камерах неудачная сетка даёт кадры по сто пикселей, на
 * которых не разглядеть ничего, а на одной камере — растянутую на весь
 * экран картинку с пустотой по бокам.
 */

export const VIEW_MODES = ["grid", "single"] as const;
export type ViewMode = (typeof VIEW_MODES)[number];

export const VIEW_MODE_LABEL: Record<ViewMode, string> = {
  grid: "Все камеры",
  single: "Одна камера",
};

/**
 * Сколько столбцов в сетке при данном числе камер.
 *
 * Считаем от количества, а не задаём жёстко: две камеры в сетке из
 * четырёх столбцов выглядят потерянными, а двадцать в двух столбцах
 * требуют бесконечной прокрутки.
 *
 * Потолок — четыре. Дальше кадр становится мельче спичечного коробка,
 * и сетка перестаёт быть полезной: смотреть надо по одной.
 */
export function gridColumns(cameraCount: number): number {
  if (cameraCount <= 1) return 1;
  if (cameraCount <= 4) return 2;
  if (cameraCount <= 9) return 3;
  return 4;
}

/**
 * Классы Tailwind для сетки.
 *
 * Именно готовые строки, а не сборка вида `grid-cols-${n}`: Tailwind
 * ищет имена классов в исходниках по тексту и собранное из кусков имя
 * просто не попадёт в стили. Это классическая тихая поломка — в
 * разработке работает, в сборке нет.
 */
export function gridClass(cameraCount: number): string {
  switch (gridColumns(cameraCount)) {
    case 1:
      return "grid-cols-1";
    case 2:
      return "grid-cols-1 sm:grid-cols-2";
    case 3:
      return "grid-cols-2 lg:grid-cols-3";
    default:
      return "grid-cols-2 lg:grid-cols-4";
  }
}

/** С какого количества камер сетка перестаёт быть удобной. */
export const CROWDED_FROM = 10;

export function isCrowded(cameraCount: number): boolean {
  return cameraCount >= CROWDED_FROM;
}

/**
 * Какой режим предложить по умолчанию.
 *
 * До четырёх камер сетка удобнее: видно всё сразу. Дальше кадры мельчают,
 * и полезнее одна крупная с переключением.
 */
export function defaultMode(cameraCount: number): ViewMode {
  return cameraCount > 6 ? "single" : "grid";
}

/** Следующая камера по кругу — для стрелок и автопереключения. */
export function nextIndex(current: number, total: number, step = 1): number {
  if (total <= 0) return 0;
  return (((current + step) % total) + total) % total;
}
