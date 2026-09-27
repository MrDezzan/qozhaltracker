from __future__ import annotations

import time
from dataclasses import dataclass, field

from cv_service.detector import Detection

# Визиты короче этого порога не считаем: животное просто прошло мимо
MIN_VISIT_SECONDS = 5.0

# Сколько ждать перед закрытием визита, если объект пропал из кадра.
# Трекер иногда теряет объект на кадр-другой, и без этой паузы
# один визит распался бы на десяток коротких.
LOST_GRACE_SECONDS = 10.0

# У кормушки пауза длиннее, и это не мелкая настройка.
#
# Животное ест не непрерывно: опустило голову, взяло корм, подняло,
# жуёт двадцать-тридцать секунд, снова опустило. При правильно
# поставленной камере — сбоку через кормовой стол — видно ровно голову,
# и поднятая голова выходит из зоны кормушки.
#
# С общей паузой в десять секунд получасовая кормёжка распадалась бы на
# полсотни кусков, каждый короче MIN_VISIT_SECONDS, — и почти всё это
# отбрасывалось бы. В отчёте животное, которое ело полчаса, выглядело бы
# как не евшее вовсе, а health.py объявил бы ему тревогу «мало корма».
#
# Шестьдесят секунд: длиннее любой паузы на жвачку, короче настоящего
# перерыва между кормлениями.
FEEDER_GRACE_SECONDS = 60.0

# Пауза по виду зоны. Для прохода и ворот короткая: там животное идёт
# мимо, и склеивать два прохода в один нельзя.
GRACE_BY_KIND = {
    "feeder": FEEDER_GRACE_SECONDS,
    "water": FEEDER_GRACE_SECONDS,
}


def grace_for(kind: str, default: float = LOST_GRACE_SECONDS) -> float:
    """Сколько ждать, прежде чем считать визит в зону этого вида законченным."""
    return GRACE_BY_KIND.get(kind, default)


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    kind: str
    # Координаты в долях от 0 до 1 — не зависят от разрешения камеры
    polygon: tuple[tuple[float, float], ...]


@dataclass
class Visit:
    zone: Zone
    track_id: int
    started_at: float
    last_seen_at: float
    # Где была морда в последний раз, долями кадра. Только для кормовых
    # зон и только когда модель сегментационная: у обычной контура нет
    head_point: tuple[float, float] | None = None

    @property
    def duration_s(self) -> float:
        return self.last_seen_at - self.started_at


def anchor_point(detection: Detection, frame_width: int, frame_height: int) -> tuple[float, float]:
    """
    Точка привязки — середина нижней грани рамки, то есть место,
    где животное стоит. Центр рамки давал бы ложные попадания:
    голова над кормушкой при туловище в стороне.

    Битый кадр нулевого размера не должен ронять обработку: возвращаем
    точку за пределами кадра, она заведомо не попадёт ни в одну зону.
    """
    if frame_width <= 0 or frame_height <= 0:
        return (-1.0, -1.0)

    x1, _, x2, y2 = detection.bbox
    return ((x1 + x2) / 2 / frame_width, y2 / frame_height)


# Виды зон, где решает голова, а не то, где животное стоит.
#
# Только они и бывают на камере кормушки, поэтому отдельного признака
# «это кормовая камера» не нужно: вид зоны и есть этот признак.
HEAD_KINDS = frozenset({"feeder", "water"})


