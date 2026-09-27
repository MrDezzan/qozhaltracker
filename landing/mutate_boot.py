# -*- coding: utf-8 -*-
"""Проверка, что тест заставки умеет падать.

Каждая мутация ломает ровно одну защиту. Тест обязан это заметить.
Мутация, которую тест не заметил, означает, что защита не проверяется
ничем и держится на честном слове.

    npm i jsdom && python3 mutate_boot.py
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
    ("убран предохранитель в <head>",
     '''window.setTimeout(function () {
      document.documentElement.classList.remove("booting", "boot-out");
    }, 4000);''',
     '''  /* мутант: предохранителя нет */'''),

    ("убран потолок в основном скрипте",
     "window.setTimeout(finish, BOOT_MAX_MS);",
     "/* мутант: потолка нет */"),

    ("ошибка загрузки шрифта больше не считается ответом",
     "document.fonts.ready.then(finish, finish);",
     "document.fonts.ready.then(finish);"),

    ("браузер без document.fonts больше не обрабатывается",
     '''} else {
        finish();
      }''',
     '''  } else {
    /* мутант: ничего не делаем */
  }'''),
]

def вернуть_страницу(*_):
    """Вернуть страницу из резервной копии, в том числе по сигналу.

    Если прогон убить в середине, finally может не отработать, и
    страница останется с применённой мутацией. Один раз так и вышло:
    дальше тесты падали на ровном месте, и поиск несуществующей
    регрессии съел полчаса.
    """
    if not os.path.exists(BACKUP):
        return
    shutil.copy(BACKUP, PAGE)
    if open(PAGE, encoding="utf-8").read() == open(BACKUP, encoding="utf-8").read():
        os.remove(BACKUP)


shutil.copy(PAGE, BACKUP)
signal.signal(signal.SIGTERM, lambda *_: (вернуть_страницу(), sys.exit(3)))
signal.signal(signal.SIGINT, lambda *_: (вернуть_страницу(), sys.exit(3)))
orig = open(BACKUP, encoding="utf-8").read()
survived = []
отстал = []
try:
    for name, old, new in MUTANTS:
        if orig.count(old) != 1:
            # Отставший мутант это НЕ выживший. Выживший означает
            # «защита не проверяется», отставший — «проверка сломалась и
            # молчит», а это хуже: она выглядит работающей. Так и вышло
            # после прогона файла через форматировщик
            отстал.append(name)
            print("  ОТСТАЛ  %-52s ← совпадений в коде: %d" % (name, orig.count(old)))
            continue
        open(PAGE, "w", encoding="utf-8").write(orig.replace(old, new))
        run = subprocess.run(["node", os.path.join(HERE, "test_boot.js")],
                             capture_output=True, text=True, cwd=HERE)
        if run.returncode == 0:
            print("  ВЫЖИЛ   %s" % name)
            survived.append(name)
        else:
            hit = [l for l in run.stdout.splitlines()
                   if l.startswith(("ЗАВИСЛА", "МЕДЛЕННО"))]
            print("  убит    %s   ← %s" % (name, hit[0].strip() if hit else ""))
finally:
    вернуть_страницу()

print()
if отстал:
    print("ОТСТАЛИ: %d — эти мутанты не нашли своё место в коде." % len(отстал))
    print("Они ничего не проверяют, хотя выглядят рабочими.")
    sys.exit(2)
if survived:
    print("ВЫЖИВШИХ: %d — эти защиты ничем не проверяются" % len(survived))
    sys.exit(1)
print("все %d мутантов убиты" % len(MUTANTS))
