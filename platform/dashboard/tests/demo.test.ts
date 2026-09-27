import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { demoAlerts, demoEvents, demoSnapshots } from "../lib/demo/events";
import { demoHerd } from "../lib/demo/herd";
import {
  DEMO_CAMERAS,
  DEMO_ZONES,
  DEMO_FARM,
  DEMO_PLACEMENT,
} from "../lib/demo/farm";
import { measuresWeight } from "../lib/cameras";
import { подобратьКадры } from "../lib/demo/frames";
import { bucketHeadcountByMinute } from "../lib/formatters";
import { summariseZoneVisits } from "../lib/feeding";
import {
  activityByHour,
  assessFarmCondition,
  compareWithPreviousDay,
} from "../lib/analytics";
import { NAV, withBase, shouldHide } from "../components/ui/TopNav";
import { ALERT_KINDS, alertName, describeAlert } from "../lib/alerts";

/**
 * РАЗДЕЛ ПОКАЗА
 *
 * Его смотрят люди, которые видят платформу первый и единственный раз, и
 * ошибка там стоит дороже ошибки в рабочем разделе: рабочий покажут ещё
 * сто раз, а этот один.
 *
 * Отсюда требования, каждое из которых уже однажды ломалось в похожих
 * показах у других:
 *
 * 1. Данные считаются настоящим кодом, а не вписаны в разметку. Иначе
 *    показ расходится с продуктом на второй правке.
 * 2. Числа устойчивы: на одно и то же «сейчас» одна и та же картина.
 *    Иначе дубли при съёмке ролика не склеить.
 * 3. Ничего не выдаёт, что это показ. Ни слова «демо» на экране.
 * 4. Каждый раздел в полосе существует. Нажатие в пустоту на защите
 *    выглядит хуже отсутствующего раздела.
 */

const now = new Date("2026-09-27T14:30:00.000Z");

describe("Данные показа устойчивы", () => {
  it("на одно и то же время получается одна и та же картина", () => {
    // Случайные числа сделали бы ролик несклеиваемым: график менялся бы
    // между дублями
    const первый = demoEvents(now);
    const второй = demoEvents(now);
    expect(второй.length).toBe(первый.length);
    expect(второй.map((e) => e.id).join()).toBe(первый.map((e) => e.id).join());
    expect(второй.map((e) => JSON.stringify(e.payload)).join()).toBe(
      первый.map((e) => JSON.stringify(e.payload)).join(),
    );
  });

  it("события отдаются от новых к старым", () => {
    const события = demoEvents(now);
    const даты = события.map((e) => e.occurred_at);
    expect([...даты].sort((a, b) => b.localeCompare(a))).toEqual(даты);
  });

  it("ни одно событие не из будущего", () => {
    // Событие, помеченное будущим, даёт на экране «через 3 часа назад»
    for (const событие of demoEvents(now)) {
      expect(new Date(событие.occurred_at).getTime()).toBeLessThanOrEqual(
        now.getTime(),
      );
    }
  });
});

describe("Числа на экране считает настоящий код", () => {
  const события = demoEvents(now);

  it("поголовье в кадре правдоподобно", () => {
    const точки = bucketHeadcountByMinute([...события].reverse());
    expect(точки.length).toBeGreaterThan(200);
    const последняя = точки[точки.length - 1];
    expect(последняя.count).toBeGreaterThan(0);
    // В кадр не может попасть больше, чем есть на ферме
    for (const точка of точки) {
      expect(точка.count).toBeLessThanOrEqual(DEMO_FARM.herd);
    }
  });

  it("сводка по зонам собирается по всем заданным зонам с подходами", () => {
    const сводка = summariseZoneVisits(события);
    const сПодходами = DEMO_ZONES.filter((z) => z.visits > 0).length;
    expect(сводка.length).toBe(сПодходами);
    for (const зона of сводка) {
      expect(зона.visits).toBeGreaterThan(0);
      expect(зона.averageSeconds).toBeGreaterThan(0);
    }
  });

  it("сравнение с вчера получается из данных, а не вписано", () => {
    // Позавчерашних суток в наборе нет нарочно: сравнение должно
    // опираться на настоящие события, иначе показатель пустой
    const сравнение = compareWithPreviousDay(события, now);
    expect(сравнение.previous).toBeGreaterThan(0);
    expect(сравнение.changePercent).not.toBeNull();
  });

  it("в суточном ритме есть утренний и вечерний всплеск", () => {
    // Ровная полка по часам выдаёт придуманные данные с первого взгляда
    const часы = activityByHour(события, DEMO_FARM.timezone);
    const максимум = Math.max(...часы.map((ч) => ч.visits));
    const минимум = Math.min(...часы.map((ч) => ч.visits));
    expect(максимум).toBeGreaterThan(минимум * 2);
  });

  it("состояние фермы считается той же функцией, что на живой ферме", () => {
    const сравнение = compareWithPreviousDay(события, now);
    const состояние = assessFarmCondition({
      deviceOnline: true,
      camerasCount: DEMO_CAMERAS.length,
      zonesConfigured: DEMO_ZONES.length > 0,
      eventsToday: события.length,
      feeding: сравнение,
    });
    expect(состояние.score).toBeGreaterThanOrEqual(85);
    expect(состояние.reasons).toEqual([]);
  });
});

