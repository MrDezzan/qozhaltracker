from __future__ import annotations

import os

import cv2
import numpy as np

from cv_service.detector import Detection

TEXT_COLOR = (20, 20, 20)
MASK_OPACITY = 0.45

# Палитра для разных особей: цвета максимально далеки друг от друга,
# чтобы соседние животные не сливались. Цвета в порядке BGR (OpenCV).
TRACK_COLORS: list[tuple[int, int, int]] = [
    (80, 220, 100),
    (230, 120, 60),
    (70, 90, 240),
    (230, 200, 60),
    (200, 80, 220),
    (60, 210, 230),
    (150, 120, 240),
    (110, 190, 60),
    (240, 160, 120),
    (90, 160, 250),
]


def preview_enabled() -> bool:
    """Окно предпросмотра включается переменной SHOW_PREVIEW=1."""
    return os.environ.get("SHOW_PREVIEW", "").strip().lower() in {"1", "true", "yes"}


def color_for_track(track_id: int) -> tuple[int, int, int]:
    """
    Цвет закреплён за номером трека: пока животное не потерялось,
    оно остаётся того же цвета от кадра к кадру.
    """
    return TRACK_COLORS[track_id % len(TRACK_COLORS)]


# Размер клички относительно ширины кадра и рамки животного.
#
# Жёсткий размер не годится: один и тот же коэффициент даёт нечитаемые
# буквы на кадре 1920 и закрывающие полживотного — на 640. Считаем от
# кадра, но не больше, чем помещается над самим животным.
NAME_SCALE_MIN = 0.7
NAME_SCALE_MAX = 2.2


def label_scale(frame, box_width: float) -> float:
    """Насколько крупно писать кличку на этом кадре."""
    frame_width = frame.shape[1] if hasattr(frame, "shape") else 1280
    by_frame = frame_width / 900.0
    # Не шире самой рамки: подпись, вылезающая за пределы животного,
    # закрывает соседнее
    by_box = max(box_width, 1) / 220.0
    return max(NAME_SCALE_MIN, min(NAME_SCALE_MAX, min(by_frame, by_box)))


def draw_heads(frame, heads: dict[int, tuple[float, float]] | None):
    """
    Отмечает морды тех, кто сейчас ест. Координаты — доли кадра.

    Рисуется поверх контуров и нужно ровно для одного: при наведении
    камеры на кормовой стол человек должен своими глазами убедиться, что
    отметка стоит на морде, а не на ухе или на спине соседа. Без этой
    проверки ошибка в разметке зоны обнаружилась бы через две недели по
    странным отчётам о кормлении.

    Кружок с точкой в центре, а не крестик: крестик на пёстрой шкуре
    теряется, а кружок читается и на чёрной, и на белой.
    """
    if not heads:
        return frame

    height, width = frame.shape[:2]
    radius = max(6, int(min(width, height) * 0.012))

    for track_id, (x, y) in heads.items():
        centre = (int(x * width), int(y * height))
        color = color_for_track(track_id)
        # Белый кант: цвет трека может совпасть со шкурой
        cv2.circle(frame, centre, radius + 2, (255, 255, 255), 2)
        cv2.circle(frame, centre, radius, color, 2)
        cv2.circle(frame, centre, 2, color, -1)

    return frame


def draw_detections(
    frame,
    detections: list[Detection],
    names: dict[int, str] | None = None,
    heads: dict[int, tuple[float, float]] | None = None,
):
    """
    Рисует контуры животных, каждое своим цветом, и подписи.

    names — клички опознанных животных по номеру трека. Если кличка известна,
    показываем её вместо номера: фермеру нужна «Зорька», а не «#7».

    heads — морды тех, кто сейчас в кормовой зоне. Туловище и голова
    показываются ОДНОВРЕМЕННО и не заменяют друг друга: контур нужен для
    веса и промеров, отметка морды — чтобы видеть, что засчитано именно
    кормление, а не стояние рядом.

    Возвращает копию — исходный кадр не трогаем, чтобы не влиять на детекцию.
    """
    names = names or {}
    annotated = frame.copy()

    # Маски заливаем на отдельном слое и смешиваем разом:
    # так полупрозрачность не накапливается на пересечениях
    overlay = annotated.copy()
    has_masks = False

    for detection in detections:
        if not detection.mask or len(detection.mask) < 3:
            continue
        has_masks = True
        polygon = np.array([[int(x), int(y)] for x, y in detection.mask], dtype=np.int32)
        cv2.fillPoly(overlay, [polygon], color_for_track(detection.track_id))

    if has_masks:
        cv2.addWeighted(overlay, MASK_OPACITY, annotated, 1 - MASK_OPACITY, 0, annotated)

    for detection in detections:
        color = color_for_track(detection.track_id)
        x1, y1, x2, y2 = (int(v) for v in detection.bbox)

        if detection.mask and len(detection.mask) >= 3:
            polygon = np.array([[int(x), int(y)] for x, y in detection.mask], dtype=np.int32)
            cv2.polylines(annotated, [polygon], True, color, 2)
        else:
            # Модель без сегментации — остаётся обычная рамка
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        name = names.get(detection.track_id)
        label = name if name else f"#{detection.track_id} {detection.confidence:.0%}"

        # Кличку пишем крупно, номер трека — мелко.
        #
        # Смысл в том, ради чего систему покупают: хозяин хочет видеть на
        # кадре «Зорька», причём с расстояния и на телефоне. Номер трека
        # ему не нужен вовсе, он служебный, и раздувать его до того же
        # размера значит уравнять важное с шумом.
        scale, thickness = (label_scale(frame, x2 - x1), 2) if name else (0.5, 1)

        (text_w, text_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
        )
        pad = max(4, int(text_h * 0.35))

        # Подложка под текстом: на светлой шкуре белые буквы теряются,
        # на тёмной — чёрные. Плашка снимает вопрос
        cv2.rectangle(
            annotated,
            (x1, max(0, y1 - text_h - baseline - pad * 2)),
            (x1 + text_w + pad * 2, y1),
            color,
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (x1 + pad, max(text_h, y1 - baseline - pad)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            TEXT_COLOR,
            thickness,
            cv2.LINE_AA,
        )

    # Морды рисуются последними — поверх контуров и подписей. Иначе
    # отметка терялась бы под заливкой маски соседнего животного, а
    # смысл её именно в том, чтобы её было видно
    draw_heads(annotated, heads)

    counter = f"objects: {len(detections)}"
    if heads:
        counter += f"  feeding: {len(heads)}"
    cv2.putText(
        annotated,
        counter,
        (10, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        annotated, counter, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (30, 30, 30), 1, cv2.LINE_AA
    )
    return annotated


def show_frame(window_name: str, frame) -> bool:
    """
    Показывает кадр. Возвращает False, если пользователь нажал q —
    это сигнал остановить обработку.
    """
    cv2.imshow(window_name, frame)
    return cv2.waitKey(1) & 0xFF != ord("q")


def close_preview() -> None:
    cv2.destroyAllWindows()
