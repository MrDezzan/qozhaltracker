import { describe, expect, it } from "vitest";
import {
  LastRecording,
  MIN_TO_RECOGNISE,
  NEEDED,
  TARGET,
  PER_CAMERA,
  cameraProgress,
  framesToFinish,
  RecordingSession,
  readiness,
  recordingHint,
  secondsLeft,
  describeOutcome,
  isEnough,
  isStuck,
  outcomeIsGood,
  VIEW_TITLES,
  progressPercent,
  framesLeftInStep,
  viewStates,
  validateLabel,
} from "../lib/enrollment";

function session(over: Partial<RecordingSession> = {}): RecordingSession {
  return {
    id: "s1",
    camera_id: "c1",
    camera_ids: ["c1"],
    animal_id: "a1",
    label: "Зорька",
    captured: 0,
    needed: NEEDED,
    target: TARGET,
    per_camera: PER_CAMERA,
    captured_by: {},
    per_view: 5,
    views_order: [],
    views_done: [],
    views_skipped: [],
    awaiting_view: null,
    hint: null,
    started_at: "2026-08-19T10:00:00.000Z",
    expires_at: "2026-08-19T10:05:00.000Z",
    ...over,
  };
}

describe("готовность животного", () => {
  it("без записи говорит прямо, что узнавания не будет", () => {
    const status = readiness(undefined);
    expect(status.ready).toBe(false);
    expect(status.line).toContain("Не записано");
  });

  it("нескольких ракурсов мало", () => {
    const status = readiness({
      animal_id: "a1",
      embeddings: MIN_TO_RECOGNISE - 1,
      last_recorded_at: null,
    });
    expect(status.ready).toBe(false);
    expect(status.line).toContain("ещё раз");
  });

  it("прерванная запись всё-таки даёт узнавание", () => {
    // Врать, что животное не заведено, когда узнавание уже работает
    // хуже полного, — неправильно: человек пойдёт записывать заново
    const status = readiness({
      animal_id: "a1",
      embeddings: MIN_TO_RECOGNISE,
      last_recorded_at: null,
    });
    expect(status.ready).toBe(true);
    expect(status.line).toBe("Узнаётся");
  });

  it("полная запись описана без оговорок", () => {
    const status = readiness({
      animal_id: "a1",
      embeddings: NEEDED,
      last_recorded_at: "2026-08-19T10:00:00.000Z",
    });
    expect(status.ready).toBe(true);
    expect(status.line).toContain("уверенно");
  });
});

describe("подсказка во время записи", () => {
  it("до первого кадра просит показать животное одно", () => {
    expect(recordingHint(session())).toContain("только оно");
  });

  it("в середине объясняет, почему счётчик идёт не сразу", () => {
    // Иначе человек видит одно и то же число несколько секунд подряд и
    // решает, что сломалось, — хотя система просто ждёт нового положения
    expect(recordingHint(session({ captured: 3 }))).toContain("повороте");
  });

  it("в конце говорит, что животное записано", () => {
    const done = session({ captured: PER_CAMERA, captured_by: { c1: PER_CAMERA } });
    expect(recordingHint(done)).toContain("Готово");
  });
});

describe("время сеанса", () => {
  it("считает остаток в секундах", () => {
    const left = secondsLeft(session(), new Date("2026-08-19T10:03:00.000Z"));
    expect(left).toBe(120);
  });

  it("после срока остаток отрицательный, а не ноль", () => {
    const left = secondsLeft(session(), new Date("2026-08-19T10:07:00.000Z"));
    expect(left).toBeLessThan(0);
  });
});

describe("проверка клички", () => {
  it("пустая не проходит", () => {
    expect(validateLabel("  ", [])).not.toBe("");
  });

  it("занятая не проходит независимо от регистра", () => {
    expect(validateLabel("зорька", ["Зорька"])).toContain("уже заведено");
  });

  it("свободная проходит", () => {
    expect(validateLabel("Ночка", ["Зорька"])).toBe("");
  });
});

