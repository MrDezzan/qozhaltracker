"""
Сколько животное прошло — по камере, без носимых датчиков.

Считается по смещению точки опоры между кадрами: центр нижней грани
рамки, то есть примерно место, где животное стоит. Не центр рамки —
он уезжает вверх, когда животное поднимает голову, и вниз, когда
опускает, добавляя метры на ровном месте.

Две ловушки, из-за которых наивная сумма смещений даёт чушь.

**Дрожание.** Рамка от кадра к кадру гуляет на пару пикселей даже у
спящего животного. За сутки такой дрожи набегают километры, и в отчёте
корова, простоявшая день в углу, «прошла шесть километров». Поэтому
смещение меньше порога считается нулём.

**Подмена трека.** Трекер иногда переносит номер с одного животного на
другое — они пересеклись, одно закрыло другое. Точка опоры прыгает
через полкадра, и это выглядит как рывок на двадцать метров. Поэтому
смещение больше потолка отбрасывается целиком.

И главная оговорка, которая должна дойти до человека: **это путь в
кадре, а не весь путь животного.** Камера видит кусок загона. Сравнивать
метры между фермами бессмысленно; сравнивать животное с собой вчера —
осмысленно.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from cv_service.detector import Detection


def activity_enabled() -> bool:
    return os.environ.get("TRACK_ACTIVITY", "1").strip().lower() in {"1", "true", "yes"}


# Меньше этого считаем, что животное стоит. В сантиметрах, потому что
# порог в пикселях зависел бы от того, как высоко висит камера
MIN_STEP_CM = 15.0

# Больше этого — не шаг, а подмена трека. Корова идёт около 1,2 м/с;
# за полсекунды между опросами трекера это метр с небольшим, а не пять
MAX_STEP_CM = 500.0

# Реже этого промежутка точки не сравниваем. Между двумя соседними
# кадрами животное не успевает сдвинуться заметнее дрожания рамки
MIN_INTERVAL_S = 0.4

# Дольше этого перерыв означает, что животное уходило из кадра. Считать
# смещение через такой разрыв нельзя: между точками оно шло вне кадра,
# и прямая между ними — не его путь
MAX_GAP_S = 5.0


@dataclass
class TrackPath:
    """Путь одного трека: где видели в последний раз и сколько накопили."""

    last_x: float
    last_y: float
    last_at: float
    first_at: float
    meters: float = 0.0
    steps: int = 0


def foot_point(detection: Detection) -> tuple[float, float]:
    """Точка опоры: середина нижней грани рамки."""
    x1, _, x2, y2 = detection.bbox
    return ((x1 + x2) / 2.0, y2)


@dataclass
class ActivityTracker:
    """
    Копит путь по каждому треку и отдаёт итог, когда трек закончился.

    Без калибровки камеры не работает вовсе: `cm_per_pixel` — это то,
    что превращает пиксели в метры. Считать «активность в пикселях» и
    показывать её человеком нельзя: он прочтёт число как метры, а оно
    зависит от того, как высоко висит камера.
    """

    cm_per_pixel: float
    _paths: dict[int, TrackPath] = field(default_factory=dict)

    def add(self, detections: list[Detection], now: float) -> None:
        for detection in detections:
            if detection.group != "livestock":
                continue

            x, y = foot_point(detection)
            path = self._paths.get(detection.track_id)

            if path is None:
                self._paths[detection.track_id] = TrackPath(
                    last_x=x, last_y=y, last_at=now, first_at=now
                )
                continue

            gap = now - path.last_at
            if gap < MIN_INTERVAL_S:
                continue

            if gap > MAX_GAP_S:
                # Животное уходило из кадра. Прямая между «где было» и
                # «где появилось» — не его путь, а хорда неизвестной дуги
                path.last_x, path.last_y, path.last_at = x, y, now
                continue

            pixels = ((x - path.last_x) ** 2 + (y - path.last_y) ** 2) ** 0.5
            centimetres = pixels * self.cm_per_pixel
            path.last_x, path.last_y, path.last_at = x, y, now

            if centimetres < MIN_STEP_CM or centimetres > MAX_STEP_CM:
                continue

            path.meters += centimetres / 100.0
            path.steps += 1

    def take(self, track_id: int) -> tuple[float, int, float] | None:
        """Метры, шаги и секунды в кадре. None — трека не было."""
        path = self._paths.pop(track_id, None)
        if path is None:
            return None
        return path.meters, path.steps, max(0.0, path.last_at - path.first_at)

    def forget(self, track_id: int) -> None:
        self._paths.pop(track_id, None)

    def tracked(self) -> set[int]:
        return set(self._paths)


def describe(meters: float, seconds: float) -> str:
    """Строка для журнала."""
    minutes = seconds / 60.0
    return f"прошло {meters:.0f} м за {minutes:.0f} мин в кадре"