def head_in_zone(
    detection: Detection,
    zone: Zone,
    frame_width: int,
    frame_height: int,
) -> tuple[float, float] | None:
    """
    Морда в зоне — или `None`, если животное до зоны не дотянулось.

    Отдельного класса «голова» у модели нет: в наборе COCO есть корова
    целиком и больше ничего. Но модель у нас сегментационная, и вместо
    рамки она даёт КОНТУР. Этого достаточно.

    Зона кормушки рисуется узкой полосой по кормовому столу, за
    решёткой. Дотянуться туда животное может только головой — туловище
    остаётся по свою сторону. Значит, точка контура, попавшая в зону, и
    есть морда, а искать её отдельной моделью незачем.

    Из попавших берём самую дальнюю от середины рамки: чем дальше точка
    силуэта от центра животного, тем это более вытянутая часть. Кончик
    морды — самая дальняя из всех.

    Возвращается точка, а не просто «да/нет», чтобы её было видно на
    кадре предпросмотра: при наведении камеры на ферме надо своими
    глазами убедиться, что отметка стоит на морде, а не на ухе.
    """
    if frame_width <= 0 or frame_height <= 0:
        return None

    mask = detection.mask
    if not mask or len(mask) < 3:
        return None

    x1, y1, x2, y2 = detection.bbox
    cx = (x1 + x2) / 2 / frame_width
    cy = (y1 + y2) / 2 / frame_height

    best: tuple[float, float] | None = None
    best_distance = -1.0

    for x, y in mask:
        point = (x / frame_width, y / frame_height)
        if not point_in_polygon(point, zone.polygon):
            continue
        distance = (point[0] - cx) ** 2 + (point[1] - cy) ** 2
        if distance > best_distance:
            best_distance = distance
            best = point

    return best


def in_zone(
    detection: Detection,
    zone: Zone,
    frame_width: int,
    frame_height: int,
) -> tuple[bool, tuple[float, float] | None]:
    """
    Внутри ли животное этой зоны. Вторым значением — точка морды, если
    зона кормовая и морда найдена.

    У кормушки и поилки решает голова, у прохода и ворот — ноги.

    ЗАПАСНОЙ ПУТЬ ВКЛЮЧАЕТСЯ ТОЛЬКО ПРИ ОТСУТСТВИИ КОНТУРА. Это главное
    место во всей функции. Если контур есть, но ни одна его точка в зону
    не попала, ответ «нет» — окончательный. Соблазн проверить заодно и
    точку под ногами выглядит безобидной подстраховкой, а на деле
    возвращает ровно ту ошибку, ради которой всё затевалось: корова,
    стоящая у кормушки и не евшая, снова засчитается как евшая.
    """
    if zone.kind not in HEAD_KINDS:
        point = anchor_point(detection, frame_width, frame_height)
        return point_in_polygon(point, zone.polygon), None

    head = head_in_zone(detection, zone, frame_width, frame_height)
    if head is not None:
        return True, head

    if detection.mask and len(detection.mask) >= 3:
        return False, None

    # Контура нет вовсе — обычная модель без сегментации. Возвращаемся к
    # прежнему поведению: при камере сбоку через стол низ рамки и так
    # приходится на морду
    point = anchor_point(detection, frame_width, frame_height)
    return point_in_polygon(point, zone.polygon), None


def point_in_polygon(point: tuple[float, float], polygon) -> bool:
    """
    Алгоритм трассировки луча: считаем пересечения горизонтального луча
    с рёбрами. Нечётное число — точка внутри.
    """
    x, y = point
    inside = False
    count = len(polygon)
    if count < 3:
        return False

    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