describe("подсказка от камеры", () => {
  it("важнее общих слов", () => {
    // Она говорит, что мешает прямо сейчас, а не что бывает вообще
    const text = recordingHint(session({ captured: 3, hint: "слишком далеко" }));
    expect(text).toBe("слишком далеко");
  });

  it("её отсутствие не считается помехой", () => {
    expect(isStuck(session({ captured: 3 }))).toBe(false);
    expect(isStuck(session({ hint: "никого не вижу" }))).toBe(true);
  });
});

describe("итог последней записи", () => {
  function last(over: Partial<LastRecording> = {}): LastRecording {
    return {
      id: "s1",
      label: "Зорька",
      status: "expired",
      captured: 0,
      needed: NEEDED,
      hint: null,
      finished_at: "2026-08-19T10:05:00.000Z",
      ...over,
    };
  }

  it("без записей молчит", () => {
    expect(describeOutcome(null)).toBe("");
  });

  it("удачная запись сказана прямо", () => {
    const text = describeOutcome(last({ status: "done", captured: 12 }));
    expect(text).toContain("узнаёт");
    expect(outcomeIsGood(last({ status: "done" }))).toBe(true);
  });

  it("истёкшее время объясняется, а не исчезает", () => {
    // Раньше полоса записи просто пропадала со страницы, и понять,
    // чем всё кончилось, было неоткуда
    const text = describeOutcome(last());
    expect(text).toContain("Время");
    expect(text).toContain("ещё раз");
    expect(outcomeIsGood(last())).toBe(false);
  });

  it("последняя помеха попадает в объяснение", () => {
    const text = describeOutcome(last({ hint: "Слишком далеко" }));
    expect(text).toContain("слишком далеко");
  });

  it("прерванная на середине показывает процент, а не число кадров", () => {
    const text = describeOutcome(last({ status: "cancelled", captured: 6 }));
    expect(text).toContain("50 %");
  });
});

describe("показываем меньше, чем записываем", () => {
  it("на самом деле набираем больше обещанного", () => {
    // Узнавание тем надёжнее, чем больше положений записано. Но
    // человеку это ждать незачем: он стоит и хочет уйти
    expect(TARGET).toBeGreaterThan(NEEDED);
  });

  it("полоса не переполняется", () => {
    expect(progressPercent(session({ captured: PER_CAMERA + 5 }))).toBe(100);
  });

  it("растёт пропорционально", () => {
    expect(progressPercent(session({ captured: PER_CAMERA / 4 }))).toBe(25);
    expect(progressPercent(session({ captured: 0 }))).toBe(0);
  });

  it("«готово» говорится только когда кадры правда кончились", () => {
    // Раньше сто процентов показывались на двенадцати кадрах, а запись
    // шла до сорока. Человек читал «готово» и не понимал, почему
    // счётчик продолжает расти
    expect(isEnough(session({ captured: PER_CAMERA - 1 }))).toBe(false);
    expect(recordingHint(session({ captured: PER_CAMERA - 1 }))).toContain("дальше");

    const done = session({ captured: PER_CAMERA, captured_by: { c1: PER_CAMERA } });
    expect(isEnough(done)).toBe(true);
    expect(recordingHint(done)).toContain("записано");
  });

  it("полоса доходит до ста ровно к концу записи", () => {
    expect(progressPercent(session({ captured: PER_CAMERA / 2 }))).toBe(50);
    expect(progressPercent(session({ captured: PER_CAMERA }))).toBe(100);
  });

  it("до обещанного уводить рано", () => {
    // Считаем от того, на чём запись кончится, а не от прежних
    // двенадцати: с двумя камерами их набирают вдвоём, по шесть
    expect(isEnough(session({ captured: PER_CAMERA - 1 }))).toBe(false);
  });
});

