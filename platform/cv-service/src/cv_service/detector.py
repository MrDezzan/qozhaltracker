from __future__ import annotations

import os
from dataclasses import dataclass

from ultralytics import YOLO

from cv_service import profile as _profile

# Классы, которые считаем скотом.
#
# Модель обучена на наборе COCO, и отдельного класса для козы, верблюда
# или яка там нет. На практике это значит:
#
#   cow    — крупный рогатый скот, а также яки и часто козы покрупнее
#   sheep  — овцы и козы: модель их почти не различает, и это нормально,
#            в Казахстане мелкий рогатый скот обычно считают вместе
#   horse  — лошади, ослы, мулы
#
# Верблюдов COCO не знает вовсе — на верблюжьей ферме нужна своя модель.
#
# Чего здесь намеренно нет:
#   bird       — вороны и голуби над загоном раздули бы поголовье. Для
#                птицефермы включается отдельно: TRACKED_CLASSES=bird
#   dog, cat   — собака у кормушки записалась бы как визит животного
#   person     — люди в поголовье не нужны. Для отладки на ноутбучной
#                камере ставится вручную, но на ферме это ошибка
DEFAULT_TRACKED_CLASS_NAMES = frozenset({"cow", "sheep", "horse"})

# Понятное имя для того же набора: ниже он противопоставляется охране,
# и «DEFAULT_TRACKED» в этом месте читается хуже
LIVESTOCK_CLASS_NAMES = DEFAULT_TRACKED_CLASS_NAMES

# Настройки, которые годятся только для проверки на столе
DEBUG_ONLY_CLASSES = frozenset({"person"})

# ---------------------------------------------------------------------------
# Охрана: люди и техника
# ---------------------------------------------------------------------------
# Это ОТДЕЛЬНЫЙ набор, а не расширение списка скота, и разделение здесь
# принципиально. Стоит человеку попасть в общий поток — и он войдёт в
# поголовье, его стояние у кормушки запишется как кормление, его силуэт
# уйдёт в обучающую выборку для веса, а его лицо — в базу векторов
# признаков, где ему уж точно не место.
#
# Модель вызывается один раз на оба набора: второго прохода не нужно,
# разделение делается по имени класса уже после детекции.
SECURITY_CLASS_NAMES = frozenset({"person", "car", "truck", "bus", "motorcycle"})

LIVESTOCK = "livestock"
SECURITY = "security"

# Действующий профиль: кого считаем подопечным.
#
# Один набор на всю систему. Разделение классов происходит в десятке
# мест, и протаскивать эти списки через каждое — верный способ однажды
# забыть про одно из них и получить человека в поголовье.
#
# Читается из окружения один раз при загрузке модуля.
_ACTIVE = _profile.resolve()


def active_profile():
    return _ACTIVE


def reload_profile() -> None:
    """Перечитать `.env`. Нужно тестам и запуску из отладочного режима."""
    global _ACTIVE
    _ACTIVE = _profile.resolve()


def class_group(class_name: str) -> str:
    """
    Животное или охрана.

    Решение принимается в одном месте, а не по жёсткому списку в каждом:
    наборы классов настраиваются под хозяйство, и разойтись они не
    должны.
    """
    if class_name in _ACTIVE.subject_classes:
        return LIVESTOCK
    if class_name in _ACTIVE.security_classes:
        return SECURITY
    # Незнакомый класс считаем животным: наборы настраиваются под
    # хозяйство, и на верблюжьей ферме появится свой класс. Отнести
    # незнакомое к охране означало бы поднимать тревогу на верблюда
    return LIVESTOCK


