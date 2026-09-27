"""
Мутационная проверка порогов здоровья.

Запуск из корня проекта:

    python3 cv-service/scripts/mutate_health.py

Каждая строка ниже портит один порог или одну заслонку в health.py и
прогоняет тесты. Тест обязан упасть. Выживший мутант означает, что порог
можно менять как угодно и никто не заметит, — то есть он не проверен.

Так уже находили: тест, сравнивавший константу саму с собой; заслонку,
которую можно удалить целиком; и одну и ту же проверку в двух местах,
где убрать любую из копий было безнаказанно.

Файл возвращается в исходное состояние в любом случае, включая падение.
"""

import io, os, pathlib, shutil, subprocess
CV = "cv-service"
H = f"{CV}/src/cv_service/health.py"
TESTS = ["tests/test_health_days.py", "tests/test_health_norms.py", "tests/test_health_rules.py"]

MUTS = [
    (H, "MIN_ALIVE_HOURS = 12.0", "MIN_ALIVE_HOURS = 0.0", "порог живости камеры"),
    (H, "LOW_RATIO = 0.67", "LOW_RATIO = 0.99", "порог «мало»"),
    (H, "HIGH_RATIO = 1.5", "HIGH_RATIO = 1.01", "порог «много»"),
    (H, "DAYS_TO_SPEAK = 2", "DAYS_TO_SPEAK = 1", "два дня подряд"),
    (H, "MIN_EMBEDDINGS_TO_JUDGE = 4", "MIN_EMBEDDINGS_TO_JUDGE = 0", "заслонка узнавания"),
    (H, "HERD_TROUBLE_SHARE = 1.0 / 3.0", "HERD_TROUBLE_SHARE = 2.0", "заслонка стада"),
    (H, "MIN_HERD_FOR_SHARE = 5", "MIN_HERD_FOR_SHARE = 1", "малое стадо"),
    (H, "MIN_DAYS_FOR_BASELINE = 3", "MIN_DAYS_FOR_BASELINE = 1", "минимум дней для нормы"),
    (H, "MIN_SECONDS_VISIBLE = 300.0", "MIN_SECONDS_VISIBLE = 0.0", "минимум времени в кадре"),
    (H, "        movement.add(row.day)\n        if row.has_feeder:\n            feeding.add(row.day)",
        "        movement.add(row.day)\n        feeding.add(row.day)", "корм только с кормушечных камер"),
    (H, "    if move_low and feed_low and not missed_meals:", "    if False:", "сочетание признаков"),
    (H, "    if history.herd_share_low >= HERD_TROUBLE_SHARE:\n        # Просело всё стадо. Это про загон, а не про животное\n        return []",
        "    if False:\n        return []", "снятие личных при просевшем стаде"),
    (H, "    if can_move and normally_seen and not today.can_judge_movement:",
        "    if False:", "«не видели» отдельной тревогой"),
    (H, "        if one.day not in history.usable_movement or not one.can_judge_movement:",
        "        if not one.can_judge_movement:", "негодные сутки: движение"),
    (H, "        if one.day not in history.usable_feeding:\n            return False\n        value = ratio(one.feeder_seconds, feeder_norm)",
        "        if False:\n            return False\n        value = ratio(one.feeder_seconds, feeder_norm)", "негодные сутки: корм"),
    (H, "        return self.seconds_visible >= MIN_SECONDS_VISIBLE",
        "        return True", "время в кадре разрешает судить"),
    (H, "    if len(values) < 2:\n        return None\n    return statistics.median(values)",
        "    if len(values) < 1:\n        return None\n    return statistics.median(values)",
        "одно животное не стадо"),
    (H, "    if baseline is None or baseline <= 0:", "    if baseline is None:", "деление на нулевую норму"),
    (H, "    if can_feed and water_norm is not None and water_norm > 0 and today.water_visits == 0:",
        "    if can_feed and today.water_visits == 0:", "вода без истории питья"),
]

survived = []
for path, old, new, why in MUTS:
    src = io.open(path, encoding="utf-8").read()
    if old not in src:
        print("НЕ НАЙДЕНО:", why); survived.append(why + " (образец не найден)"); continue
    io.open(path, "w", encoding="utf-8").write(src.replace(old, new, 1))
    try:
        subprocess.run(["rm", "-rf", f"{CV}/src/cv_service/__pycache__", f"{CV}/tests/__pycache__"])
        r = subprocess.run(["python3", "-m", "pytest", "-q"] + TESTS, cwd=CV,
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": "src:/tmp/stubs"})
        ok = r.returncode != 0
        print(("УБИТА   " if ok else "ВЫЖИЛА  ") + why)
        if not ok: survived.append(why)
    finally:
        io.open(path, "w", encoding="utf-8").write(src)

print("\nвыжило:", len(survived), "из", len(MUTS))
for s in survived: print(" -", s)