describe("ракурсы", () => {
  function withViews(over: Partial<RecordingSession> = {}): RecordingSession {
    return session({
      views_order: ["side_a", "side_b", "front", "rear"],
      ...over,
    });
  }

  it("названия не говорят про лево и право", () => {
    // Который бок левый, зависит от того, как повешена камера. Система
    // не должна утверждать то, чего не знает
    const joined = Object.values(VIEW_TITLES).join(" ").toLowerCase();
    expect(joined).not.toContain("лев");
    expect(joined).not.toContain("прав");
  });

  it("проценты считаются по ракурсам, а не по кадрам", () => {
    // Человеку важно, сколько осталось ПОКАЗАТЬ, а не сколько кадров
    // набрано: кадры он всё равно не считает
    const half = withViews({ views_done: ["side_a", "side_b"], captured: 3 });
    expect(progressPercent(half)).toBe(50);
  });

  it("полоса не стоит на нуле, когда ракурс не определяется", () => {
    // Так и было вживую: человек сидел перед ноутбуком, вбок не ходил,
    // ракурс не определялся ни разу. Кадров набралось пятьдесят восемь,
    // а полоса показывала ноль — и конца не предвиделось
    const stuck = withViews({ captured: 20, views_done: [], awaiting_view: "side_a" });
    expect(progressPercent(stuck)).toBeGreaterThan(0);
  });

  it("видно, сколько кадров осталось на шаге", () => {
    // «Ещё 3» отвечает на вопрос, который человек себе и задаёт:
    // сколько мне ещё так стоять
    const row = withViews({ captured: 2, awaiting_view: "side_a", per_view: 5 });
    expect(framesLeftInStep(row)).toBe(3);
  });

  it("на втором шаге отсчёт начинается заново", () => {
    // Иначе «осталось» уходило бы в минус: кадры первого шага не должны
    // засчитываться во второй
    const row = withViews({
      captured: 7,
      views_done: ["side_a"],
      awaiting_view: "side_b",
      per_view: 5,
    });
    expect(framesLeftInStep(row)).toBe(3);
  });

  it("когда шагов не осталось, считать нечего", () => {
    const done = withViews({
      captured: 20,
      views_done: ["side_a", "side_b", "front", "rear"],
      awaiting_view: null,
    });
    expect(framesLeftInStep(done)).toBe(0);
  });

  it("пропущенный ракурс считается закрытым", () => {
    // Иначе полоса никогда не дойдёт до конца, и человек будет ждать
    // того, чего система уже не просит
    const row = withViews({ views_done: ["side_a"], views_skipped: ["side_b"] });
    expect(progressPercent(row)).toBe(50);
  });

  it("ракурсы не решают, закончена ли запись", () => {
    // Решают камеры. Все четыре ракурса, набранные боковой камерой, не
    // делают животное узнаваемым для верхней: там видна спина, и своих
    // эталонов у неё по-прежнему нет
    const allViews = withViews({
      views_done: ["side_a", "side_b", "front"],
      views_skipped: ["rear"],
      captured: 4,
    });
    expect(isEnough(allViews)).toBe(false);
  });

  it("камера без ракурсов считает по кадрам", () => {
    expect(progressPercent(session({ captured: PER_CAMERA / 2 }))).toBe(50);
  });

  it("указание одно на всю запись — круг", () => {
    // Четыре команды заставляли человека останавливаться и ждать
    // переключения шага, хотя движение у него одно непрерывное
    expect(recordingHint(session())).toContain("круг");
  });

  it("помеха важнее указания", () => {
    // «Слишком далеко» надо услышать раньше: пока далеко, ничего не
    // запишется, сколько ни води
    const row = session({ hint: "Слишком далеко" });
    expect(recordingHint(row)).toBe("Слишком далеко");
  });

  it("состояния ракурсов раскладываются для списка", () => {
    const row = withViews({
      views_done: ["side_a"],
      views_skipped: ["rear"],
      awaiting_view: "side_b",
    });
    const states = viewStates(row);
    expect(states.map((s) => s.state)).toEqual([
      "done",
      "now",
      "waiting",
      "skipped",
    ]);
  });
});

