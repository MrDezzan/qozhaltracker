# -*- coding: utf-8 -*-
"""Проверка, что тест анкеты умеет падать.

Каждая мутация ломает ровно одно правило: расчёта, обязательности или
запрета на цены. Тест обязан это заметить.

Мутация, которую тест не заметил, означает, что правило ничем не
проверяется. Для расчёта это значит, что страница сможет назвать
клиенту неверное число камер; для обязательности — что менеджеру придёт
пустая анкета; и узнаем мы об этом не здесь.

    npm i jsdom && python3 mutate_calc.py
"""
import os
import shutil
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "index.html")
BACKUP = os.path.join(HERE, ".index.orig.html")

MUTANTS = [
    # ---------------------------------------------------------- расчёт
    ("голов на проход: 400 → 500",
     "const HEAD_PER_RACE = 400;", "const HEAD_PER_RACE = 500;"),

    ("откорм считается как обычное стадо (600 → 400)",
     "const FEED_PER_RACE = 600;", "const FEED_PER_RACE = 400;"),

    ("одна камера на проход вместо двух",
     "const CAMS_PER_RACE = 2;", "const CAMS_PER_RACE = 1;"),

    ("камер на мини-ПК: 4 → 8",
     "const CAMS_PER_PC = 4;", "const CAMS_PER_PC = 8;"),

    # ------------------------------------------- обзор загонов и охрана
    # Половина продукта: без камер над загонами не работает ни одна
    # тревога по здоровью, а страница их обещает
    ("метров на камеру обзора: 330 → 1000",
     "const M2_PER_PEN_CAM = 330;", "const M2_PER_PEN_CAM = 1000;"),

    ("обзор загонов выброшен из общего числа",
     "  const cams = race + pens + guard;", "  const cams = race + guard;"),

    ("охрана выброшена из общего числа",
     "  const cams = race + pens + guard;", "  const cams = race + pens;"),

    ("обзор загонов округляется вниз",
     "    ? Math.ceil(one * s.pensCount / M2_PER_PEN_CAM)",
     "    ? Math.floor(one * s.pensCount / M2_PER_PEN_CAM)"),

    ("загоны считаются, даже когда ответили «нет»",
     "  const one = s.pens ? penArea(s.pensSize) : null;",
     "  const one = penArea(s.pensSize);"),

    ("метров забора на камеру: 150 → 400",
     "const M_PER_GUARD_CAM = 150;", "const M_PER_GUARD_CAM = 400;"),

    ("углы без камер: минимум охраны снят",
     "const MIN_GUARD_CAMS = 4;", "const MIN_GUARD_CAMS = 0;"),

    ("нечитаемый размер загона проходит проверку",
     "    else if (penArea(s.pensSize) === null) gaps.push",
     "    else if (false) gaps.push"),

    ("«15 на 12» читается как 15, а не как площадь",
     "if (found.length < 2) return a;\n      const b = parseFloat(found[1]);\n      return b > 0 ? a * b : a;",
     "return a;"),

    ("округление проходов вниз вместо вверх",
     "Math.ceil(plain / HEAD_PER_RACE) + Math.ceil(feed / FEED_PER_RACE));",
     "Math.floor(plain / HEAD_PER_RACE) + Math.floor(feed / FEED_PER_RACE));"),

    ("откорм считается даже без откормплощадки",
     "const feed = s.feedlot ? Math.min(Math.max(0, s.feedHead || 0), head) : 0;",
     "const feed = Math.min(Math.max(0, s.feedHead || 0), head);"),

    ("откорм больше стада больше не обрезается",
     "const feed = s.feedlot ? Math.min(Math.max(0, s.feedHead || 0), head) : 0;",
     "const feed = s.feedlot ? Math.max(0, s.feedHead || 0) : 0;"),

    # -------------------------------------------------- обязательность
    ("поголовье перестало быть обязательным",
     '  if (!s.head) gaps.push({ field: "f-head", focus: "q-head", err: "e-head", key: "eHead" });',
     "  /* мутант: поголовье не проверяется */"),

    ("охрана перестала быть обязательной",
     '  if (s.guard === null) gaps.push({ field: "f-guard", focus: null, err: "e-guard", key: "eGuard" });',
     "  /* мутант: охрана не проверяется */"),

    ("размер загона перестал быть обязательным",
     '    else if (!s.pensSize.trim()) gaps.push({ field: "f-pens", focus: "q-penssize", err: "e-pens", key: "ePensSize" });',
     "    /* мутант: размер не проверяется */"),

    ("незаполненная анкета всё равно уходит в WhatsApp",
     'if (!gaps.length) return;      // ссылка уже ведёт в WhatsApp\n        e.preventDefault();',
     "if (true) return;"),

    ("ссылка ведёт в WhatsApp, даже когда ответов не хватает",
     'a.href = gaps.length\n          ? "#ask"',
     'a.href = false\n          ? "#ask"'),

    ("прочерки заменились выдуманной единицей",
     'document.getElementById("r-race").textContent = ready ? k.races : "—";',
     'document.getElementById("r-race").textContent = k.races;'),

    # ------------------------------------------------------ ответ в письме
    ("площадь не попадает в письмо",
     'dict.waArea + ": " + s.area,', '"",'),

    ("размеры загонов не попадают в письмо",
     '", " + dict.waPensSize + " " + s.pensSize.trim() + ")" : ""),',
     '")" : ""),'),
]

