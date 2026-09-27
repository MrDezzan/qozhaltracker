from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field

import cv2
import numpy as np

from cv_service.detector import Detection, active_profile


def weighing_enabled() -> bool:
    """Обмер силуэта можно выключить целиком, не трогая настройки камер."""
    return os.environ.get("ESTIMATE_WEIGHT", "1").strip().lower() in {"1", "true", "yes"}



# Доля кадра, ближе которой к краю измерять нельзя: часть тела уже срезана
BORDER_MARGIN = 0.02

# Минимальная площадь маски в долях кадра. Слишком далеко — контур
# рваный, и площадь скачет от кадра к кадру.
MIN_AREA_FRACTION = 0.004


@dataclass(frozen=True)
class Silhouette:
    """Один замер силуэта: площадь маски и стороны описанного прямоугольника."""

    area_px: float
    length_px: float
    width_px: float
    quality: float


def measure(
    detection: Detection,
    frame_width: int,
    frame_height: int,
    neighbours: list[Detection] | None = None,
) -> Silhouette | None:
    """
    Считает силуэт по маске сегментации.

    None означает «этот кадр для измерения не годится». Это нормальный
    исход: за визит животное попадает в кадр десятки раз, достаточно
    нескольких пригодных.
    """
    if frame_width <= 0 or frame_height <= 0:
        return None
    if not detection.mask or len(detection.mask) < 3:
        return None

    contour = np.array([[float(x), float(y)] for x, y in detection.mask], dtype=np.float32)
    area_px = float(cv2.contourArea(contour))
    if area_px <= 0:
        return None
    if area_px / (frame_width * frame_height) < MIN_AREA_FRACTION:
        return None

    (_, _), (side_a, side_b), _ = cv2.minAreaRect(contour)
    length_px = float(max(side_a, side_b))
    width_px = float(min(side_a, side_b))
    if width_px <= 0:
        return None

    subject = active_profile()
    aspect = length_px / width_px
    if aspect < subject.min_aspect or aspect > subject.max_aspect:
        return None

    quality = _quality(detection, frame_width, frame_height, neighbours or [])
    return Silhouette(
        area_px=area_px, length_px=length_px, width_px=width_px, quality=quality
    )


def _quality(
    detection: Detection,
    frame_width: int,
    frame_height: int,
    neighbours: list[Detection],
) -> float:
    """
    Насколько замеру можно верить.

    Срезанный краем кадра силуэт занижает площадь, а перекрытие соседним
    животным её завышает: две слипшиеся маски выглядят как одна большая.
    Оба случая систематические, поэтому их лучше пометить, чем усреднять.
    """
    quality = 1.0

    x1, y1, x2, y2 = detection.bbox
    margin_x = frame_width * BORDER_MARGIN
    margin_y = frame_height * BORDER_MARGIN
    touches_border = (
        x1 <= margin_x
        or y1 <= margin_y
        or x2 >= frame_width - margin_x
        or y2 >= frame_height - margin_y
    )
    if touches_border:
        quality -= 0.6

    for other in neighbours:
        if other.track_id == detection.track_id:
            continue
        if _overlap_fraction(detection.bbox, other.bbox) > 0.05:
            quality -= 0.5
            break

    return max(0.0, round(quality, 2))


def _overlap_fraction(box, other) -> float:
    """Какая доля рамки перекрыта соседней."""
    ax1, ay1, ax2, ay2 = box
    bx1, by1, bx2, by2 = other

    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    area = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    if area <= 0:
        return 0.0
    return (inter_w * inter_h) / area


@dataclass
class MorphometryCollector:
    """
    Копит замеры по трекам и отдаёт по одному итогу на трек.

    Берём медиану, а не среднее: пока животное идёт, оно нагибается,
    поворачивается и на части кадров выглядит короче. Медиана такие
    выбросы отбрасывает, среднее — размазывает.
    """

    # Меньше этого числа замеров медиана ничего не устойчивее одиночного кадра
    min_samples: int = 5
    _samples: dict[int, list[Silhouette]] = field(default_factory=dict)

    def add(self, detections: list[Detection], frame_width: int, frame_height: int) -> None:
        for detection in detections:
            silhouette = measure(detection, frame_width, frame_height, detections)
            if silhouette is None or silhouette.quality < 0.8:
                continue

            self._samples.setdefault(detection.track_id, []).append(silhouette)

    def summarize(self, track_id: int) -> Silhouette | None:
        samples = self._samples.get(track_id, [])
        if len(samples) < self.min_samples:
            return None
        return Silhouette(
            area_px=statistics.median(s.area_px for s in samples),
            length_px=statistics.median(s.length_px for s in samples),
            width_px=statistics.median(s.width_px for s in samples),
            quality=1.0,
        )

    def take(self, track_id: int) -> Silhouette | None:
        result = self.summarize(track_id)
        self._samples.pop(track_id, None)
        return result

    def forget(self, track_id: int) -> None:
        self._samples.pop(track_id, None)

    def tracked(self) -> set[int]:
        return set(self._samples)


def insert_measurement(
    client,
    farm_id: str,
    camera_id: str,
    track_id: int,
    silhouette: Silhouette,
    animal_id: str | None = None,
    sighting_id: str | None = None,
    cm_per_pixel: float | None = None,
) -> None:
    row = {
        "farm_id": farm_id,
        "camera_id": camera_id,
        "track_id": track_id,
        "area_px": round(silhouette.area_px, 1),
        "length_px": round(silhouette.length_px, 1),
        "width_px": round(silhouette.width_px, 1),
        "quality": silhouette.quality,
    }
    if animal_id:
        row["animal_id"] = animal_id
    if sighting_id:
        row["sighting_id"] = sighting_id
    if cm_per_pixel:
        # Сантиметры считаем здесь и храним отдельными колонками, а не
        # на лету при чтении: камеру могут перекалибровать, а измерение
        # должно остаться таким, каким было сделано
        row["cm_per_pixel"] = cm_per_pixel
        row["length_cm"] = round(silhouette.length_px * cm_per_pixel, 1)
        row["width_cm"] = round(silhouette.width_px * cm_per_pixel, 1)

    client.table("body_measurements").insert(row).execute()
