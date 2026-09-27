import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * ЕДИНЫЙ ДИЗАЙН-КОД
 *
 * Правило одно: в разметке нет сырых цветов из палитры Tailwind. Есть
 * только имена по смыслу — ink, muted, line, brand, calm, watch,
 * trouble.
 *
 * Зачем правило, а не договорённость. Договорённость держится, пока о
 * ней помнят: один `text-neutral-500`, дописанный в спешке, ничего не
 * ломает и никем не замечается. Через полгода их триста, и «поменять
 * цвет» снова значит обойти пятьдесят файлов — ровно то, от чего
 * уходили.
 *
 * Проверка дешёвая: поиск по строке. Мутационный прогон ей не нужен —
 * она либо находит вхождение, либо нет.
 */

const КОРНИ = ["app", "components"];

const ЗАПРЕЩЕНО =
  /(?<![\w-])(bg|text|border|ring|divide|from|to|placeholder|fill|stroke|outline|decoration|shadow|accent|caret)-(neutral|gray|slate|zinc|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}(?![\w-])/g;

function файлы(корень: string): string[] {
  const найдено: string[] = [];
  const обойти = (папка: string) => {
    for (const имя of readdirSync(папка)) {
      const путь = join(папка, имя);
      if (statSync(путь).isDirectory()) обойти(путь);
      else if (путь.endsWith(".tsx")) найдено.push(путь);
    }
  };
  обойти(join(process.cwd(), корень));
  return найдено;
}

