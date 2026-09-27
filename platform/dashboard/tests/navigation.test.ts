import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV, isActive, shouldHide } from "../components/ui/TopNav";

/**
 * РАЗДЕЛЫ НАЗЫВАЮТСЯ ОДИНАКОВО ВЕЗДЕ
 *
 * Человек нажимает «Животные» и должен попасть на страницу, над которой
 * написано «Животные». Звучит очевидно, но расходится это легко: подпись
 * в полосе разделов и заголовок страницы лежат в разных файлах, и
 * переименовать один, забыв другой, ничего не ломает. Ничего, кроме
 * уверенности человека, что он попал куда хотел.
 *
 * Второе правило: одно слово — одно место. «Камеры» было сразу тремя
 * разными вещами: раздел с разметкой кормушек, карточка с кадрами на
 * главной и список камер в настройках. Человек, которому сказали
 * «посмотрите в камерах», не знал, куда идти.
 */

const ФАЙЛ_СТРАНИЦЫ: Record<string, string> = {
  "/alerts": "app/alerts/page.tsx",
  "/animals": "app/animals/page.tsx",
  "/zones": "app/zones/page.tsx",
  "/settings": "app/settings/page.tsx",
};

/** Первый заголовок страницы: <PageHeader title="…" /> */
function заголовок(файл: string): string | null {
  const текст = readFileSync(join(process.cwd(), файл), "utf8");
  const м = текст.match(/<PageHeader[\s\S]{0,200}?title="([^"]+)"/);
  return м ? м[1] : null;
}

describe("Подпись раздела и заголовок страницы совпадают", () => {
  it("у каждого раздела, кроме главной, известна страница", () => {
    // Иначе проверка ниже молча пропустила бы новый раздел
    const без = NAV.filter((р) => р.href !== "/" && !(р.href in ФАЙЛ_СТРАНИЦЫ));
    expect(без.map((р) => р.href)).toEqual([]);
  });

  it.each(Object.entries(ФАЙЛ_СТРАНИЦЫ))(
    "%s: заголовок такой же, как подпись в полосе",
    (href, файл) => {
      const подпись = NAV.find((р) => р.href === href)?.label;
      expect(заголовок(файл)).toBe(подпись);
    },
  );

  it("главная обходится без заголовка: там сразу ответ про ферму", () => {
    const текст = readFileSync(join(process.cwd(), "app/page.tsx"), "utf8");
    expect(текст).not.toContain("<PageHeader");
    expect(текст).toContain("<FarmStatus");
  });
});

describe("Одно название — одно место", () => {
  it("подписи разделов не повторяются", () => {
    const подписи = NAV.map((р) => р.label);
    expect(new Set(подписи).size).toBe(подписи.length);
  });

  it("название раздела не занято карточкой на другом экране", () => {
    // «Камеры» было и разделом, и карточкой на главной, и карточкой в
    // настройках. Совет «посмотрите в камерах» переставал что-то значить
    const чужие = ["app/page.tsx", "app/settings/page.tsx"];
    const занятые: string[] = [];
    for (const файл of чужие) {
      const текст = readFileSync(join(process.cwd(), файл), "utf8");
      for (const м of текст.matchAll(/title="([^"]+)"/g)) {
        const свой = ФАЙЛ_СТРАНИЦЫ[NAV.find((р) => р.label === м[1])?.href ?? ""];
        if (NAV.some((р) => р.label === м[1]) && свой !== файл) {
          занятые.push(`${файл}: карточка «${м[1]}» названа как раздел`);
        }
      }
    }
    expect(занятые).toEqual([]);
  });
});

describe("Подсветка раздела", () => {
  it("главная подсвечивается только на главной", () => {
    // Любой путь начинается со слэша, поэтому по префиксу она горела бы всегда
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/animals", "/")).toBe(false);
  });

  it("раздел горит и на вложенной странице", () => {
    expect(isActive("/animals/17", "/animals")).toBe(true);
  });

  it("на входе и на условиях полос нет: уходить некуда", () => {
    expect(shouldHide("/login")).toBe(true);
    expect(shouldHide("/terms")).toBe(true);
    expect(shouldHide("/animals")).toBe(false);
  });
});
