import { SupabaseClient } from "@supabase/supabase-js";

/**
 * Заведение животного записью с камеры.
 *
 * Прежний порядок — загрузка фотографий со всех сторон — убран. Дело не
 * только в том, что снимать каждое животное на телефон неудобно.
 * Узнавание сравнивает кадр с камеры с эталоном, и модель признаков
 * чувствительна к тому, чем и как снято: фото днём с двух метров сбоку
 * и кадр потолочной камеры ночью для неё почти не связаны. Совпадение
 * выходило слабым даже при аккуратной съёмке.
 *
 * Теперь эталон снимает сама камера. Человек вводит кличку, жмёт
 * «Записать» и проводит животное мимо камеры — эталон и рабочий кадр
 * приходят из одного источника.
 */

/**
 * Столько ракурсов показываем человеку. После них животное узнаётся, и
 * его можно уводить.
 */
export const NEEDED = 12;

/**
 * А столько набираем на самом деле, пока животное ещё в кадре.
 *
 * Узнавание тем надёжнее, чем больше разных положений записано: голова
 * опущена, животное отвернулось, отошло дальше, встало против света.
 * Показывать это число человеку незачем — он стоит и ждёт, когда можно
 * уйти, а лишние восемь ракурсов ему ничего не дают. Это подарок, а не
 * обязанность.
 */
export const TARGET = 20;

/**
 * Ракурсы, которые может показать животное.
 *
 * Названия намеренно не «левый» и «правый». Который бок левый, зависит
 * от того, как повешена камера, и система этого не знает. Она различает
 * два РАЗНЫХ бока — для узнавания важно именно это.
 */
export const VIEW_TITLES: Record<string, string> = {
  side_a: "мимо камеры",
  side_b: "в обратную сторону",
  front: "навстречу камере",
  rear: "от камеры",
};

/**
 * Единственное указание на всю запись.
 *
 * Раньше их было четыре — «мимо камеры», «в обратную сторону»,
 * «навстречу», «от камеры». Человек всё равно делает одно непрерывное
 * движение: обводит животное кругом. Разбивать это на команды значило
 * заставлять его останавливаться и ждать переключения шага.
 */
export const CIRCLE_ASK = "Проведите животное вокруг, полный круг и не спеша";

export function viewTitle(view: string): string {
  return VIEW_TITLES[view] ?? view;
}

/**
 * Сколько кадров берёт каждая камера.
 *
 * Шесть, а не двенадцать: камер две, и двадцать четыре кадра человек у
 * загона не выстоит. Шесть и шесть дают те же двенадцать, что раньше
 * набирала одна камера, но снятые с двух сторон — спина и профиль.
 * Для узнавания это лучше, чем двенадцать с одной стороны.
 *
 * Совпадает с `per_camera` в базе. Используется, только когда база это
 * число не прислала.
 */
export const PER_CAMERA = 6;

export type RecordingSession = {
  id: string;
  camera_id: string;
  /** Все камеры, отмеченные для этой записи. */
  camera_ids: string[];
  animal_id: string;
  label: string;
  captured: number;
  needed: number;
  /** Сколько набираем на самом деле. Человеку не показывается. */
  target: number;
  /** Сколько кадров нужно с каждой камеры. */
  per_camera: number;
  /** Сколько уже набрано по каждой: { "id-камеры": 7 }. */
  captured_by: Record<string, number>;
  /** Сколько кадров нужно на один ракурс. */
  per_view: number;
  /** В каком порядке просим ракурсы. Пусто — камера их не различает. */
  views_order: string[];
  views_done: string[];
  views_skipped: string[];
  /** Какой ракурс ждём прямо сейчас. */
  awaiting_view: string | null;
  /** Почему кадры сейчас не берутся. Пусто — берутся. */
  hint: string | null;
  started_at: string;
  expires_at: string;
};

export type AnimalReadiness = {
  animal_id: string;
  embeddings: number;
  last_recorded_at: string | null;
};

export async function getActiveRecording(
  client: SupabaseClient,
  farmId: string
): Promise<RecordingSession | null> {
  const { data } = await client
    .from("active_recording")
    .select("id, camera_id, camera_ids, animal_id, label, captured, needed, target, per_camera, captured_by, per_view, views_order, views_done, views_skipped, awaiting_view, hint, started_at, expires_at")
    .eq("farm_id", farmId)
    .limit(1)
    .maybeSingle();

  return (data as RecordingSession | null) ?? null;
}

export async function getReadiness(
  client: SupabaseClient,
  farmId: string
): Promise<Map<string, AnimalReadiness>> {
  const { data } = await client.rpc("animal_readiness", { target_farm_id: farmId });
  const rows = (data as AnimalReadiness[] | null) ?? [];
  return new Map(rows.map((row) => [row.animal_id, row]));
}

/**
 * Готово ли животное к узнаванию.
 *
 * Порог ниже, чем нужное для записи количество: если запись прервали на
 * восьми ракурсах, животное всё равно будет узнаваться — хуже, но будет.
 * Врать, что оно не заведено, в такой ситуации неправильно.
 */
