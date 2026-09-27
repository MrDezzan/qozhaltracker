"""
Мутационная проверка раздачи кличек по кадру.

Запуск из корня проекта:

    python3 cv-service/scripts/mutate_identity.py

Каждая строка ниже портит одно решение в identity.py и прогоняет тесты.
Тест обязан упасть. Выживший мутант означает, что решение можно менять
как угодно и никто не заметит, — то есть оно не проверено.

Здесь это важнее, чем где-либо ещё в сервисе. Ошибка узнавания не падает
с исключением и не пишет в журнал слово «ошибка». Она просто ставит
чужую кличку над животным — и увидеть это можно только глазами по видео,
через неделю, когда в отчёте Зорька окажется в двух загонах сразу.
"""

import os
import pathlib
import shutil
import subprocess
import sys

CV = "cv-service"
TARGET = f"{CV}/src/cv_service/identity.py"
TESTS = ["tests/test_identity.py"]

MUTS = [
    # --- одна кличка — один трек ---
    # Мутант «колонка „новый“ одна на всех» отсюда убран: он выживает и
    # выживает честно. Трек, которому не досталось НИ ОДНОЙ колонки,
    # венгерка оставляет без назначения, а такой трек мы считаем
    # неузнанным — ровно как и трек, ушедший в колонку «новый». Снаружи
    # разницы нет, убить мутанта нечем.
    #
    # Колонок всё равно столько, сколько треков: полагаться на то, что
    # «без назначения» и «новый» совпали, значит полагаться на
    # случайность реализации scipy, а не на своё решение.
    (
        "                if занято.get(c.animal_id, s.track_id) == s.track_id",
        "                if True",
        "кличка, занятая другим треком, снова доступна",
    ),
    (
        "                if занято.get(c.animal_id, s.track_id) == s.track_id",
        "                if занято.get(c.animal_id) is None",
        "свой трек теряет собственную кличку",
    ),
    (
        "                and c.distance <= threshold",
        "                and True",
        "далёкие кандидаты доходят до раздачи",
    ),

    # --- отрыв считается по кадру ---
    (
        "        if отрыв < нужно:",
        "    if False:",
        "спорное совпадение называется как уверенное",
    ),
    (
        "        seen, animals, threshold, forbidden=(row, col), must_name=row",
        "        seen, animals, threshold, forbidden=(row, col)",
        "отрыв меряется от отказа, а не от следующего кандидата",
    ),
    (
        "    if другой >= _forbidden_cost(threshold):\n        return float(\"inf\")",
        "    if False:\n        return float(\"inf\")",
        "единственный кандидат считается спорным",
    ),
    # Мутант «значение forbidden по умолчанию» отсюда убран намеренно:
    # оно всегда перекрывается вызовом из `_gap`, и любая его порча
    # равносильна исходному коду. Убить такого нечем, и держать его в
    # списке значит каждый раз объяснять себе, почему он выжил.

    # --- порог ---
    (
        "            if цена is None or forbidden == (i, j):",
        "            if цена is None:",
        "запрещённая пара всё равно рассматривается",
    ),
    (
        "def dummy_cost(threshold: float) -> float:\n    return float(threshold)",
        "def dummy_cost(threshold: float) -> float:\n    return float(threshold) * 100",
        "отказ называть стал дороже любого совпадения",
    ),

    # --- что кладём в эталоны ---
    (
        "    if verdict.quality != STRONG or not verdict.animal_id:",
        "    if False:",
        "в эталоны попадает и неуверенно узнанное",
    ),
    (
        "    if voted:",
        "    if False:",
        "в эталоны попадает узнанное с переспроса",
    ),
    (
        "    if verdict.distance is not None and verdict.distance < DUP_DISTANCE:",
        "    if False:",
        "тот же ракурс запоминается снова и вытесняет другие",
    ),
    (
        "    if not crop_ok:",
        "    if False:",
        "в эталоны попадает негодный кадр",
    ),
    (
        "DUP_DISTANCE = 0.08",
        "DUP_DISTANCE = 0.34",
        "почти всё считается уже известным ракурсом",
    ),

    # --- когда заводить новую особь ---
    (
        "    if threshold < nearest <= threshold + NEAR_MISS:\n        return base * NEAR_MISS_PATIENCE",
        "    if False:\n        return base * NEAR_MISS_PATIENCE",
        "двойник заводится с первого раза",
    ),
    (
        "NEAR_MISS_PATIENCE = 3",
        "NEAR_MISS_PATIENCE = 1",
        "терпения в полосе «почти узнали» не прибавилось",
    ),
    (
        "    if nearest is None:\n        return base",
        "    if nearest is None:\n        return base * NEAR_MISS_PATIENCE",
        "молчание базы ужесточает правила",
    ),
    (
        "NEAR_MISS = 0.10",
        "NEAR_MISS = 0.0",
        "полосы «почти узнали» больше нет",
    ),

    # --- качество кадра как вес ---
    (
        "        нужно = margin_needed(min_margin, наблюдение.quality)",
        "        нужно = min_margin",
        "качество кадра не влияет на требуемый отрыв",
    ),
    (
        "QUALITY_PENALTY = 2.0",
        "QUALITY_PENALTY = 1.0",
        "плохой кадр доказывает столько же, сколько хороший",
    ),
    (
        "    испорчено = 1.0 - min(1.0, max(0.0, quality))",
        "    испорчено = 1.0 - quality",
        "качество вне 0..1 ломает требуемый отрыв",
    ),
    (
        "    видно = min(1.0, max(0.0, area) / GOOD_AREA_PX)",
        "    видно = 1.0",
        "размер животного перестал влиять на доверие",
    ),
    (
        "    return видно * min(1.0, max(0.0, confidence)) * min(1.0, max(0.0, clarity))",
        "    return видно * min(1.0, max(0.0, confidence))",
        "резкость перестала влиять на доверие",
    ),
]


