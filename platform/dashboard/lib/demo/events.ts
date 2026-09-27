import { EventRow } from "../formatters";
import { AlertRow, AlertKind } from "../alerts";
import { CameraSnapshot } from "../snapshots";
import {
  DEMO_ANIMALS,
  DEMO_CAMERAS,
  DEMO_FARM,
  DEMO_ZONES,
  DemoZone,
} from "./farm";

/**
 * События хозяйства за последние сутки.
 *
 * Генератор ДЕТЕРМИНИРОВАННЫЙ: на одно и то же «сейчас» получается одна
 * и та же картина. Случайные числа здесь были бы хуже, чем бесполезны —
 * при съёмке ролика график менялся бы между дублями, и склеить их стало
 * бы невозможно.
 *
 * Поэтому вместо Math.random взят простой конгруэнтный генератор с
 * постоянным зерном. Он не криптографический и не должен быть таким:
 * его задача — давать одну и ту же неровность.
 */
function случайный(зерно: number): () => number {
  let s = зерно % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

const ЧАС = 3600_000;
const МИНУТА = 60_000;

/**
 * Суточный ритм стада.
 *
 * Доля от максимума по часам местного времени. Два всплеска: утренняя и
 * вечерняя раздача корма. Ночью животные лежат, и это видно на графике
 * не хуже, чем в загоне.
 */
const РИТМ = [
  0.18, 0.14, 0.12, 0.12, 0.16, 0.34, 0.72, 0.95, 0.88, 0.62, 0.48, 0.42,
  0.4, 0.44, 0.5, 0.58, 0.74, 0.96, 0.9, 0.66, 0.44, 0.32, 0.24, 0.2,
];

/** Голов в кадре в этот час: от ритма, с небольшой неровностью. */
function головВКадре(час: number, шум: () => number): number {
  const максимум = 63;
  const доля = РИТМ[час] ?? 0.3;
  return Math.max(4, Math.round(максимум * доля + (шум() - 0.5) * 6));
}

/** Час по времени фермы для метки времени. */
function часФермы(момент: Date): number {
  const строка = момент.toLocaleString("ru-RU", {
    timeZone: DEMO_FARM.timezone,
    hour: "2-digit",
    hour12: false,
  });
  return Number(строка.slice(0, 2));
}

/**
 * Сводки подсчёта раз в минуту за сутки.
 *
 * Сутки, а не четыре часа: рядом с графиком стоит плитка «максимум за
 * сутки», и считать её по четырём часам значит показать не максимум.
 * График при этом берёт только последние часы — так же, как на живой
 * ферме.
 */
function подсчёты(now: Date): EventRow[] {
  const шум = случайный(4242);
  const события: EventRow[] = [];
  const минут = 24 * 60;

  for (let i = минут; i >= 0; i--) {
    const момент = new Date(now.getTime() - i * МИНУТА);
    события.push({
      id: `demo-count-${i}`,
      // Подсчёт идёт с камеры над загоном: только сверху видно всё
      // поголовье сразу, без перекрытий
      camera_id: "cam-3",
      animal_id: null,
      event_type: "counted",
      payload: { unique_count: головВКадре(часФермы(момент), шум) },
      occurred_at: момент.toISOString(),
    });
  }

  return события;
}

/**
 * Выходы из зон за двое суток.
 *
 * Двое, а не одни: экран сравнивает сегодняшнее время у кормушки с
 * вчерашним. На одних сутках сравнение показало бы «вчера данных не
 * было», то есть самый интересный показатель остался бы пустым.
 */
function выходыИзЗон(now: Date): EventRow[] {
  const события: EventRow[] = [];

  for (const зона of DEMO_ZONES) {
    if (зона.visits === 0) continue;
    события.push(...выходыЗоны(зона, now, 0, 1));
    // Вчера подходов было чуть больше: сегодняшнее «ниже вчерашнего»
    // должно получаться из данных, а не быть вписанным руками
    события.push(...выходыЗоны(зона, now, 1, 1.12));
  }

  return события;
}

function выходыЗоны(
  зона: DemoZone,
  now: Date,
  сутокНазад: number,
  множитель: number,
): EventRow[] {
  const шум = случайный(зона.id.length * 977 + сутокНазад * 13 + зона.visits);
  const события: EventRow[] = [];
  const всего = Math.round(зона.visits * множитель);
  const начало = now.getTime() - (сутокНазад + 1) * 24 * ЧАС;

  for (let i = 0; i < всего; i++) {
    // Подходы ставим по суточному ритму, а не равномерно: иначе на
    // графике по часам вышла бы ровная полка, чего в загоне не бывает
    const час = выбратьЧас(шум);
    const момент = new Date(начало + час * ЧАС + Math.floor(шум() * ЧАС));
    if (момент.getTime() > now.getTime()) continue;

    const длительность = Math.max(
      8,
      Math.round(зона.averageS * (0.55 + шум() * 0.9)),
    );
    const животное = DEMO_ANIMALS[Math.floor(шум() * DEMO_ANIMALS.length)];

    события.push({
      id: `demo-zone-${зона.id}-${сутокНазад}-${i}`,
      camera_id: зона.cameraId,
      animal_id: животное.id,
      event_type: "zone_exit",
      payload: {
        zone_id: зона.id,
        zone_name: зона.name,
        zone_kind: зона.kind,
        duration_s: длительность,
      },
      occurred_at: момент.toISOString(),
    });
  }

  return события;
}

/** Час суток по ритму стада: чаще утро и вечер. */
function выбратьЧас(шум: () => number): number {
  const сумма = РИТМ.reduce((a, b) => a + b, 0);
  let цель = шум() * сумма;
  for (let час = 0; час < РИТМ.length; час++) {
    цель -= РИТМ[час];
    if (цель <= 0) return час;
  }
  return 12;
}

/** Все события хозяйства: подсчёты и выходы из зон, от новых к старым. */
export function demoEvents(now: Date): EventRow[] {
  return [...подсчёты(now), ...выходыИзЗон(now)].sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at),
  );
}