export const MIN_TO_RECOGNISE = 4;

export type Readiness = {
  ready: boolean;
  count: number;
  line: string;
};

export function readiness(record: AnimalReadiness | undefined): Readiness {
  const count = record?.embeddings ?? 0;

  if (count === 0) {
    return {
      ready: false,
      count,
      line: "Не записано",
    };
  }

  if (count < MIN_TO_RECOGNISE) {
    return {
      ready: false,
      count,
      line: `Мало ракурсов, проведите ещё раз`,
    };
  }

  if (count < NEEDED) {
    return {
      ready: true,
      count,
      line: "Узнаётся",
    };
  }

  return { ready: true, count, line: "Узнаётся уверенно" };
}

/**
 * Проверка клички до отправки.
 *
 * Две «Зорьки» на одной ферме — это почти наверняка одно животное,
 * заведённое дважды. База такое не пропустит, но сказать об этом лучше
 * до нажатия кнопки.
 */
export function validateLabel(raw: string, existing: string[]): string {
  const label = raw.trim();
  if (!label) return "Введите кличку или номер";
  if (label.length > 60) return "Слишком длинное имя";

  const taken = existing.some((e) => e.toLowerCase() === label.toLowerCase());
  if (taken) return `«${label}» уже заведено`;

  return "";
}

/** Сколько осталось до конца сеанса. Отрицательное — время вышло. */
export function secondsLeft(session: RecordingSession, now: Date = new Date()): number {
  return Math.round((new Date(session.expires_at).getTime() - now.getTime()) / 1000);
}

/**
 * Что показывать человеку во время записи.
 *
 * Он стоит у загона с телефоном в руке. Ему нужно знать одно: вести
 * животное дальше или уже хватит.
 */
export function recordingHint(
  session: RecordingSession,
  names: Record<string, string> = {}
): string {
  // Подсказка от камеры важнее общих слов: она говорит, что именно
  // мешает прямо сейчас — далеко, темно, двое в кадре
  if (session.hint) return session.hint;

  if (session.captured === 0) {
    return `${CIRCLE_ASK}. В кадре должно быть только оно`;
  }

  // Одна камера набрала своё, другая нет. Общая полоса при этом растёт,
  // и человек уверен, что всё идёт как надо, — а провести животное надо
  // ещё раз, мимо отставшей камеры
  const waiting = cameraProgress(session, names).filter((one) => !one.done);
  const cameras = session.camera_ids?.length ?? 0;
  if (cameras > 1 && waiting.length > 0 && waiting.length < cameras) {
    return `Камере «${waiting[0].name}» не хватает кадров, проведите ещё раз`;
  }

  if (!isEnough(session)) {
    return "Ведите дальше по кругу, счётчик растёт на каждом повороте";
  }

  return "Готово. Животное записано";
}

/**
 * Готовность записи в процентах.
 *
 * Проценты, а не «3 из 12». Числа тут ничего не добавляют: человек всё
 * равно не знает, много двенадцать или мало, и что делать при семи.
 * А сто процентов понятны без объяснений.
 *
 * Обрезано по сотне: после обещанного полоса заполнена, и ждать больше
 * нечего. Продолжение записи — сверх обещанного.
 */
/**
 * Сколько кадров набирается сверх обещанного, прежде чем запись
 * закончится сама. Совпадает с потолком в базе.
 */
export const HARD_CAP_FACTOR = 2;

/**
 * Сколько кадров нужно всего, чтобы запись закончилась.
 *
 * Считается от камер, а не от общего числа: каждая набирает своё и
 * замолкает. Одна камера, стоящая удачнее, не должна набрать весь сеанс
 * сама — эталоны с верхней и боковой несопоставимы, и вторая камера без
 * своих просто не узнает животное.
 */
export function framesToFinish(session: RecordingSession): number {
  const cameras = session.camera_ids?.length ?? 0;
  const per = session.per_camera ?? PER_CAMERA;
  if (cameras > 0) return per * cameras;

  // Старая база без списка камер: сеанс одно-камерный
  return Math.max(session.target ?? 0, session.needed);
}

export function progressPercent(session: RecordingSession): number {
  const total = session.views_order?.length ?? 0;

  // Считаем от того, на чём запись действительно закончится, а не от
  // обещанного. Иначе полоса упирается в сто задолго до конца, человек
  // читает это как «готово» — и недоумевает, почему кадры всё идут
  const finishAt = framesToFinish(session);
  const byFrames =
    finishAt > 0
      ? Math.min(100, Math.round((session.captured / finishAt) * 100))
      : 100;

  if (total === 0) return byFrames;

  const closed =
    (session.views_done?.length ?? 0) + (session.views_skipped?.length ?? 0);
  const byViews = Math.min(100, Math.round((closed / total) * 100));

  // Берём большее из двух, и это не для красоты. Ракурс может не
  // определяться вовсе — животное стоит на месте, камера смотрит в лоб.
  // Тогда по ракурсам полоса стоит на нуле, хотя кадры идут десятками, и
  // человек видит намертво замерший ноль. Так и было: пятьдесят восемь
  // записанных кадров при нуле процентов.
  return Math.max(byViews, byFrames);
}

