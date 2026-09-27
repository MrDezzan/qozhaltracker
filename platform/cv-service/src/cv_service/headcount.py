from __future__ import annotations

import os
from dataclasses import dataclass, field

from cv_service.detector import Detection

DEFAULT_INTERVAL_S = 60.0


def headcount_interval_s() -> float:
    """Как часто писать сводку по поголовью. 0 отключает."""
    raw = os.environ.get("HEADCOUNT_INTERVAL_S", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_S


@dataclass
class HeadcountAggregator:
    """
    Копит наблюдения и раз в интервал отдаёт сводку.

    Запись на каждое обнаружение раздувает базу: пять животных при опросе
    раз в две секунды дают около 200 тысяч строк в сутки. Одна сводка
    в минуту сохраняет тот же график, но в сотни раз дешевле.
    """

    interval_s: float = DEFAULT_INTERVAL_S
    _track_ids: set[int] = field(default_factory=set)
    _class_counts: dict[str, set[int]] = field(default_factory=dict)
    _peak: int = 0
    _window_started_at: float | None = None

    def add(self, detections: list[Detection], now: float) -> None:
        if self._window_started_at is None:
            self._window_started_at = now

        for detection in detections:
            self._track_ids.add(detection.track_id)
            self._class_counts.setdefault(detection.class_name, set()).add(detection.track_id)

        self._peak = max(self._peak, len(detections))

    def due(self, now: float) -> bool:
        if self._window_started_at is None:
            return False
        return now - self._window_started_at >= self.interval_s

    def take(self) -> dict | None:
        """
        Отдаёт сводку и обнуляет окно. None, если за окно никого не видели —
        писать нули каждую минуту круглосуточно смысла нет.
        """
        if not self._track_ids:
            self._reset()
            return None

        summary = {
            "unique_count": len(self._track_ids),
            "peak_in_frame": self._peak,
            "by_class": {name: len(ids) for name, ids in self._class_counts.items()},
        }
        self._reset()
        return summary

    def _reset(self) -> None:
        self._track_ids = set()
        self._class_counts = {}
        self._peak = 0
        self._window_started_at = None
