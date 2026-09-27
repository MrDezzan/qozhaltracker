/* Проверка заставки.  Запуск:  npm i jsdom && node test_boot.js
 *
 * Заставка — единственное место на странице, поломка которого делает
 * сайт недоступным ЦЕЛИКОМ: синий экран, который не уходит. Поэтому она
 * проверяется не глазами, а прогоном по всем сценариям отказа.
 *
 * Что тест умеет ловить — видно из mutate_boot.py: он ломает защиты по
 * одной и убеждается, что тест это замечает.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const PAGE = path.join(__dirname, 'index.html');

/**
 * fonts:
 *   'ok'      — шрифт готов почти сразу
 *   'slow'    — обещание не выполняется никогда, спасать должен потолок
 *   'error'   — загрузка шрифта провалилась (обещание отклонено)
 *   'missing' — браузер не знает document.fonts вовсе
 */
function run(name, { fonts = 'ok', reduced = false, noMatchMedia = false,
                     breakScript = false, maxWait = 9000 }) {
  return new Promise((resolve) => {
    let html = fs.readFileSync(PAGE, 'utf8');
    if (breakScript) {
      // Ломаем ОСНОВНОЙ скрипт: проверяем, что предохранитель в <head> спасает
      const at = html.indexOf('function applyLang(');
      if (at < 0) throw new Error('не нашёл, что ломать — проверка стала пустышкой');
      html = html.slice(0, at) + 'ЛОМАЕМ(' + html.slice(at);
    }

    // beforeParse обязателен: скрипты страницы выполняются ВО ВРЕМЯ разбора,
    // и подмена после конструктора приходит уже слишком поздно
    const dom = new JSDOM(html, {
      runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://example.com/',
      beforeParse(win) {
        if (fonts === 'missing') {
          delete win.document.fonts;
        } else {
          const ready =
            fonts === 'ok'    ? Promise.resolve() :
            fonts === 'error' ? Promise.reject(new Error('шрифт не отдался')) :
                                new Promise(() => {});   // 'slow' — никогда
          ready.catch(() => {});                          // без этого node ругается
          Object.defineProperty(win.document, 'fonts', { value: { ready }, configurable: true });
        }

        if (noMatchMedia) { delete win.matchMedia; return; }
        win.matchMedia = (q) => ({
          matches: reduced && q.includes('reduce'),
          addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
        });
      },
    });
    const { window } = dom;

    const started = Date.now();
    const poll = setInterval(() => {
      if (!window.document.documentElement.classList.contains('booting')) {
        clearInterval(poll);
        resolve({ name, ok: true, ms: Date.now() - started });
      } else if (Date.now() - started > maxWait) {
        clearInterval(poll);
        resolve({ name, ok: false, ms: Date.now() - started });
      }
    }, 25);
  });
}

const cases = [
  ['шрифт готов',                      { fonts: 'ok' },                        900],
  ['шрифт не отдался (ошибка)',        { fonts: 'error' },                     900],
  ['шрифт молчит совсем',              { fonts: 'slow' },                     2900],
  ['браузер без document.fonts',       { fonts: 'missing' },                   900],
  ['режим «уменьшить анимацию»',       { reduced: true, fonts: 'ok' },         900],
  ['браузер без matchMedia',           { noMatchMedia: true, fonts: 'ok' },    900],
  ['основной скрипт сломан целиком',   { breakScript: true, fonts: 'slow' },  5000],
];

(async () => {
  let bad = 0;
  for (const [name, opts, limit] of cases) {
    const r = await run(name, opts);
    const fast = r.ok && r.ms <= limit;
    if (!fast) bad += 1;
    const mark = !r.ok ? 'ЗАВИСЛА ' : (fast ? 'открылась' : 'МЕДЛЕННО');
    console.log(`${mark}  ${String(r.ms).padStart(5)} мс (норма ≤${limit})  ${name}`);
  }
  console.log(bad === 0 ? '\nвсе сценарии открыли страницу' : `\nПРОВАЛОВ: ${bad}`);
  process.exit(bad === 0 ? 0 : 1);
})();