describe("Цвета берутся только из токенов", () => {
  const всё = КОРНИ.flatMap(файлы);

  it("файлов для проверки нашлось достаточно", () => {
    // Иначе проверка, ничего не нашедшая, выглядела бы как пройденная
    expect(всё.length).toBeGreaterThan(30);
  });

  it.each(КОРНИ)("в %s нет сырых цветов палитры", (корень) => {
    const нарушители: string[] = [];
    for (const путь of файлы(корень)) {
      const текст = readFileSync(путь, "utf8");
      const найдено = текст.match(ЗАПРЕЩЕНО);
      if (найдено) {
        const короткий = путь.slice(путь.indexOf(корень));
        нарушители.push(`${короткий}: ${[...new Set(найдено)].join(", ")}`);
      }
    }
    expect(нарушители).toEqual([]);
  });

  it("нет длинной записи bg-[var(--color-…)] вместо короткого имени", () => {
    // Две записи одного и того же расходятся тем быстрее, чем больше
    // файлов: короткое имя правится переименованием токена, длинное —
    // нет, и остаётся жить со старым именем
    const длинно: string[] = [];
    for (const путь of всё) {
      const найдено = readFileSync(путь, "utf8").match(
        /(?:bg|text|border|ring|fill|stroke|outline)-\[var\(--color-[a-z0-9-]+\)\]/g,
      );
      if (найдено) {
        длинно.push(`${путь.slice(путь.indexOf("dashboard/") + 10)}: ${[
          ...new Set(найдено),
        ].join(", ")}`);
      }
    }
    expect(длинно).toEqual([]);
  });

  it("в разметке нет цветов шестнадцатеричным кодом", () => {
    /*
      Запрет на сырые классы палитры не ловил цвета внутри SVG: там они
      пишутся атрибутами, а не классами. В графике поголовья так и
      остались fill="#171717" и stroke="#f0f0f0" — почти чёрный и почти
      белый, не имеющие отношения ни к знаку, ни к токенам. При смене
      палитры на синюю они остались серыми, и график выглядел деталью из
      другого продукта.
    */
    const сырые: string[] = [];
    for (const путь of всё) {
      const код = readFileSync(путь, "utf8");
      const найдено = код.match(/#[0-9a-fA-F]{3,8}\b/g);
      if (найдено) {
        const короткий = путь.slice(путь.indexOf("dashboard/") + 10);
        сырые.push(`${короткий}: ${[...new Set(найдено)].join(", ")}`);
      }
    }
    expect(
      сырые,
      "цвет задаётся токеном: var(--color-…), а не кодом",
    ).toEqual([]);
  });

  it("сама проверка работает", () => {
    // Без этого она молча прошла бы и на сломанном выражении
    expect("text-neutral-500".match(ЗАПРЕЩЕНО)).not.toBeNull();
    expect("bg-emerald-50".match(ЗАПРЕЩЕНО)).not.toBeNull();
    expect("hover:bg-red-50".match(ЗАПРЕЩЕНО)).not.toBeNull();
  });

  it("имена по смыслу проверку не трогают", () => {
    for (const можно of [
      "text-ink",
      "text-muted",
      "border-line",
      "bg-surface",
      "bg-calm-bg",
      "text-trouble",
      "hover:bg-soft",
      "border-watch/30",
      "bg-brand",
      "text-[length:var(--text-base)]",
    ]) {
      expect(можно.match(ЗАПРЕЩЕНО)).toBeNull();
    }
  });
});

describe("Касания не мельчают", () => {
  it("у кнопок и ссылок-кнопок есть класс tap", () => {
    // Высота, набранная отступами, зависит от размера шрифта внутри:
    // на коротком тексте кнопка выходит в тридцать пикселей, и это
    // видно только тому, кто по ней промахнулся
    const кнопка = readFileSync(
      join(process.cwd(), "components/ui/Button.tsx"),
      "utf8",
    );
    expect(кнопка).toContain("tap");
  });
});

describe("Страницы устроены одинаково", () => {
  /*
    Список страниц берётся с диска, а не пишется руками.

    Руками он уже был, и в нём не хватало админских разделов: новая
    страница просто не попадала под проверку, и заметить это можно было
    только случайно. Списки, написанные рядом с тем, что они
    описывают, расходятся всегда.

    Исключения названы поимённо и объяснены. Каждое проверяется на
    существование: переименовали страницу, и «исключение» молча стало
    бы прикрытием для несуществующего файла.
  */
  const ИСКЛЮЧЕНИЯ: Record<string, string> = {
    "app/login/page.tsx": "вход: экран по центру, без полос и разделов",
    "app/admin/page.tsx": "админка живёт в своём макете, с боковым меню",
    "app/admin/training/page.tsx": "то же, макет админки",
    "app/admin/farms/new/page.tsx": "то же, макет админки",
    "app/admin/farms/[id]/page.tsx": "то же, макет админки",
  };

  function всеСтраницы(): string[] {
    const найдено: string[] = [];
    const обойти = (папка: string) => {
      for (const имя of readdirSync(папка)) {
        const путь = join(папка, имя);
        if (statSync(путь).isDirectory()) обойти(путь);
        else if (имя === "page.tsx") {
          найдено.push(путь.slice(путь.indexOf("app/")));
        }
      }
    };
    обойти(join(process.cwd(), "app"));
    return найдено.sort();
  }

  const СТРАНИЦЫ = всеСтраницы().filter((п) => !(п in ИСКЛЮЧЕНИЯ));

  it("страниц нашлось столько, сколько их есть", () => {
    expect(всеСтраницы().length).toBeGreaterThan(8);
    expect(СТРАНИЦЫ.length).toBeGreaterThan(4);
  });

  it.each(Object.keys(ИСКЛЮЧЕНИЯ))("исключение %s существует", (путь) => {
    expect(() => statSync(join(process.cwd(), путь))).not.toThrow();
  });

  it.each(СТРАНИЦЫ)("%s берёт общую обёртку", (путь) => {
    // Одна и та же строка отступов была скопирована в девять файлов и в
    // трёх уже разошлась. По отдельности незаметно, а при переходе
    // между разделами содержимое дёргается — и человек видит не «разные
    // страницы», а «что-то подгрузилось криво»
    const текст = readFileSync(join(process.cwd(), путь), "utf8");
    expect(текст).toContain("<Page");
  });

  it("обёртка отступает от нижней полосы", () => {
    // Иначе на телефоне последняя карточка прячется под разделами, и
    // заметит это не разработчик, а человек, не нашедший «Сохранить»
    const обёртка = readFileSync(
      join(process.cwd(), "components/ui/Page.tsx"),
      "utf8",
    );
    expect(обёртка).toContain("pb-nav");
  });
});
