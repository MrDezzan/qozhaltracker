"""
Мутационная проверка зон: голова у кормушки и пауза на поднятую голову.

Запуск из корня проекта:

    python3 cv-service/scripts/mutate_zones.py

Каждая строка ниже портит одно решение в zones.py и прогоняет тесты.
Тест обязан упасть. Выживший мутант означает, что решение можно менять
как угодно и никто не заметит, — то есть оно не проверено.

Здесь это особенно важно, потому что ошибки в подсчёте кормления не
выглядят как поломка. Система работает, цифры есть, и они правдоподобны.
Просто «время у корма» означает не то, что написано, а тревога «мало
ест» приходит на здоровое животное или не приходит на больное.
"""

import os
import pathlib
import shutil
import subprocess
import sys

CV = "cv-service"
Z = f"{CV}/src/cv_service/zones.py"
TESTS = ["tests/test_zones.py"]

MUTS = [
    # --- голова вместо ног у кормушки ---
    (
        'HEAD_KINDS = frozenset({"feeder", "water"})',
        "HEAD_KINDS = frozenset()",
        "голова не решает нигде",
    ),
    (
        'HEAD_KINDS = frozenset({"feeder", "water"})',
        'HEAD_KINDS = frozenset({"feeder", "water", "gate"})',
        "голова решает и на проходе",
    ),
    (
        "    if detection.mask and len(detection.mask) >= 3:\n        return False, None",
        "    if False:\n        return False, None",
        "запасной путь по ногам при живом контуре",
    ),
    (
        "        if distance > best_distance:",
        "        if distance >= -1:",
        "морда — любая точка, не самая дальняя",
    ),
    (
        "        distance = (point[0] - cx) ** 2 + (point[1] - cy) ** 2",
        "        distance = -((point[0] - cx) ** 2 + (point[1] - cy) ** 2)",
        "берётся ближняя точка вместо дальней",
    ),
    (
        "    if not mask or len(mask) < 3:\n        return None",
        "    if not mask:\n        return None",
        "вырожденный контур из двух точек",
    ),
    (
        "        if not point_in_polygon(point, zone.polygon):\n            continue\n        distance",
        "        if False:\n            continue\n        distance",
        "точки вне зоны тоже считаются мордой",
    ),
    (
        "    if zone.kind not in HEAD_KINDS:\n        point = anchor_point(detection, frame_width, frame_height)\n"
        "        return point_in_polygon(point, zone.polygon), None",
        "    if False:\n        point = anchor_point(detection, frame_width, frame_height)\n"
        "        return point_in_polygon(point, zone.polygon), None",
        "проход пошёл по голове",
    ),
    (
        "                    if head is not None:\n                        visit.head_point = head",
        "                    pass",
        "отметка морды не обновляется",
    ),
    (
        "    if frame_width <= 0 or frame_height <= 0:\n        return None\n\n    mask = detection.mask",
        "    if False:\n        return None\n\n    mask = detection.mask",
        "битый размер кадра",
    ),

    # --- пауза на поднятую голову ---
    (
        "FEEDER_GRACE_SECONDS = 60.0",
        "FEEDER_GRACE_SECONDS = 10.0",
        "пауза у кормушки равна общей",
    ),
    (
        'GRACE_BY_KIND = {\n    "feeder": FEEDER_GRACE_SECONDS,\n    "water": FEEDER_GRACE_SECONDS,\n}',
        "GRACE_BY_KIND = {}",
        "таблица пауз пуста",
    ),
    (
        '    "water": FEEDER_GRACE_SECONDS,\n',
        "",
        "поилка потеряла длинную паузу",
    ),
    (
        '    "feeder": FEEDER_GRACE_SECONDS,\n',
        "",
        "кормушка потеряла длинную паузу",
    ),
    (
        "    return GRACE_BY_KIND.get(kind, default)",
        "    return FEEDER_GRACE_SECONDS",
        "длинная пауза у всех зон",
    ),
    (
        "            if moment - visit.last_seen_at < grace_for(\n"
        "                visit.zone.kind, self.lost_grace_seconds\n            ):",
        "            if moment - visit.last_seen_at < self.lost_grace_seconds:",
        "вид зоны не учитывается",
    ),
    (
        "                    visit.last_seen_at = moment",
        "                    pass",
        "время визита не продлевается",
    ),
]


def run_tests() -> bool:
    """True — тесты прошли."""
    # Чистка кэша обязательна, и это не перестраховка.
    #
    # Python решает, годен ли скомпилированный .pyc, по РАЗМЕРУ и времени
    # правки исходника. Замена «= 60.0» на «= 10.0» размер не меняет, а
    # время правки на многих файловых системах округляется — и
    # интерпретатор берёт СТАРЫЙ байткод. Мутант выглядит выжившим, хотя
    # до кода он просто не дошёл.
    #
    # Поймано так: мутант «пауза у кормушки равна общей» то выживал, то
    # нет от прогона к прогону, а применённый руками честно ронял четыре
    # теста. Все мутации одинаковой длины были ненадёжны.
    for cache in pathlib.Path(CV).rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    # "src" впереди, но чужой PYTHONPATH сохраняем: без него скрипт не
    # запустить там, где часть зависимостей подставляется заглушками
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(filter(None, ["src", os.environ.get("PYTHONPATH", "")])),
        PYTHONDONTWRITEBYTECODE="1",
    )
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
        cwd=CV,
        capture_output=True,
        env=env,
    )
    return result.returncode == 0


def main() -> int:
    if not os.path.isdir(CV):
        print(f"Запускать из корня проекта: папки {CV} здесь нет")
        return 2

    original = open(Z, encoding="utf-8").read()

    if not run_tests():
        print("Тесты не проходят ДО мутаций — чинить надо их, а не пороги")
        return 2

    survivors: list[str] = []
    missing: list[str] = []

    try:
        for before, after, name in MUTS:
            if before not in original:
                missing.append(name)
                print(f"  ? {name}: строка не найдена, мутация не применена")
                continue

            open(Z, "w", encoding="utf-8").write(original.replace(before, after, 1))
            if run_tests():
                survivors.append(name)
                print(f"  ВЫЖИЛ  {name}")
            else:
                print(f"  убит   {name}")
    finally:
        open(Z, "w", encoding="utf-8").write(original)

    print("-" * 60)
    print(f"мутантов: {len(MUTS)}, выжило: {len(survivors)}, не применено: {len(missing)}")

    if missing:
        print("\nНе применены (код изменился — поправьте скрипт):")
        for name in missing:
            print(f"  {name}")

    if survivors:
        print("\nВыжившие — это непроверенные решения:")
        for name in survivors:
            print(f"  {name}")
        return 1

    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
