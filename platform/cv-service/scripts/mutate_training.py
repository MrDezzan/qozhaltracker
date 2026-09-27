"""
Мутационная проверка отбора кадров для дообучения.

Запуск из корня проекта:

    python3 cv-service/scripts/mutate_training.py

Каждая строка ниже портит один порог или одну заслонку в training.py и
прогоняет тесты. Тест обязан упасть. Выживший мутант означает, что порог
можно менять как угодно и никто не заметит, — то есть он не проверен.

Здесь это особенно важно. Ошибка в отборе не проявляется как поломка:
кадры собираются, экран работает, числа выглядят правдоподобно. Просто
через две недели выясняется, что собраны не те кадры, и полтора месяца
разметки потрачены впустую.

Файл возвращается в исходное состояние в любом случае, включая падение.
"""

import os
import pathlib
import shutil
import subprocess
import sys

CV = "cv-service"
T = f"{CV}/src/cv_service/training.py"
TESTS = ["tests/test_training.py"]

MUTS = [
    # --- пороги отбора ---
    (T, "DOUBT_LOW = 0.30", "DOUBT_LOW = 0.00", "нижняя граница сомнения"),
    (T, "DOUBT_HIGH = 0.60", "DOUBT_HIGH = 1.00", "верхняя граница сомнения"),
    (T, "COUNT_JUMP_RATIO = 0.25", "COUNT_JUMP_RATIO = 0.01", "доля скачка счётчика"),
    (T, "COUNT_JUMP_MIN = 2", "COUNT_JUMP_MIN = 1", "минимум голов в скачке"),
    (T, "CROWD_OVERLAP = 0.35", "CROWD_OVERLAP = 0.99", "порог тесноты"),
    (T, "ROUTINE_EVERY = 8", "ROUTINE_EVERY = 1", "частота обычных кадров"),

    # --- самоотключение ---
    (
        T,
        "    try:\n        return date.fromisoformat(raw)\n    except ValueError:\n        return None",
        "    try:\n        return date.fromisoformat(raw)\n    except ValueError:\n        return date.max",
        "непонятная дата включает сбор навсегда",
    ),
    (
        T,
        "    return (today or datetime.now(timezone.utc).date()) <= until",
        "    return True",
        "срок сбора вообще не проверяется",
    ),
    (
        T,
        "    return (today or datetime.now(timezone.utc).date()) <= until",
        "    return (today or datetime.now(timezone.utc).date()) < until",
        "последний день сбора теряется",
    ),
    (
        T,
        "    return value if value > 0 else DEFAULT_DAILY_CAP",
        "    return value",
        "нулевой потолок выключает сбор молча",
    ),

    # --- пустой кадр ---
    (
        T,
        "    if not detections:\n        # Пустой кадр не сохраняем НИКОГДА",
        "    if False:\n        # Пустой кадр не сохраняем НИКОГДА",
        "заслонка пустого кадра",
    ),

    # --- порядок причин ---
    (
        T,
        '    if is_crowded(detections):\n        return "crowded"',
        '    if False:\n        return "crowded"',
        "теснота вообще не ловится",
    ),
    (
        T,
        '    if count_jumped(len(detections), previous_count):\n        return "count_jump"',
        '    if False:\n        return "count_jump"',
        "скачок счётчика не ловится",
    ),
    (
        T,
        '    if has_doubt(detections):\n        return "low_confidence"',
        '    if False:\n        return "low_confidence"',
        "сомнение модели не ловится",
    ),
    (
        T,
        '    if index % ROUTINE_EVERY == 0:\n        return "routine"',
        '    if False:\n        return "routine"',
        "обычные кадры не собираются вовсе",
    ),

    # --- пересечение рамок ---
    (
        T,
        "    return inter / min(area_a, area_b)",
        "    return inter / (area_a + area_b - inter)",
        "пересечение от объединения, а не от меньшей рамки",
    ),
    (
        T,
        "    if inter_w <= 0 or inter_h <= 0:\n        return 0.0",
        "    if False:\n        return 0.0",
        "рамки, которые не пересекаются вовсе",
    ),
    # Проверки «нулевая площадь» здесь нет намеренно: она недостижима.
    # Мутант на неё выжил ровно поэтому — строка была мёртвой, и её
    # удалили. Если кто-то припишет её обратно, этот комментарий
    # объяснит, почему не надо.

    # --- скачок счётчика ---
    (
        T,
        "    if previous is None:\n        return False",
        "    if False:\n        return False",
        "первый кадр без предыдущего счёта",
    ),
    (
        T,
        "    return delta >= max(count, previous) * COUNT_JUMP_RATIO",
        "    return delta >= min(count, previous) * COUNT_JUMP_RATIO",
        "доля считается от меньшего счёта",
    ),

    # --- путь ---
    (
        T,
        '    stamp = moment.strftime("%H%M%S_%f")[:-3]',
        '    stamp = moment.strftime("%H%M%S")',
        "кадры в одной секунде затирают друг друга",
    ),
    (
        T,
        '    return f"{farm_id}/{camera_id}/{day}/{stamp}.jpg"',
        '    return f"{farm_id}/{camera_id}/{stamp}.jpg"',
        "день выпал из пути — датасет не поделить",
    ),

    # --- кадр ---
    (
        T,
        "    ok, buffer = cv2.imencode(\".jpg\", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])",
        "    frame = cv2.resize(frame, (960, 540))\n"
        "    ok, buffer = cv2.imencode(\".jpg\", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])",
        "кадр ужимается, как предпросмотр",
    ),

    # --- уборка мусорного файла ---
    (
        T,
        "    try:\n        client.storage.from_(TRAINING_BUCKET).remove([path])",
        "    try:\n        pass",
        "мусорный файл остаётся в хранилище навсегда",
    ),
    (
        T,
        "    if response.data:\n        return path",
        "    if True:\n        return path",
        "потолок ничего не значит",
    ),
]