# Сколько ждать один прогон. Мутант, который не роняет тесты, а ВЕШАЕТ
# их, — это тоже находка: значит, испорченное решение уводит код в
# бесконечный цикл. Без предела такой мутант съедает весь прогон, и
# остальные проверки просто не выполняются
RUN_TIMEOUT_S = 60


def run_tests() -> bool | None:
    """True — тесты прошли, False — упали, None — зависли."""
    # Чистка кэша обязательна: Python решает годность .pyc по размеру и
    # времени правки, а замена одинаковой длины ни того, ни другого не
    # меняет — и мутант выглядит выжившим, не дойдя до кода
    for cache in pathlib.Path(CV).rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join(
            filter(None, ["src", os.environ.get("PYTHONPATH", "")])
        ),
        PYTHONDONTWRITEBYTECODE="1",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
            cwd=CV,
            capture_output=True,
            env=env,
            timeout=RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    return result.returncode == 0


def main() -> int:
    original = open(TARGET, encoding="utf-8").read()

    # Копия на диске, а не только в памяти.
    #
    # `finally` не отрабатывает, когда процесс УБИВАЮТ: прогон под
    # `timeout` оборвался, и файл остался мутантом. Дальше падали уже
    # свои же тесты, и выглядело это как «сломался код», а не «скрипт
    # не убрал за собой».
    запасная = TARGET + ".before-mutation"
    open(запасная, "w", encoding="utf-8").write(original)

    if run_tests() is not True:
        print("Тесты не проходят ДО мутаций — чинить надо их, а не пороги")
        print(f"Если прошлый прогон убили, целый файл лежит рядом: {запасная}")
        return 2

    survivors: list[str] = []
    missing: list[str] = []
    hung: list[str] = []

    try:
        for before, after, name in MUTS:
            if original.count(before) != 1:
                missing.append(name)
                print(f"  ? {name}: совпадений {original.count(before)}, не применено")
                continue

            open(TARGET, "w", encoding="utf-8").write(
                original.replace(before, after, 1)
            )
            исход = run_tests()
            if исход is None:
                hung.append(name)
                print(f"  ЗАВИС  {name}")
            elif исход:
                survivors.append(name)
                print(f"  ВЫЖИЛ  {name}")
            else:
                print(f"  убит   {name}")
    finally:
        open(TARGET, "w", encoding="utf-8").write(original)
        os.remove(запасная)

    print("-" * 60)
    print(
        f"мутантов: {len(MUTS)}, выжило: {len(survivors)}, "
        f"не применено: {len(missing)}"
    )

    if missing:
        print("\nНе применены (код изменился — поправьте скрипт):")
        for name in missing:
            print(f"  {name}")

    if hung:
        print("\nЗависли — испорченное решение уводит код в бесконечный цикл:")
        for name in hung:
            print(f"  {name}")

    if survivors:
        print("\nВыжившие — это непроверенные решения:")
        for name in survivors:
            print(f"  {name}")
        return 1

    return 1 if (missing or hung) else 0


if __name__ == "__main__":
    sys.exit(main())