describe("Расстановка камер не противоречит показанным числам", () => {
  it("у каждой камеры известно, где она стоит", () => {
    for (const камера of DEMO_CAMERAS) {
      expect(DEMO_PLACEMENT[камера.id]).toBeDefined();
    }
  });

  it("зон кормления нет на камерах сверху", () => {
    /*
      docs/KAMERA_NA_KORMUSHKU.md: трекер считает животное в зоне по
      нижней точке силуэта, и сверху эта точка приходится на зад
      животного, метра на полтора позади морды. Корова, стоящая у
      кормушки и не евшая, засчитывалась бы как евшая. «Время у корма»
      превращается в «время рядом с кормушкой», а это другая величина.
    */
    const неверные = DEMO_ZONES.filter(
      (зона) =>
        зона.kind === "feeder" && DEMO_PLACEMENT[зона.cameraId] === "overhead",
    );
    expect(неверные.map((з) => з.name)).toEqual([]);
  });

  it("есть камера над животными, иначе вес считать нечем", () => {
    // На экране поголовья показана точность веса, а на экране настроек
    // написано, что вес снимается только с камеры над животными. Без
    // такой камеры одно противоречило бы другому
    const сверху = DEMO_CAMERAS.filter((к) =>
      measuresWeight(DEMO_PLACEMENT[к.id]),
    );
    expect(сверху.length).toBeGreaterThanOrEqual(1);
  });

  it("подсчёт голов идёт с камеры над загоном", () => {
    // Только сверху видно всё поголовье сразу, без перекрытий
    const подсчёты = demoEvents(now).filter((e) => e.event_type === "counted");
    expect(подсчёты.length).toBeGreaterThan(0);
    for (const событие of подсчёты) {
      expect(DEMO_PLACEMENT[событие.camera_id]).toBe("overhead");
    }
  });

  it("охрана периметра стоит на камере общего обзора", () => {
    const периметр = DEMO_ZONES.filter((з) => з.kind === "perimeter");
    expect(периметр.length).toBeGreaterThan(0);
    for (const зона of периметр) {
      expect(DEMO_PLACEMENT[зона.cameraId]).toBe("wide");
    }
  });
});

describe("Кадры берутся из папки, а не из списка с расширением", () => {
  /*
    Сначала имена файлов были записаны в данных как «cam-1.jpg». Кадры
    пришли в png, и платформа просила у браузера четыре несуществующих
    адреса: в окнах появлялся значок битой картинки — ровно то, от чего
    мы уходили, убирая пустые окна. Теперь расширение ищется в папке.
  */
  const png = ["cam-1.png", "cam-2.png", "cam-3.png", "cam-4.png", "ЧИТАТЬ.txt"];

  it("png подходит так же, как jpg", () => {
    const найдено = подобратьКадры(png);
    expect(Object.keys(найдено).sort()).toEqual(["cam-1", "cam-2", "cam-3", "cam-4"]);
    expect(найдено["cam-1"]).toBe("cam-1.png");
  });

  it("jpg, webp и верхний регистр тоже подходят", () => {
    const найдено = подобратьКадры(["cam-1.JPG", "cam-2.webp", "CAM-3.PNG"]);
    expect(найдено["cam-1"]).toBe("cam-1.JPG");
    expect(найдено["cam-2"]).toBe("cam-2.webp");
    expect(найдено["cam-3"]).toBe("CAM-3.PNG");
  });

  it("посторонние файлы в папке не считаются кадрами", () => {
    const найдено = подобратьКадры(["ЧИТАТЬ.txt", "cam-1.txt", "cam-1.psd"]);
    expect(найдено).toEqual({});
  });

  it("камера, которой полагается молчать, кадра не получает даже с файлом", () => {
    // Решение «эта камера без сигнала» принимается в данных. Иначе оно
    // менялось бы от того, какие файлы кто-то положил в папку
    const найдено = подобратьКадры([...png, "cam-5.png"]);
    expect(найдено["cam-5"]).toBeUndefined();
  });

  it("пустая папка означает, что сигнала нет ни с одной камеры", () => {
    expect(подобратьКадры([])).toEqual({});
  });
});