def security_enabled() -> bool:
    """
    Охрана включается явно.

    По умолчанию выключена не из осторожности к коду, а по закону: снимать
    людей нельзя, пока на ферме не оформлены приказ, ознакомление под
    роспись и таблички на входах.
    """
    return os.environ.get("SECURITY_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def split_by_group(detections: list["Detection"]) -> tuple[list["Detection"], list["Detection"]]:
    """
    Разделяет находки на скот и охрану.

    Отдельная функция, а не два условия по месту: так это проверяется
    тестом, и так видно, что список ровно один и делится он ровно надвое.
    """
    livestock = [d for d in detections if d.group == LIVESTOCK]
    security = [d for d in detections if d.group == SECURITY]
    return livestock, security


def get_tracked_class_names() -> frozenset[str]:
    """
    Какие классы модель вообще отслеживает.

    COUNT_PEOPLE добавляет человека к этому списку в самом конце, что бы
    ни стояло в TRACKED_CLASSES. Иначе выходила молчаливая ловушка: в
    `.env` перечислен скот, человек в список не попадает, из охраны он
    при этом уже убран — и включённый режим людей не находит никого,
    ничего об этом не сказав.
    """
    raw = os.environ.get("TRACKED_CLASSES", "").strip()
    names = {part.strip().lower() for part in raw.split(",") if part.strip()}

    if not names:
        return _ACTIVE.subject_classes

    # Отладочная настройка, забытая в .env, — тихая беда: система работает,
    # а скот не считает вовсе. Пусть говорит об этом вслух
    debug = names & DEBUG_ONLY_CLASSES & _ACTIVE.security_classes
    if debug:
        print(
            f"ВНИМАНИЕ: в TRACKED_CLASSES стоит {', '.join(sorted(debug))} — "
            "это настройка для проверки на столе. На ферме скот считаться не будет"
        )

    return frozenset(names) | (_ACTIVE.subject_classes & {"person"})


@dataclass
class Detection:
    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]
    # Контур животного в пикселях. Есть только у сегментационных моделей;
    # у обычных остаётся None, и рисуется прямоугольник.
    mask: list[tuple[float, float]] | None = None

    @property
    def group(self) -> str:
        """`livestock` или `security`. Выводится из класса, а не хранится:
        одно поле меньше — одна возможность рассогласования меньше."""
        return class_group(self.class_name)


class Detector:
    def __init__(
        self,
        model_path: str | None = None,
        tracked_classes: frozenset[str] | None = None,
    ):
        # Сегментационная модель по умолчанию: она даёт контур животного,
        # а не только рамку, и картинка сразу читается как на скриншотах.
        model_path = model_path or os.environ.get("YOLO_MODEL", "yolov8n-seg.pt")
        self.model = YOLO(model_path)
        self.tracked_classes = tracked_classes or get_tracked_class_names()
        # Классы охраны добавляются к отслеживаемым, только когда охрана
        # включена. Иначе модель считала бы людей впустую, а разделять их
        # было бы некому — и они попали бы в поголовье
        if security_enabled():
            self.tracked_classes = self.tracked_classes | _ACTIVE.security_classes

    def detect_and_track(self, frame) -> list[Detection]:
        results = self.model.track(frame, persist=True, verbose=False)[0]
        detections: list[Detection] = []
        if results.boxes is None or results.boxes.id is None:
            return detections

        polygons = _extract_polygons(results)

        for index, (box, track_id, cls_idx, conf) in enumerate(zip(
            results.boxes.xyxy.tolist(),
            results.boxes.id.tolist(),
            results.boxes.cls.tolist(),
            results.boxes.conf.tolist(),
        )):
            class_name = self.model.names[int(cls_idx)]
            if class_name not in self.tracked_classes:
                continue
            detections.append(
                Detection(
                    track_id=int(track_id),
                    class_name=class_name,
                    confidence=float(conf),
                    bbox=tuple(box),
                    mask=polygons[index] if index < len(polygons) else None,
                )
            )
        return detections


def _extract_polygons(results) -> list[list[tuple[float, float]]]:
    """Контуры из сегментационной модели. У обычной их просто нет."""
    masks = getattr(results, "masks", None)
    if masks is None:
        return []
    try:
        return [[(float(x), float(y)) for x, y in polygon] for polygon in masks.xy]
    except (TypeError, ValueError):
        return []