@dataclass
class ZoneTracker:
    """
    Следит, кто в какой зоне находится, и выдаёт завершённые визиты.

    Состояние живёт в памяти устройства: при перезапуске незакрытые
    визиты теряются. Это осознанный компромисс — иначе понадобилась бы
    запись промежуточного состояния в базу на каждом кадре.
    """

    zones: list[Zone]
    min_visit_seconds: float = MIN_VISIT_SECONDS
    lost_grace_seconds: float = LOST_GRACE_SECONDS
    _open: dict[tuple[str, int], Visit] = field(default_factory=dict)

    def set_zones(self, zones: list[Zone]) -> list[Visit]:
        """
        Обновляет список зон, не дожидаясь перезапуска: админ нарисовал
        зону — устройство подхватило её на ходу, как и новые камеры.

        Визиты в исчезнувшие зоны закрываются и возвращаются, чтобы
        накопленное время не пропало.
        """
        self.zones = zones
        alive = {zone.id for zone in zones}

        closed: list[Visit] = []
        for key, visit in list(self._open.items()):
            if visit.zone.id in alive:
                continue
            del self._open[key]
            if visit.duration_s >= self.min_visit_seconds:
                closed.append(visit)
        return closed

    def update(
        self,
        detections: list[Detection],
        frame_width: int,
        frame_height: int,
        now: float | None = None,
    ) -> tuple[list[Visit], list[Visit]]:
        """
        Возвращает пару: начавшиеся визиты и завершённые.
        Завершённые короче порога отбрасываются.
        """
        moment = time.monotonic() if now is None else now
        started: list[Visit] = []
        seen_keys: set[tuple[str, int]] = set()

        for detection in detections:
            for zone in self.zones:
                inside, head = in_zone(detection, zone, frame_width, frame_height)
                if not inside:
                    continue
                key = (zone.id, detection.track_id)
                seen_keys.add(key)
                visit = self._open.get(key)
                if visit is None:
                    visit = Visit(
                        zone=zone,
                        track_id=detection.track_id,
                        started_at=moment,
                        last_seen_at=moment,
                        head_point=head,
                    )
                    self._open[key] = visit
                    started.append(visit)
                else:
                    visit.last_seen_at = moment
                    # Голова двигается; держим последнюю известную, чтобы
                    # на кадре отметка не отставала от животного
                    if head is not None:
                        visit.head_point = head

        finished: list[Visit] = []
        for key, visit in list(self._open.items()):
            if key in seen_keys:
                continue
            # Пауза берётся по виду зоны: поднятая над кормушкой голова
            # выходит из зоны, но кормёжка при этом не кончилась
            if moment - visit.last_seen_at < grace_for(
                visit.zone.kind, self.lost_grace_seconds
            ):
                continue
            del self._open[key]
            if visit.duration_s >= self.min_visit_seconds:
                finished.append(visit)

        return started, finished

    def current_heads(self) -> dict[int, tuple[float, float]]:
        """
        Морды тех, кто прямо сейчас у корма, по номеру трека.

        Нужно для отрисовки на кадре. Если одно животное числится сразу
        в двух кормовых зонах — например, зоны нарисованы внахлёст, —
        берётся любая: на картинке это одна и та же морда.
        """
        return {
            visit.track_id: visit.head_point
            for visit in self._open.values()
            if visit.head_point is not None
        }

    def flush(self, now: float | None = None) -> list[Visit]:
        """Закрывает все открытые визиты — вызывается при остановке камеры."""
        moment = time.monotonic() if now is None else now
        finished = [
            visit
            for visit in self._open.values()
            if visit.duration_s >= self.min_visit_seconds
        ]
        self._open.clear()
        return finished


def describe_zone_change(before: list[Zone], after: list[Zone]) -> str | None:
    """
    Что именно изменилось в списке зон — чтобы в журнале было видно
    не «стало 2», а какая зона появилась или пропала.
    """
    before_ids = {zone.id: zone for zone in before}
    after_ids = {zone.id: zone for zone in after}

    added = [zone.name for zid, zone in after_ids.items() if zid not in before_ids]
    removed = [zone.name for zid, zone in before_ids.items() if zid not in after_ids]

    if not added and not removed:
        return None

    parts = []
    if added:
        parts.append("добавлены: " + ", ".join(f"«{name}»" for name in added))
    if removed:
        parts.append("удалены: " + ", ".join(f"«{name}»" for name in removed))
    return "; ".join(parts)


def parse_zones(rows: list[dict]) -> list[Zone]:
    """Строит зоны из строк БД, отбрасывая некорректные многоугольники."""
    zones: list[Zone] = []
    for row in rows:
        polygon = row.get("polygon") or []
        if not isinstance(polygon, list) or len(polygon) < 3:
            continue
        try:
            points = tuple((float(p[0]), float(p[1])) for p in polygon)
        except (TypeError, ValueError, IndexError):
            continue
        zones.append(
            Zone(
                id=str(row["id"]),
                name=str(row.get("name", "")),
                kind=str(row.get("kind", "other")),
                polygon=points,
            )
        )
    return zones
