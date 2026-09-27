import { SupabaseClient } from "@supabase/supabase-js";

export type Severity = "info" | "warning" | "danger";

export type AlertRow = {
  id: string;
  animal_id: string | null;
  camera_id: string | null;
  /** Снимок к тревоге. Есть только у тревог о посторонних. */
  snapshot_path?: string | null;
  kind: string;
  severity: Severity;
  title: string;
  detail: Record<string, unknown>;
  opened_at: string;
  resolved_at: string | null;
  acknowledged_at: string | null;
};

export const SEVERITY_ORDER: Record<Severity, number> = {
  danger: 0,
  warning: 1,
  info: 2,
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  danger: "Срочно",
  warning: "Внимание",
  info: "К сведению",
};

/**
 * Что означает каждый вид тревоги и что с ним делать.
 *
 * Тревога без подсказки бесполезна: название вида ничего не говорит
 * человеку, который в шесть утра смотрит в телефон. Нужно сразу писать,
 * что пойти проверить.
 *
 * Вид пока один. Здоровье стада раньше поднимало тревоги по показаниям
 * носимых датчиков — от них отказались: их цена растёт с каждой головой,
 * а камеры уже стоят. Тревоги по здоровью вернутся, когда камеры научатся
 * давать активность и хромоту.
 */
const KIND_INFO: Record<string, { name: string; advice: string }> = {
  intruder: {
    name: "Посторонний на территории",
    advice:
      "Посмотреть снимок и живую камеру. Если это свой, отметьте тревогу просмотренной " +
      "и поправьте охранное окно в настройках, чтобы не будило зря.",
  },

  low_activity: {
    name: "Двигается меньше обычного",
    advice:
      "Посмотрите, встаёт ли животное и как оно ступает. Хромота на этом сроке " +
      "видна глазом, а системе она пока недоступна.",
  },
  low_feeding: {
    name: "Мало подходит к корму",
    advice:
      "Посмотрите, ест ли животное вообще. Проверьте, нет ли слюны, запаха изо рта " +
      "и не отгоняют ли его от кормушки соседи.",
  },
  low_both: {
    name: "Мало ест и мало двигается",
    advice:
      "Два признака сразу: это уже повод позвать ветврача, а не понаблюдать ещё день. " +
      "По отдельности каждый может быть погодой, вместе почти никогда.",
  },
  not_seen: {
    name: "Не видели в кадре",
    advice:
      "Сначала проверьте, в загоне ли животное: могло уйти, застрять или лечь вне " +
      "обзора. Если оно на месте, камера его не узнаёт: допишите ракурсы в карточке.",
  },
  no_water: {
    name: "Не подходит к воде",
    advice:
      "Проверьте поилку: не перекрыта ли, есть ли давление, не замёрзла ли. Сутки без " +
      "воды опаснее суток без корма.",
  },
  heat: {
    name: "Двигается больше обычного",
    advice:
      "Это не болезнь. У коров так бывает в охоте: посмотрите, нет ли других признаков, " +
      "и решите про осеменение.",
  },
  herd_low: {
    name: "Стадо двигается меньше обычного",
    advice:
      "Проверять надо загон, а не отдельных животных: воду, вентиляцию и корм. " +
      "Личные тревоги за этот день не поднимались: просело сразу у многих.",
  },
};

/**
 * Виды тревог, которые система умеет поднимать.
 *
 * Выведены из самой таблицы, а не переписаны рядом с ней: второй
 * перечень видов разошёлся бы с первым. Пригодилось сразу — набор
 * данных для показа платформы был собран с видом «person_detected»,
 * которого в системе нет, и на экране вместо названия тревоги стояло
 * это слово латиницей.
 */
export const ALERT_KINDS = Object.keys(KIND_INFO) as Array<keyof typeof KIND_INFO>;
export type AlertKind = (typeof ALERT_KINDS)[number];

/** Виды тревог, которые говорят о здоровье животного. */
const HEALTH_KINDS = new Set([
  "low_activity",
  "low_feeding",
  "low_both",
  "not_seen",
  "no_water",
  "herd_low",
]);