def вернуть_страницу(*_):
    """Вернуть страницу из резервной копии.

    Раньше восстановление стояло только в finally, и этого оказалось
    мало. Прогон убили по таймауту в середине — finally не отработал,
    страница осталась с применённой мутацией, а резервная копия пропала.
    Дальше тесты падали на ровном месте, и полчаса ушло на поиск
    «регрессии», которой не было.

    Теперь то же самое висит и на сигналах завершения, а резервная копия
    удаляется только после того, как страница действительно возвращена.
    """
    if not os.path.exists(BACKUP):
        return
    shutil.copy(BACKUP, PAGE)
    # Проверяем, что вернули, и только потом убираем копию: иначе при
    # сбое записи мы потеряли бы и страницу, и её копию
    if open(PAGE, encoding="utf-8").read() == open(BACKUP, encoding="utf-8").read():
        os.remove(BACKUP)
    sys.exit(3) if _ else None


shutil.copy(PAGE, BACKUP)
signal.signal(signal.SIGTERM, вернуть_страницу)
signal.signal(signal.SIGINT, вернуть_страницу)
orig = open(BACKUP, encoding="utf-8").read()
survived = []
отстал = []
try:
    for name, old, new in MUTANTS:
        if orig.count(old) != 1:
            # Мутант отстал от кода: строка, которую он ищет, больше не
            # совпадает. Это НЕ то же самое, что выживший мутант, и
            # путать их нельзя. Выживший означает «правило не
            # проверяется». Отставший означает «проверка сломалась и
            # молчит», а это хуже: она выглядит работающей.
            #
            # Случилось ровно так: файл прогнали через форматировщик,
            # отступы поехали, и пять мутантов перестали находить своё
            # место. Тесты были зелёные, проверка мутациями — тоже, если
            # смотреть только на последнюю строку.
            отстал.append((name, orig.count(old)))
            print("  ОТСТАЛ  %-52s ← совпадений в коде: %d" % (name, orig.count(old)))
            continue
        open(PAGE, "w", encoding="utf-8").write(orig.replace(old, new))
        run = subprocess.run(["node", os.path.join(HERE, "test_calc.js")],
                             capture_output=True, text=True, cwd=HERE)
        if run.returncode == 0:
            print("  ВЫЖИЛ   %s" % name)
            survived.append(name)
        else:
            hit = [l.strip() for l in run.stdout.splitlines()
                   if l.startswith("РАСХОЖДЕНИЕ")]
            print("  убит    %-52s ← %s" % (name, hit[0][12:].strip() if hit else "тест упал"))
finally:
    вернуть_страницу()

print()
if отстал:
    print("ОТСТАЛИ: %d — эти мутанты не нашли своё место в коде." % len(отстал))
    print("Они ничего не проверяют, хотя выглядят рабочими.")
    print("Поправьте строку поиска в mutate_calc.py и прогоните снова.")
    sys.exit(2)
if survived:
    print("ВЫЖИВШИХ: %d — эти правила ничем не проверяются" % len(survived))
    sys.exit(1)
print("все %d мутантов убиты" % len(MUTANTS))
