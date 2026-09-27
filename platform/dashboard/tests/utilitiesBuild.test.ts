import { describe, it, expect, beforeAll } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { compile } from "tailwindcss";

/**
 * КАЖДЫЙ СМЫСЛОВОЙ КЛАСС ИЗ РАЗМЕТКИ ДЕЙСТВИТЕЛЬНО СОБИРАЕТСЯ.
 *
 * ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ
 *
 * Соседний designCode.test.ts проверяет, что в разметке нет сырых
 * цветов Tailwind — только наши имена: bg-surface, text-ink, bg-calm-bg.
 * Он проходил зелёным в тот день, когда половина этих классов не
 * собиралась вовсе.
 *
 * Случилось вот что. Смысловые токены лежали в :root, а в @theme
 * дублировались строками вида `--color-surface: var(--color-surface)`.
 * Имя ссылалось само на себя; Tailwind такие выбрасывает молча. Классов
 * bg-surface, bg-calm-bg, bg-watch-bg, bg-trouble-bg, text-surface в
 * собранном CSS не было. Карточки и три плитки состояния фермы
 * оставались без фона — то есть главный экран выглядел сломанным, а
 * тесты были зелёные.
 *
 * Отсюда правило: проверять надо не разметку и не исходный CSS, а то,
 * что получается на выходе. Поэтому тест берёт настоящий сборщик
 * Tailwind, скармливает ему наш globals.css и все имена классов из
 * разметки, и смотрит, для каких имён не родилось ни одного правила.
 *
 * Такой тест ловит и будущие поломки того же рода: опечатку в имени
 * токена, переименование в CSS без правки разметки, случайный перенос
 * объявления из @theme в :root.
 */

const КОРЕНЬ = path.resolve(__dirname, "..");

/**
 * Имена наших смысловых цветов — из самого CSS, а не списком руками.
 *
 * Берём ЛЮБОЕ объявление --color-*, а не только внутри @theme. Это
 * важно: перенос объявления из @theme в :root — ровно та поломка,
 * которую тест обязан поймать. Если бы список собирался только из
 * @theme, такой перенос просто опустошил бы список, и проверка ниже
 * прошла бы вхолостую.
 */
function цветаИзCSS(css: string): string[] {
  const имена = new Set<string>();
  for (const м of css.matchAll(/--color-([a-z0-9-]+)\s*:/g)) имена.add(м[1]);
  return [...имена];
}

function файлыРазметки(): string[] {
  const итог: string[] = [];
  const обойти = (папка: string) => {
    for (const вход of fs.readdirSync(папка, { withFileTypes: true })) {
      const п = path.join(папка, вход.name);
      if (вход.isDirectory()) {
        if (вход.name === "node_modules" || вход.name.startsWith(".")) continue;
        обойти(п);
      } else if (вход.name.endsWith(".tsx")) {
        итог.push(п);
      }
    }
  };
  for (const п of ["app", "components"]) обойти(path.join(КОРЕНЬ, п));
  return итог;
}