describe("запись с нескольких камер", () => {
  function twoCameras(over: Partial<RecordingSession> = {}): RecordingSession {
    return session({ camera_ids: ["верх", "бок"], ...over });
  }

  const names = { верх: "Проход сверху", бок: "Проход сбоку" };

  it("считает до конца по всем камерам, а не по одной", () => {
    expect(framesToFinish(twoCameras())).toBe(PER_CAMERA * 2);
    expect(framesToFinish(session())).toBe(PER_CAMERA);
  });

  it("полная одна камера не делает запись готовой", () => {
    // Главное здесь. Двенадцать кадров сбоку и ноль сверху — это не
    // «записано»: верхняя камера животное не узнает, а обмер силуэта
    // берётся только с неё и ляжет ничей
    const half = twoCameras({
      captured: PER_CAMERA,
      captured_by: { бок: PER_CAMERA },
    });
    expect(isEnough(half)).toBe(false);
    expect(progressPercent(half)).toBe(50);
  });

  it("готово, когда набрали обе", () => {
    const done = twoCameras({
      captured: PER_CAMERA * 2,
      captured_by: { верх: PER_CAMERA, бок: PER_CAMERA },
    });
    expect(isEnough(done)).toBe(true);
    expect(progressPercent(done)).toBe(100);
  });

  it("называет отставшую камеру, а не просит вести дальше", () => {
    // «Ведите дальше по кругу» здесь врёт: боковая своё набрала, и
    // сколько ни води мимо неё, счётчик не сдвинется
    const half = twoCameras({
      captured: PER_CAMERA,
      captured_by: { бок: PER_CAMERA },
    });
    expect(recordingHint(half, names)).toContain("Проход сверху");
  });

  it("пока обе отстают, просит просто вести дальше", () => {
    // Называть камеру рано: не набрала ни одна, и виновата не камера,
    // а то, что животное только пошло
    const early = twoCameras({ captured: 4, captured_by: { верх: 2, бок: 2 } });
    expect(recordingHint(early, names)).toContain("дальше");
  });

  it("разбивка показывает, кому чего не хватает", () => {
    const half = twoCameras({
      captured: PER_CAMERA + 3,
      captured_by: { бок: PER_CAMERA, верх: 3 },
    });
    const rows = cameraProgress(half, names);
    expect(rows.map((r) => r.name)).toEqual(["Проход сверху", "Проход сбоку"]);
    expect(rows.find((r) => r.id === "верх")?.done).toBe(false);
    expect(rows.find((r) => r.id === "бок")?.done).toBe(true);
  });

  it("перебор одной камеры не показывается сверх её доли", () => {
    // Иначе «14/12» читается как ошибка счёта
    const over = twoCameras({ captured_by: { бок: PER_CAMERA + 2 } });
    expect(cameraProgress(over).find((r) => r.id === "бок")?.taken).toBe(
      PER_CAMERA
    );
  });

  it("старый сеанс без разбивки не виснет на нуле", () => {
    // Запись, начатая до того, как сеансы стали общими на несколько
    // камер: разбивки нет, но кадры есть, и камера в нём одна
    const old = session({ captured: PER_CAMERA, captured_by: {} });
    expect(progressPercent(old)).toBe(100);
    expect(isEnough(old)).toBe(true);
  });

  it("две камеры без разбивки не засчитываются обе", () => {
    // Здесь угадывать нельзя: кто из двух набрал эти кадры, неизвестно,
    // и записать их обеим значило бы объявить готовой камеру, у которой
    // нет ни одного эталона
    const unknown = twoCameras({ captured: PER_CAMERA, captured_by: {} });
    expect(isEnough(unknown)).toBe(false);
  });
});