export type CameraProgress = {
  id: string;
  name: string;
  taken: number;
  needed: number;
  done: boolean;
};

/**
 * Что набрала каждая камера.
 *
 * Показывается, только когда камер больше одной. При двух это
 * единственное, что объясняет застрявшую полосу: боковая набрала своё,
 * а верхняя не видит животное — и человеку надо провести его ещё раз, а
 * не ждать.
 */
export function cameraProgress(
  session: RecordingSession,
  names: Record<string, string> = {}
): CameraProgress[] {
  const per = session.per_camera ?? PER_CAMERA;
  const by = session.captured_by ?? {};
  const ids = session.camera_ids ?? [];

  // Разбивки нет, а кадры есть — сеанс начат до того, как записи стали
  // общими на несколько камер. Камера в нём одна, и всё набранное её.
  // Без этой оговорки такой сеанс навсегда завис бы на нуле процентов
  const unsplit = Object.keys(by).length === 0 && ids.length === 1;

  return ids.map((id) => {
    const taken = unsplit ? session.captured : Number(by[id] ?? 0);
    return {
      id,
      name: names[id] ?? "Камера",
      taken: Math.min(taken, per),
      needed: per,
      done: taken >= per,
    };
  });
}

/**
 * Сколько кадров осталось на текущем шаге.
 *
 * Шаг закрывается сам, когда наберётся `per_view`. Человеку это видно
 * как «ещё 3»: понятнее, чем проценты, потому что отвечает на вопрос
 * «сколько мне ещё так стоять».
 */
export function framesLeftInStep(session: RecordingSession): number {
  if (!session.awaiting_view) return 0;
  const per = session.per_view ?? 5;
  const closed =
    (session.views_done?.length ?? 0) + (session.views_skipped?.length ?? 0);
  const inStep = Math.max(0, session.captured - closed * per);
  return Math.max(0, per - inStep);
}

export type ViewState = "done" | "skipped" | "now" | "waiting";

/** Состояние каждого ракурса — для списка на экране. */
export function viewStates(
  session: RecordingSession
): { view: string; title: string; state: ViewState }[] {
  return (session.views_order ?? []).map((view) => {
    let state: ViewState = "waiting";
    if (session.views_done?.includes(view)) state = "done";
    else if (session.views_skipped?.includes(view)) state = "skipped";
    else if (session.awaiting_view === view) state = "now";
    return { view, title: viewTitle(view), state };
  });
}

/**
 * Набрано ли всё.
 *
 * По камерам, а не по общему числу. Двадцать кадров с одной камеры и
 * ноль со второй — это не «записано»: вторая камера животное не узнает,
 * и обмер силуэта с неё ляжет ничей.
 */
export function isEnough(session: RecordingSession): boolean {
  const cameras = cameraProgress(session);
  if (cameras.length > 0) return cameras.every((camera) => camera.done);
  return session.captured >= Math.max(session.target ?? 0, session.needed);
}

/** Мешает ли что-то прямо сейчас. По этому подсказка подсвечивается. */
export function isStuck(session: RecordingSession): boolean {
  return Boolean(session.hint);
}

export type LastRecording = {
  id: string;
  label: string;
  status: "done" | "cancelled" | "expired";
  captured: number;
  needed: number;
  hint: string | null;
  finished_at: string;
};

export async function getLastRecording(
  client: SupabaseClient,
  farmId: string
): Promise<LastRecording | null> {
  const { data } = await client.rpc("last_recording", { target_farm_id: farmId });
  const rows = (data as LastRecording[] | null) ?? [];
  return rows[0] ?? null;
}

/**
 * Чем кончилась последняя запись.
 *
 * Раньше полоса записи просто исчезала со страницы, и понять, чем всё
 * кончилось, было неоткуда: набралось, отменили, время вышло — вид
 * одинаковый.
 *
 * Пустая строка — говорить не о чем.
 */
export function describeOutcome(last: LastRecording | null): string {
  if (!last) return "";

  const percent = Math.min(
    100,
    Math.round((last.captured / Math.max(1, last.needed)) * 100)
  );

  if (last.status === "done") {
    return `«${last.label}» записано. Камера теперь его узнаёт`;
  }

  if (last.status === "cancelled") {
    return last.captured === 0
      ? `Запись «${last.label}» отменена: ничего не набралось`
      : `Запись «${last.label}» остановлена на ${percent} %`;
  }

  const why = last.hint ? ` Последнее, что мешало: ${last.hint.toLowerCase()}.` : "";
  return last.captured === 0
    ? `Время записи «${last.label}» вышло, ничего не набралось.${why} Попробуйте ещё раз, встав ближе к камере`
    : `Время записи «${last.label}» вышло на ${percent} %.${why} Можно записать ещё раз, новое добавится к прежнему`;
}

/** Успешной ли была последняя запись. По этому её подсвечивают. */
export function outcomeIsGood(last: LastRecording | null): boolean {
  return last?.status === "done";
}