/**
 * Тревога о здоровье или нет.
 *
 * Охота сюда намеренно НЕ входит, хотя считается той же машинкой.
 * Высокая активность — подсказка осеменатору, а не болезнь. Смешать их
 * значит звать ветврача к здоровой корове ровно в тот день, когда её
 * надо осеменять.
 */
export function isHealthAlert(kind: string): boolean {
  return HEALTH_KINDS.has(kind);
}

export function alertName(kind: string): string {
  return KIND_INFO[kind]?.name ?? kind;
}

export function alertAdvice(kind: string): string {
  return KIND_INFO[kind]?.advice ?? "";
}

export function isSecurityAlert(kind: string): boolean {
  return kind === "intruder";
}

/**
 * Одна строка с сутью: цифры, из-за которых тревога поднялась.
 *
 * Числа обязательны. Вердикт без них нечем проверить, и первое же
 * несогласие человека с системой кончается тем, что он ей не верит:
 * «двигается меньше обычного» — это мнение, «прошла 100 м при обычных
 * 600» — повод пойти посмотреть.
 */
export function describeAlert(alert: AlertRow): string {
  if (alert.kind === "intruder") {
    const persons = Number(alert.detail?.persons ?? 0);
    const seconds = Number(alert.detail?.seconds_present ?? 0);
    const who = persons > 1 ? `людей в кадре: ${persons}` : "человек в кадре";
    return `${who}, держится ${Math.round(seconds)} с`;
  }

  if (alert.kind === "herd_low") {
    const share = Number(alert.detail?.value ?? 0);
    return `ниже своей нормы ${Math.round(share * 100)} % животных`;
  }

  if (isHealthAlert(alert.kind) || alert.kind === "heat") {
    // Объяснение приходит от устройства: там известны и числа, и то,
    // какое из них главное для этого вида
    const text = String(alert.detail?.text ?? "").trim();
    const days = Number(alert.detail?.days_in_row ?? 0);
    const streak = days >= 2 ? ` ${days}-й день подряд.` : "";
    return text ? `${text}.${streak}`.replace("..", ".") : streak.trim();
  }

  return "";
}

export function sortAlerts(alerts: AlertRow[]): AlertRow[] {
  return [...alerts].sort((a, b) => {
    const bySeverity = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];
    if (bySeverity !== 0) return bySeverity;
    // Непросмотренные выше просмотренных: подтверждённое хозяин уже видел
    const ackA = a.acknowledged_at ? 1 : 0;
    const ackB = b.acknowledged_at ? 1 : 0;
    if (ackA !== ackB) return ackA - ackB;
    return b.opened_at.localeCompare(a.opened_at);
  });
}

export function countBySeverity(alerts: AlertRow[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { danger: 0, warning: 0, info: 0 };
  for (const alert of alerts) counts[alert.severity] += 1;
  return counts;
}

export async function getOpenAlerts(
  client: SupabaseClient,
  farmId: string
): Promise<AlertRow[]> {
  const { data, error } = await client
    .from("alerts")
    .select(
      "id, animal_id, camera_id, snapshot_path, kind, severity, title, detail, opened_at, resolved_at, acknowledged_at"
    )
    .eq("farm_id", farmId)
    .is("resolved_at", null)
    .order("opened_at", { ascending: false })
    .limit(100);

  if (error) throw new Error(`Не удалось загрузить тревоги: ${error.message}`);
  return sortAlerts((data as AlertRow[]) ?? []);
}

export async function getRecentAlertHistory(
  client: SupabaseClient,
  farmId: string,
  limit = 50
): Promise<AlertRow[]> {
  const { data } = await client
    .from("alerts")
    .select(
      "id, animal_id, camera_id, snapshot_path, kind, severity, title, detail, opened_at, resolved_at, acknowledged_at"
    )
    .eq("farm_id", farmId)
    .not("resolved_at", "is", null)
    .order("opened_at", { ascending: false })
    .limit(limit);

  return (data as AlertRow[]) ?? [];
}