/**
 * Тревоги.
 *
 * Открытая одна, и та о постороннем на въезде: это то, за что платят
 * деньги, и то, что понятно без объяснений. Рядом закрытые за сутки —
 * без них не видно, что тревоги вообще закрываются сами.
 */
export function demoAlerts(now: Date): { open: AlertRow[]; history: AlertRow[] } {
  const минут = (m: number) => new Date(now.getTime() - m * МИНУТА).toISOString();
  /*
    Вид тревоги проходит через типизированную обёртку. Без неё набор для
    показа был собран с видом «person_detected», которого в системе нет:
    название тревоги не нашлось в таблице, и на экране стояло само слово
    латиницей, рядом с русским заголовком. Теперь такую опечатку не
    пропустит компилятор.
  */
  const вид = (k: AlertKind): string => k;

  const open: AlertRow[] = [
    {
      id: "demo-alert-1",
      animal_id: null,
      camera_id: "cam-5",
      snapshot_path: null,
      kind: вид("intruder"),
      severity: "danger",
      title: "Посторонний на территории",
      detail: { persons: 1, seconds_present: 96 },
      // Поднята ДО того, как камера на въезде замолчала, и потому до сих
      // пор не закрылась: закрыть её некому, кадров с этой камеры нет.
      // Это не натяжка, а обычный порядок вещей, и лучше показать его,
      // чем молча закрыть тревогу по таймеру
      opened_at: минут(34),
      resolved_at: null,
      acknowledged_at: null,
    },
    {
      id: "demo-alert-2",
      animal_id: "a-09",
      camera_id: "cam-3",
      snapshot_path: null,
      kind: вид("low_feeding"),
      severity: "warning",
      title: "Мало подходит к корму",
      detail: {
        text: "подходов к корму 3 против обычных 9",
        days_in_row: 2,
      },
      opened_at: минут(148),
      resolved_at: null,
      acknowledged_at: null,
    },
  ];

  const history: AlertRow[] = [
    {
      id: "demo-alert-3",
      animal_id: "a-14",
      camera_id: "cam-1",
      snapshot_path: null,
      kind: вид("low_activity"),
      severity: "warning",
      title: "Двигается меньше обычного",
      detail: { text: "прошла 820 м против обычных 1900 м", days_in_row: 1 },
      opened_at: минут(20 * 60),
      resolved_at: минут(15 * 60),
      acknowledged_at: минут(19 * 60),
    },
    {
      id: "demo-alert-4",
      animal_id: null,
      camera_id: "cam-5",
      snapshot_path: null,
      kind: вид("intruder"),
      severity: "danger",
      title: "Посторонний на территории",
      detail: { persons: 2, seconds_present: 41 },
      opened_at: минут(31 * 60),
      resolved_at: минут(31 * 60 - 12),
      acknowledged_at: минут(31 * 60 - 20),
    },
    {
      id: "demo-alert-5",
      animal_id: "a-02",
      camera_id: "cam-2",
      snapshot_path: null,
      kind: вид("no_water"),
      severity: "danger",
      title: "Не подходит к воде",
      detail: { text: "подходов к поилке нет 14 часов", days_in_row: 1 },
      opened_at: минут(40 * 60),
      resolved_at: минут(38 * 60),
      acknowledged_at: минут(39 * 60),
    },
  ];

  return { open, history };
}

/**
 * Кадры камер.
 *
 * Имена файлов приходят СНАРУЖИ, из чтения папки показа, а не берутся из
 * списка камер. Список требовал `.jpg`, кадры пришли в `.png` — и
 * платформа просила четыре несуществующих адреса, рисуя в окнах значок
 * битой картинки. Разбор в `frames.ts`.
 *
 * Камера, для которой файла нет, приходит с `url: null` — и блок
 * трансляции сам покажет её строкой «кадров не поступало», без пустого
 * окна.
 */
export function demoSnapshots(
  now: Date,
  кадры: Record<string, string> = {},
): CameraSnapshot[] {
  return DEMO_CAMERAS.map((камера) => {
    const файл = кадры[камера.id];
    return {
      cameraId: камера.id,
      cameraName: камера.name,
      url: файл ? `/demo/${файл}` : null,
      liveUrl: null,
      hasStream: false,
      updatedAt:
        камера.frameAgeS === null
          ? null
          : new Date(now.getTime() - камера.frameAgeS * 1000).toISOString(),
    };
  });
}