describe("Камеры показа", () => {
  const кадры = подобратьКадры([
    "cam-1.png",
    "cam-2.png",
    "cam-3.png",
    "cam-4.png",
  ]);

  it("одна камера нарочно без сигнала", () => {
    // Показ, где всё идеально, вызывает вопрос «а когда сломается».
    // Ответ должен быть на экране
    const снимки = demoSnapshots(now, кадры);
    const безСигнала = снимки.filter((к) => !к.url);
    expect(безСигнала).toHaveLength(1);
    expect(безСигнала[0].cameraName).toBe("Въезд на территорию");
  });

  it("без файлов в папке окон не будет ни одного", () => {
    // И это рабочее состояние, а не поломка: блок трансляции скажет,
    // что сигнал не поступает
    const снимки = demoSnapshots(now, {});
    expect(снимки.every((к) => !к.url)).toBe(true);
  });

  it("у камер с кадром указано время кадра", () => {
    for (const кадр of demoSnapshots(now, кадры).filter((к) => к.url)) {
      expect(кадр.updatedAt).not.toBeNull();
      const возраст = now.getTime() - new Date(кадр.updatedAt!).getTime();
      // Свежий кадр: иначе блок трансляции приглушит картинку как старую
      expect(возраст).toBeLessThan(60_000);
    }
  });

  it("адрес кадра ведёт в папку показа", () => {
    for (const кадр of demoSnapshots(now, кадры).filter((к) => к.url)) {
      expect(кадр.url).toMatch(/^\/demo\/cam-\d+\.[a-z]+$/i);
    }
  });
});

describe("Поголовье показа", () => {
  const стадо = demoHerd(now);

  it("вес и привес в границах, возможных для КРС на откорме", () => {
    // Корова на 900 килограммов и привес три кило в сутки ломают
    // доверие ко всем остальным числам на экране
    for (const животное of стадо) {
      expect(животное.weightKg!).toBeGreaterThanOrEqual(350);
      expect(животное.weightKg!).toBeLessThanOrEqual(560);
      expect(животное.dailyGainKg!).toBeGreaterThan(0.5);
      expect(животное.dailyGainKg!).toBeLessThan(1.3);
    }
  });

  it("одно животное ходит меньше своей нормы", () => {
    // Это и есть то, ради чего систему покупают
    const проблемные = стадо.filter(
      (ж) => (ж.activity?.ratio_to_own ?? 1) < 0.7,
    );
    expect(проблемные).toHaveLength(1);
  });

  it("у части животных узнавание ещё набирается", () => {
    const мало = стадо.filter((ж) => (ж.readiness?.embeddings ?? 0) < 10);
    expect(мало.length).toBeGreaterThan(0);
    expect(мало.length).toBeLessThan(стадо.length / 2);
  });
});

describe("Тревоги показа", () => {
  it("каждый вид тревоги известен системе", () => {
    /*
      Набор был собран с видом «person_detected», которого в системе
      нет: название не нашлось в таблице, и на экране рядом с русским
      заголовком стояло это слово латиницей. Заметили не глазами, а
      открыв собранную страницу.
    */
    const { open, history } = demoAlerts(now);
    for (const тревога of [...open, ...history]) {
      expect(ALERT_KINDS as string[]).toContain(тревога.kind);
      expect(alertName(тревога.kind)).not.toBe(тревога.kind);
    }
  });

  it("у каждой тревоги есть строка с числами", () => {
    // Вердикт без чисел нечем проверить
    const { open, history } = demoAlerts(now);
    for (const тревога of [...open, ...history]) {
      expect(describeAlert(тревога).length).toBeGreaterThan(5);
    }
  });

  it("тревогу не поднимает камера, которая к тому времени уже молчала", () => {
    /*
      Эта нестыковка тут была. Камера на въезде числилась без сигнала
      четыре часа, а тревога о постороннем с неё же стояла открытой семь
      минут: кадров нет, а человека она увидела. Первый же внимательный
      человек в зале спросил бы, как это.

      Теперь наоборот, и это даже интереснее: тревога поднята раньше,
      чем камера замолчала, и потому до сих пор не закрылась — закрыть
      её некому. Так и работает система: она не закрывает тревогу по
      таймеру только потому, что перестала получать кадры.
    */
    const { open } = demoAlerts(now);
    const кадры = demoSnapshots(now, подобратьКадры([]));

    for (const тревога of open) {
      if (!тревога.camera_id) continue;
      const кадр = кадры.find((к) => к.cameraId === тревога.camera_id);
      if (!кадр || кадр.updatedAt === null) continue;

      const замолчала = new Date(кадр.updatedAt).getTime();
      const поднята = new Date(тревога.opened_at).getTime();
      expect(
        поднята,
        `тревога «${тревога.title}» поднята камерой, которая к тому времени молчала`,
      ).toBeLessThanOrEqual(замолчала);
    }
  });

  it("есть открытая тревога о постороннем", () => {
    const { open } = demoAlerts(now);
    expect(open.some((a) => a.kind === "intruder")).toBe(true);
    expect(open.every((a) => a.resolved_at === null)).toBe(true);
  });

  it("в истории только закрытые", () => {
    const { history } = demoAlerts(now);
    expect(history.length).toBeGreaterThan(0);
    expect(history.every((a) => a.resolved_at !== null)).toBe(true);
  });
});

