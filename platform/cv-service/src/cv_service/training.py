"""
Сбор кадров для дообучения.

Отличается от `snapshot.py` тремя вещами, и каждая из них — причина, по
которой снимки предпросмотра для обучения не годятся:

  1. кадр сохраняется ЧИСТЫМ, до отрисовки контуров. На картинке с
     нарисованными рамками модель научится искать зелёные линии;
  2. путь у каждого кадра свой, с датой. Снимок предпросмотра лежит по
     постоянному пути и перезаписывается каждые пятнадцать секунд —
     накопить съёмку за две недели физически невозможно;
  3. кадр не уменьшается. Предпросмотр жмётся до 960 пикселей, потому
     что его смотрят с телефона. Для обучения важен каждый пиксель:
     животное в дальнем углу загона и так занимает их мало.

Сбор включается на срок и выключается САМ. Это не удобство, а защита:
включённый и забытый сбор за месяц даёт под сто тысяч файлов с одной
камеры, и узнают об этом по счёту за хранилище.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

import cv2

TRAINING_BUCKET = "training"

# ---------------------------------------------------------------------------
# Отбор кадров
# ---------------------------------------------------------------------------
# Размечать случайные кадры — потратить месяц и получить пару процентов:
# соседние кадры почти одинаковы, и модель полторы тысячи раз увидит одно
# и то же. Отбирать надо там, где модель ошибается.

# Полоса сомнения. Ниже неё модель уверена, что перед ней не животное,
# выше — уверена, что животное. Интересна середина
DOUBT_LOW = 0.30
DOUBT_HIGH = 0.60

# Насколько должен измениться счётчик, чтобы счесть это скачком.
#
# Два условия сразу: и доля, и абсолютное число. Без доли на большом
# стаде сработает любое движение — из сорока животных два всегда кого-то
# заслоняют. Без абсолютного минимума на маленьком сработает переход с
# одного животного на два, а это норма, а не сбой
COUNT_JUMP_RATIO = 0.25
COUNT_JUMP_MIN = 2

# Доля пересечения рамок, после которой считаем, что животные стоят
# вплотную.
#
# Важная тонкость: это НЕ обнаружение слипшихся масок. Когда модель
# слепила двух животных в одно, мы видим одну рамку и заметить это по
# пересечениям нельзя — такой случай проявляется как падение счётчика.
# Здесь ловится зона риска: животные стоят так тесно, что модель вот-вот
# перестанет их разделять
CROWD_OVERLAP = 0.35

# Каждый N-й кадр берётся просто так, без повода.
#
# Без обычных кадров датасет состоит из одних трудных случаев, и модель
# разучится работать в лёгких условиях. В документе это «четверть кадров
# — обычные дневные для равновесия»
ROUTINE_EVERY = 8

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL_S = 30.0
DEFAULT_DAILY_CAP = 200
DEFAULT_QUALITY = 92


def collect_until() -> date | None:
    """
    Дата, до которой идёт сбор, включительно. `None` — сбор выключен.

    Пустое и непонятное значение означают ВЫКЛЮЧЕНО. Это осознанно:
    опечатка в дате не должна включать сбор навсегда. Молчаливое «собираю
    вечно» обнаружилось бы через месяц по размеру хранилища.
    """
    raw = os.environ.get("TRAINING_COLLECT_UNTIL", "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def collecting(today: date | None = None) -> bool:
    """Идёт ли сбор сегодня."""
    until = collect_until()
    if until is None:
        return False
    return (today or datetime.now(timezone.utc).date()) <= until


def interval_s() -> float:
    """Как часто брать кадр. Реже, чем работает обработка: соседние
    кадры почти одинаковы и место занимают зря."""
    raw = os.environ.get("TRAINING_INTERVAL_S", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_S
    return value if value > 0 else DEFAULT_INTERVAL_S


def daily_cap() -> int:
    """
    Потолок кадров в сутки на камеру. Второй рубеж после срока: даже
    если срок выставили на год по ошибке, объём остаётся предсказуемым.
    """
    raw = os.environ.get("TRAINING_DAILY_CAP", "").strip()
    if not raw:
        return DEFAULT_DAILY_CAP
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_DAILY_CAP
    return value if value > 0 else DEFAULT_DAILY_CAP


# ---------------------------------------------------------------------------
# Правила отбора
# ---------------------------------------------------------------------------


def _overlap(first, second) -> float:
    """
    Доля пересечения двух рамок от площади меньшей из них.

    Именно от меньшей, а не от объединения: телёнок рядом с коровой даёт
    маленькое пересечение относительно суммы, но может быть перекрыт ею
    почти целиком. Опасен как раз второй случай.
    """
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second

    inter_w = min(ax2, bx2) - max(ax1, bx1)
    inter_h = min(ay2, by2) - max(ay1, by1)
    if inter_w <= 0 or inter_h <= 0:
        return 0.0

    # Проверки на нулевую площадь здесь НЕ НУЖНО, и это стоит объяснить,
    # иначе её припишет обратно первый же читающий.
    #
    # `inter_w > 0` означает min(ax2,bx2) > max(ax1,bx1), а отсюда сразу
    # ax2 > ax1 и bx2 > bx1. То же по вертикали. То есть до этой строки
    # доходят только рамки с заведомо положительной площадью, и делить
    # на ноль тут не на чем. Вырожденные рамки отсекает возврат выше.
    inter = inter_w * inter_h
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / min(area_a, area_b)


def has_doubt(detections) -> bool:
    """Есть ли обнаружение, в котором модель сомневалась."""
    return any(DOUBT_LOW <= d.confidence <= DOUBT_HIGH for d in detections)


def is_crowded(detections) -> bool:
    """Стоят ли животные вплотную."""
    boxes = [d.bbox for d in detections]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i], boxes[j]) >= CROWD_OVERLAP:
                return True
    return False


def count_jumped(count: int, previous: int | None) -> bool:
    """Скакнул ли счётчик по сравнению с прошлым разом."""
    if previous is None:
        return False
    delta = abs(count - previous)
    if delta < COUNT_JUMP_MIN:
        return False
    return delta >= max(count, previous) * COUNT_JUMP_RATIO


def pick_reason(
    detections,
    previous_count: int | None = None,
    index: int = 0,
) -> str | None:
    """
    Почему этот кадр стоит сохранить. `None` — не стоит.

    Порядок проверок — по тяжести последствий. Слипшиеся животные портят
    и подсчёт, и обмер силуэта; скачок счётчика напрямую завышает
    поголовье в отчёте; сомнение модели — самый мягкий случай.
    """
    if not detections:
        # Пустой кадр не сохраняем НИКОГДА, даже по очереди `routine`.
        # Камера над пустым загоном ночью иначе выберет весь суточный
        # потолок кадрами, на которых нечего размечать
        return None

    if is_crowded(detections):
        return "crowded"
    if count_jumped(len(detections), previous_count):
        return "count_jump"
    if has_doubt(detections):
        return "low_confidence"
    if index % ROUTINE_EVERY == 0:
        return "routine"
    return None


# ---------------------------------------------------------------------------
# Файл
# ---------------------------------------------------------------------------


def training_path(farm_id: str, camera_id: str, when: datetime | None = None) -> str:
    """
    Путь кадра: ферма / камера / день / метка времени.

    День отдельным сегментом не для порядка, а ради деления датасета.
    Обучение и проверку делят ПО ДНЯМ: кадры, снятые с разницей в
    секунду, почти одинаковы, и при случайном делении почти у каждого
    кадра обучающей части есть близнец в проверочной. Модель показывает
    98% точности, а на новой ферме не работает.
    """
    moment = when or datetime.now(timezone.utc)
    day = moment.strftime("%Y-%m-%d")
    stamp = moment.strftime("%H%M%S_%f")[:-3]
    return f"{farm_id}/{camera_id}/{day}/{stamp}.jpg"


def encode_training_frame(frame, quality: int = DEFAULT_QUALITY) -> bytes:
    """
    Кадр в JPEG БЕЗ уменьшения.

    Предпросмотр жмётся до 960 пикселей по ширине, и для телефона это
    правильно. Здесь наоборот: животное в дальнем углу загона занимает
    мало пикселей, и выбрасывать их — значит собирать датасет, на
    котором модель не научится тому, ради чего всё затевалось.
    """
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Не удалось закодировать кадр обучения в JPEG")
    return buffer.tobytes()


def describe(detections, width: int = 0, height: int = 0) -> dict:
    """
    Что модель нашла — для экрана отбраковки.

    Рамки хранятся ЗДЕСЬ, а не рисуются на кадре, и это главное решение
    во всём модуле. Кадр в хранилище обязан остаться чистым, иначе он
    непригоден для обучения. А админу надо видеть, что именно система
    нашла, — без этого отбраковка превращается в гадание.

    Поэтому рамки уходят в базу числами, а браузер накладывает их поверх
    картинки. Один и тот же файл оказывается и обучающим кадром, и
    иллюстрацией.

    Координаты доля от размера кадра, а не пиксели: экран показывает
    картинку в любом размере, от телефона до монитора, и пиксели пришлось
    бы пересчитывать на каждом.
    """
    confidences = sorted(round(float(d.confidence), 3) for d in detections)
    classes: dict[str, int] = {}
    for d in detections:
        classes[d.class_name] = classes.get(d.class_name, 0) + 1

    boxes = []
    if width > 0 and height > 0:
        for d in detections:
            x1, y1, x2, y2 = d.bbox
            boxes.append({
                "x": round(x1 / width, 4),
                "y": round(y1 / height, 4),
                "w": round((x2 - x1) / width, 4),
                "h": round((y2 - y1) / height, 4),
                "c": round(float(d.confidence), 3),
                "n": d.class_name,
            })

    return {
        "count": len(detections),
        "classes": classes,
        "confidences": confidences,
        "min_confidence": confidences[0] if confidences else None,
        "boxes": boxes,
    }


def upload_training_frame(
    client,
    farm_id: str,
    camera_id: str,
    frame,
    reason: str,
    detections,
    when: datetime | None = None,
    cap: int | None = None,
) -> str | None:
    """
    Кладёт кадр в хранилище и записывает строку в базу.

    Возвращает путь или `None`, если суточный потолок уже выбран. Именно
    `None`, а не исключение: для устройства это штатная ситуация, и
    ронять из-за неё обработку видео нельзя.

    Порядок обратный привычному — сначала файл, потом строка в базе.
    Иначе при обрыве связи в базе осталась бы запись о кадре, которого
    в хранилище нет, и экран отбраковки показал бы пустую картинку.
    """
    path = training_path(farm_id, camera_id, when)
    payload = encode_training_frame(frame)
    height, width = frame.shape[:2]

    client.storage.from_(TRAINING_BUCKET).upload(
        path=path,
        file=payload,
        file_options={"content-type": "image/jpeg", "upsert": "false"},
    )

    response = client.rpc(
        "add_training_frame",
        {
            "p_camera_id": camera_id,
            "p_path": path,
            "p_reason": reason,
            "p_detections": describe(detections, width, height),
            "p_daily_cap": cap if cap is not None else daily_cap(),
        },
    ).execute()

    if response.data:
        return path

    # Потолок выбран. Файл уже в хранилище, а строки в базе нет — такой
    # файл невидим ниоткуда и остался бы лежать навсегда, занимая место
    # и не попадая ни в один датасет. Убираем сразу
    try:
        client.storage.from_(TRAINING_BUCKET).remove([path])
    except Exception:
        # Не смогли убрать — это неприятно, но ронять из-за мусорного
        # файла обработку видео нельзя
        pass
    return None
