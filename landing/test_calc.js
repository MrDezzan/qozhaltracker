/* Проверка анкеты.  Запуск:  npm i jsdom && node test_calc.js
 *
 * Три вещи, каждая из которых ломается молча:
 *
 * 1. РАСЧЁТ. Считает страница и считает менеджер по одному и тому же
 *    файлу (prodazhi/KAK_SCHITAT_KLIENTU.md). Разойдутся — выяснится на
 *    сделке. Поэтому здесь прогоняются настоящие клиенты из prodazhi.
 * 2. ОБЯЗАТЕЛЬНОСТЬ. Незаполненная анкета не должна уходить в WhatsApp:
 *    менеджеру придёт «голов: null», и он потеряет время.
 * 3. ЦЕН НЕТ. Ни одной суммы на странице — решение владельца, и его
 *    легко нарушить одной правкой текста.
 *
 * Что тест умеет ловить — видно из mutate_calc.py.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const PAGE = path.join(__dirname, 'index.html');

function open() {
  const dom = new JSDOM(fs.readFileSync(PAGE, 'utf8'), {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://example.com/',
    beforeParse(win) {
      win.matchMedia = () => ({
        matches: false,
        addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {},
      });
      Object.defineProperty(win.document, 'fonts',
        { value: { ready: Promise.resolve() }, configurable: true });
      win.HTMLElement.prototype.scrollIntoView = function () {};
    },
  });
  return dom.window;
}

const win = open();
const doc = win.document;
win.applyLang('ru');   // jsdom представляется английским браузером

let failed = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed += 1;
  console.log(`${ok ? 'сходится' : 'РАСХОЖДЕНИЕ'}  ${name}`);
  if (!ok) console.log(`            получили ${JSON.stringify(got)}, ждали ${JSON.stringify(want)}`);
}

function type(id, value) {
  const el = doc.getElementById(id);
  el.value = String(value);
  el.dispatchEvent(new win.Event('input', { bubbles: true }));
}
function pick(key, val) {
  doc.querySelector('.js-pick[data-key="' + key + '"][data-val="' + val + '"]').click();
}
function send() { doc.querySelector('.js-send').click(); }
function href() { return decodeURIComponent(doc.querySelector('.js-send').href); }
function shown() {
  return {
    races: doc.getElementById('r-race').textContent,
    cams: doc.getElementById('r-cams').textContent,
    pcs: doc.getElementById('r-pc').textContent,
  };
}
function gaps() {
  return [...doc.querySelectorAll('#summary-list a')].map(a => a.textContent);
}

// ---------------------------------------------------------------- формулы
const kit = win.kit;

console.log('── настоящие клиенты из папки prodazhi ──');
// Клиент 01: 200 голов, вся площадка откорма на 200 голов
// Полный комплект по docs/SHEMA_RASSTANOVKI.md: проход плюс обзор загонов
check('клиент 01: 200 голов, 4 загона 35х35 — 17 камер',
      kit({ head: 200, feedlot: true, feedHead: 200, area: 0.5,
            pens: true, pensCount: 4, pensSize: '35 на 35', guard: false }).cams, 17);
// Клиент 02: фермерское хозяйство, один загон, 20-30 голов на откорме
check('клиент 02: 30 голов, один загон 15х12 — 3 камеры',
      kit({ head: 30, feedlot: true, feedHead: 30, area: 0.1,
            pens: true, pensCount: 1, pensSize: '15 на 12', guard: false }).cams, 3);

console.log('\n── границы, на которых число проходов меняется ──');
check('400 голов без откорма — один проход', kit({ head: 400 }).races, 1);
check('401 голова — уже два', kit({ head: 401 }).races, 2);
check('600 на откорме — один проход (прогон плотнее)',
      kit({ head: 600, feedlot: true, feedHead: 600 }).races, 1);
check('601 на откорме — два',
      kit({ head: 601, feedlot: true, feedHead: 601 }).races, 2);
check('500 обычных плюс 600 откорма — два и один',
      kit({ head: 1100, feedlot: true, feedHead: 600 }).races, 3);

console.log('\n── откорм учитывается, только если площадка есть ──');
check('сказали «нет площадки» — введённое число откорма не считается',
      kit({ head: 600, feedlot: false, feedHead: 600 }).races, 2);
check('сказали «есть» — считается по ставке откорма',
      kit({ head: 600, feedlot: true, feedHead: 600 }).races, 1);
check('откорма больше стада — лишнее отбрасывается',
      kit({ head: 1000, feedlot: true, feedHead: 5000 }).races,
      kit({ head: 1000, feedlot: true, feedHead: 1000 }).races);

console.log('\n── камеры и железо ──');
check('на проход всегда две камеры', kit({ head: 1200 }).race, kit({ head: 1200 }).races * 2);
check('до четырёх камер — один компьютер', kit({ head: 800 }).pcs, 1);
check('шесть камер — два компьютера', kit({ head: 1200 }).pcs, 2);

console.log('\n── обзор загонов: половина продукта, которой раньше не было ──');
const penArea = win.penArea;
check('«15 на 12» это 180 квадратов', penArea('15 на 12'), 180);
check('«15х12» тоже', penArea('15х12'), 180);
check('одно число — это сразу площадь', penArea('180'), 180);
check('лишние слова не мешают', penArea('примерно 15 на 12 метров'), 180);
check('запятая в стороне читается', penArea('15,5 на 12'), 186);
check('из «большой» площади не выйдет', penArea('большой'), null);

const pens4 = { head: 200, area: 5, pens: true, pensCount: 4, pensSize: '35 на 35' };
check('4 загона по 1225 м² — 15 камер обзора', kit(pens4).pens, 15);
check('и они попадают в общее число', kit(pens4).cams, kit(pens4).race + 15);
check('сказали «нет загонов» — обзора нет',
      kit(Object.assign({}, pens4, { pens: false })).pens, 0);
check('размер не прочитался — обзор не выдумываем',
      kit(Object.assign({}, pens4, { pensSize: 'большой' })).pens, 0);

console.log('\n── охрана: по периметру, а не по площади ──');
check('без охраны камер охраны ноль', kit({ head: 200, area: 5, guard: false }).guard, 0);
check('1 га — минимум четыре угла', kit({ head: 200, area: 1, guard: true }).guard, 4);
check('5 га — по периметру больше', kit({ head: 200, area: 5, guard: true }).guard, 6);
check('охрана без площади ничего не добавляет',
      kit({ head: 200, area: null, guard: true }).guard, 0);

console.log('\n── пока не ответили, чисел нет ──');
check('в начале стоят прочерки, а не выдуманная единица',
      shown(), { races: '—', cams: '—', pcs: '—' });
check('и замечание зовёт ответить',
      doc.getElementById('r-note').dataset.i18n, 'noteStart');

console.log('\n── все пять вопросов обязательны ──');
const ev = new win.MouseEvent('click', { bubbles: true, cancelable: true });
doc.querySelector('.js-send').dispatchEvent(ev);
check('пустая анкета: переход отменён', ev.defaultPrevented, true);
check('и ссылка ведёт обратно к анкете', href().endsWith('#ask'), true);
check('перечислено ровно пять пробелов', gaps().length, 5);
check('первым — поголовье', gaps()[0], 'Сколько у вас голов');
check('сводка показана', doc.getElementById('summary').hidden, false);

type('q-head', 500);
send();
check('ответили про голов — осталось четыре', gaps().length, 4);
check('и числа появились', shown(), { races: '2', cams: '4', pcs: '1' });
// пока ответили только про поголовье: загонов и охраны ещё нет, значит
// в общем числе только проходы

pick('feedlot', 1);
send();
check('сказали «есть площадка» — теперь спрашиваем, на сколько голов',
      gaps()[0], 'На сколько голов площадка');
check('и поле показалось', doc.getElementById('s-feedlot').hidden, false);

pick('feedlot', 0);
send();
check('передумали: «нет площадки» — вопрос про голов снят',
      gaps().length, 3);
check('и поле спряталось', doc.getElementById('s-feedlot').hidden, true);

type('q-area', 12);
pick('pens', 1);
send();
check('сказали «есть загоны» — спрашиваем количество',
      gaps()[0], 'Сколько загонов');
type('q-penscount', 4);
send();
check('ответили — спрашиваем размер', gaps()[0], 'Примерный размер загона');
type('q-penssize', 'большой');
send();
check('из «большой» площадь не вычислить — просим написать иначе',
      gaps()[0], 'Размер загона, например «15 на 12»');
check('и отправку это останавливает', doc.getElementById('summary').hidden, false);

type('q-penssize', '15 на 12');
send();
check('остался только последний вопрос', gaps(), ['Нужна ли охрана территории']);

pick('guard', 1);
send();
check('анкета заполнена — сводка исчезла', doc.getElementById('summary').hidden, true);
check('и ссылка ведёт в WhatsApp', href().startsWith('https://wa.me/'), true);

console.log('\n── в письмо попали все пять ответов ──');
const msg = href();
for (const [what, needle] of [
  ['поголовье', 'Голов КРС: 500'],
  ['откормплощадка', 'Откормплощадка: нет'],
  ['площадь', 'Площадь, га: 12'],
  ['загоны', 'Загоны: есть (загонов 4, размер 15 на 12)'],
  ['охрана', 'Охрана территории: нужна'],
  ['итог расчёта', 'проходов 2'],
]) check('в письме ' + what, msg.includes(needle), true);

console.log('\n── цен на странице нет ни одной ──');
const page = fs.readFileSync(PAGE, 'utf8');
check('нет знака валюты и слова «тенге»', /₸|тенге|\bтг\b|KZT/i.test(page), false);
const noPhone = page.replace(/\+?7[\d  ()-]{9,}/g, '');
check('нет сумм из прайса', /\b(477|350|700)[  ]?000\b/.test(noPhone), false);
check('нет оборотов «стоит 300»', /(стоит|цена|стоимость)\s+\d/i.test(page), false);

console.log('\n── смена языка ничего не ломает ──');
win.applyLang('en');
/* 500 голов = 2 прохода = 4 камеры; 4 загона по 15х12 = 720 м² = 3 камеры
   обзора; охрана на 12 га = 10 камер по периметру. Итого 17 и 5 компьютеров.
   Раньше здесь стояло 4 камеры: анкета спрашивала про загоны и охрану, а
   считала только проходы */
check('числа не поехали', shown(), { races: '2', cams: '17', pcs: '5' });
check('письмо пересобралось на английском', href().includes('Cattle: 500'), true);
check('и ошибки тоже переводятся', win.eval('T.en.eHead'), 'How many head you have');
win.applyLang('ru');

console.log(failed === 0 ? '\nвсё сходится' : `\nРАСХОЖДЕНИЙ: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