describe("Показ выглядит как рабочая платформа", () => {
  function файлыПоказа(): string[] {
    const найдено: string[] = [];
    const обойти = (папка: string) => {
      for (const имя of readdirSync(папка)) {
        const путь = join(папка, имя);
        if (statSync(путь).isDirectory()) обойти(путь);
        else найдено.push(путь);
      }
    };
    обойти(join(process.cwd(), "app/demo"));
    обойти(join(process.cwd(), "lib/demo"));
    return найдено;
  }

  it("на экранах нет слов «демо», «пример» и «тест»", () => {
    /*
      Слово «демо» на экране обесценивает всё, что рядом: человек
      перестаёт читать числа и начинает искать, где ещё обман. В коде
      и в комментариях эти слова нужны, на экране их быть не должно.
    */
    const подозрительные: string[] = [];
    for (const путь of файлыПоказа()) {
      const код = readFileSync(путь, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      // Видимый текст: строки в кавычках и текст между тегами
      const строки = [
        ...код.matchAll(/"([^"\n]*[А-Яа-яЁё][^"\n]*)"/g),
        ...код.matchAll(/>\s*([^<>{}\n]*[А-Яа-яЁё][^<>{}\n]*?)\s*</g),
      ].map((м) => м[1]);
      for (const строка of строки) {
        if (/демо|пример|тест|заглушк|выдуман/i.test(строка)) {
          подозрительные.push(`${путь}: «${строка}»`);
        }
      }
    }
    expect(подозрительные).toEqual([]);
  });

  it("каждый раздел полосы существует под адресом показа", () => {
    // Нажатие в пустоту на защите выглядит хуже отсутствующего раздела
    const отсутствуют = NAV.map((раздел) => withBase("/demo", раздел.href))
      .map((адрес) => ({
        адрес,
        файл: join(
          process.cwd(),
          "app",
          адрес.replace(/^\//, ""),
          "page.tsx",
        ),
      }))
      .filter(({ файл }) => {
        try {
          statSync(файл);
          return false;
        } catch {
          return true;
        }
      })
      .map(({ адрес }) => адрес);
    expect(отсутствуют).toEqual([]);
  });

  it("обычная полоса разделов на страницах показа не выводится", () => {
    // Её ссылки уводят из показа на живую ферму, где встретит вход
    expect(shouldHide("/demo")).toBe(true);
    expect(shouldHide("/demo/alerts")).toBe(true);
    // А своя, с приставкой, выводится
    expect(shouldHide("/demo", "/demo")).toBe(false);
  });

  it("ссылки внутри показа не уводят на живую ферму", () => {
    expect(withBase("/demo", "/")).toBe("/demo");
    expect(withBase("/demo", "/alerts")).toBe("/demo/alerts");
    expect(withBase("", "/alerts")).toBe("/alerts");
  });
});

describe("Из показа нельзя уйти случайно", () => {
  it("ни одна ссылка на страницах показа не ведёт на живую ферму", () => {
    /*
      Ссылка из показа на рабочий раздел приводит человека на страницу
      входа. На защите это читается как «платформа не работает», а не
      как «сюда нужен пароль». Поэтому все адреса внутри показа
      начинаются с /demo, а там, где соответствующей страницы нет,
      ссылки не должно быть вовсе.
    */
    const наружу: string[] = [];
    const обойти = (папка: string) => {
      for (const имя of readdirSync(папка)) {
        const путь = join(папка, имя);
        if (statSync(путь).isDirectory()) {
          обойти(путь);
          continue;
        }
        const код = readFileSync(путь, "utf8")
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .replace(/^\s*\/\/.*$/gm, "");
        for (const м of код.matchAll(/href=(?:"([^"]+)"|\{`([^`]+)`\})/g)) {
          const адрес = м[1] ?? м[2] ?? "";
          if (адрес.startsWith("/") && !адрес.startsWith("/demo")) {
            наружу.push(`${путь}: ${адрес}`);
          }
        }
      }
    };
    обойти(join(process.cwd(), "app/demo"));
    expect(наружу).toEqual([]);
  });
});