/** Все слова, похожие на класс, — из строковых литералов разметки. */
function кандидаты(): Map<string, string[]> {
  const где = new Map<string, string[]>();
  for (const файл of файлыРазметки()) {
    const текст = fs.readFileSync(файл, "utf-8");
    for (const м of текст.matchAll(/["'`]([^"'`\n]{0,400})["'`]/g)) {
      for (const слово of м[1].split(/\s+/)) {
        const чистое = слово.replace(/^[a-z-]+:/g, ""); // hover:, md:, focus-visible:
        if (!/^[a-z][a-z0-9/-]*$/.test(чистое)) continue;
        if (!где.has(чистое)) где.set(чистое, []);
        const список = где.get(чистое)!;
        const короткое = path.relative(КОРЕНЬ, файл);
        if (!список.includes(короткое)) список.push(короткое);
      }
    }
  }
  return где;
}

let собранный = "";
let цвета: string[] = [];
let встречается: Map<string, string[]>;

beforeAll(async () => {
  const globals = fs.readFileSync(
    path.join(КОРЕНЬ, "app", "globals.css"),
    "utf-8",
  );
  // Имена собираем по коду, а не по комментариям вокруг него
  цвета = цветаИзCSS(globals.replace(/\/\*[\s\S]*?\*\//g, ""));
  встречается = кандидаты();

  const сборка = await compile(globals, {
    base: КОРЕНЬ,
    loadStylesheet: async (id: string, base: string) => {
      const файл =
        id === "tailwindcss"
          ? path.join(КОРЕНЬ, "node_modules", "tailwindcss", "index.css")
          : path.resolve(base, id);
      return {
        path: файл,
        base: path.dirname(файл),
        content: fs.readFileSync(файл, "utf-8"),
      };
    },
  });

  собранный = сборка.build([...встречается.keys()]);
});

/** Родилось ли в собранном CSS хоть одно правило для этого класса. */
function собирается(класс: string): boolean {
  const экран = класс.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
  return new RegExp(`\\.${экран}(?![\\w-])`).test(собранный);
}

describe("смысловые классы действительно собираются", () => {
  it("в CSS есть смысловые цвета", () => {
    expect(цвета.length).toBeGreaterThan(10);
  });

  it("каждый цветовой класс из разметки даёт правило в собранном CSS", () => {
    const пропали: string[] = [];
    for (const цвет of цвета) {
      for (const приставка of ["bg", "text", "border"]) {
        const класс = `${приставка}-${цвет}`;
        const где = встречается.get(класс);
        if (!где) continue; // класс не используется — и не надо
        if (!собирается(класс)) {
          пропали.push(`${класс} (в ${где.slice(0, 3).join(", ")})`);
        }
      }
    }
    expect(
      пропали,
      "эти классы стоят в разметке, но Tailwind их не собрал — " +
        "скорее всего токен объявлен не в @theme или ссылается сам на себя",
    ).toEqual([]);
  });

  it("ни один токен не ссылается сам на себя", () => {
    /*
      Проверка была написана только про --color-*, и на второй раз это
      вышло боком: ту же самоссылку сделали в --radius-*, и полсотни
      мест разметки тихо остались с чужими углами по умолчанию. Тест был
      зелёный, потому что смотрел не туда.

      Теперь он смотрит на любое имя. Правило общее: имя, объявленное
      через самого себя, Tailwind выбрасывает молча, и неважно, цвет это
      или радиус.

      Комментарии срезаем: в globals.css обе поломки разобраны словами, и
      без этого тест спотыкается о собственное объяснение.
    */
    const globals = fs
      .readFileSync(path.join(КОРЕНЬ, "app", "globals.css"), "utf-8")
      .replace(/\/\*[\s\S]*?\*\//g, "");
    const самоссылки = [
      ...globals.matchAll(/--([a-z0-9-]+)\s*:\s*var\(--([a-z0-9-]+)\)/g),
    ]
      .filter((м) => м[1] === м[2])
      .map((м) => `--${м[1]}`);
    expect(самоссылки).toEqual([]);
  });

  it("классы скруглений собраны нашей шкалой, а не стандартной", () => {
    // 18 пикселей у карточки это решение из макета. Стандартные 8 от
    // Tailwind выглядят почти так же, и подмену не заметишь глазами
    expect(собранный).toMatch(/--radius-lg:\s*18px/);
    expect(собранный).toMatch(/\.rounded-lg\s*\{[^}]*var\(--radius-lg\)/);
  });

  it("классы наших размеров шрифта перекрыты нашими значениями", () => {
    // text-sm должен быть 15px, а не стандартные 14
    expect(собранный).toMatch(/--text-sm:\s*\.?0?\.9375rem/);
    expect(собранный).toMatch(/\.text-sm\s*\{[^}]*var\(--text-sm\)/);
  });

  it("сам тест способен упасть: выдуманного класса в сборке нет", () => {
    expect(собирается("bg-nesushchestvuyushchiy")).toBe(false);
  });
});