def run_tests() -> bool:
    """True — тесты прошли."""
    # Без этого мутации ТОЙ ЖЕ ДЛИНЫ молча не применяются.
    #
    # Python решает, годен ли скомпилированный .pyc, по размеру и времени
    # правки исходника. Замена «= 60.0» на «= 10.0» не меняет размер, а
    # время правки на многих файловых системах округляется, — и
    # интерпретатор берёт СТАРЫЙ байткод. Мутант при этом выглядит
    # выжившим, хотя до кода он просто не дошёл.
    #
    # Ловилось так: мутант «пауза у кормушки равна общей» то выживал, то
    # нет от прогона к прогону, а applied вручную — честно ронял четыре
    # теста.
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

    original = open(T, encoding="utf-8").read()

    if not run_tests():
        print("Тесты не проходят ДО мутаций — чинить надо их, а не пороги")
        return 2

    survivors: list[str] = []
    missing: list[str] = []

    try:
        for path, before, after, name in MUTS:
            if before not in original:
                missing.append(name)
                print(f"  ? {name}: строка не найдена, мутация не применена")
                continue

            open(path, "w", encoding="utf-8").write(original.replace(before, after, 1))
            if run_tests():
                survivors.append(name)
                print(f"  ВЫЖИЛ  {name}")
            else:
                print(f"  убит   {name}")
    finally:
        open(T, "w", encoding="utf-8").write(original)

    print("-" * 60)
    print(f"мутантов: {len(MUTS)}, выжило: {len(survivors)}, не применено: {len(missing)}")

    if missing:
        print("\nНе применены (значит, код изменился — поправьте скрипт):")
        for name in missing:
            print(f"  {name}")

    if survivors:
        print("\nВыжившие — это непроверенные решения:")
        for name in survivors:
            print(f"  {name}")
        return 1

    if missing:
        return 1

    print("\nВсе мутанты убиты: каждый порог и каждая заслонка чем-то держатся")
    return 0


if __name__ == "__main__":
    sys.exit(main())
