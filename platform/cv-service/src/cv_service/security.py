"""
Тревога о постороннем на территории.

Охрана работает КРУГЛОСУТОЧНО. Воруют и среди бела дня, а на дальнем
загоне человек днём так же неуместен, как ночью.

Но и одинаково громко кричать сутки напролёт нельзя: днём по ферме ходят
свои — доярки, скотник, ветврач, водитель кормовоза. Система, которая
тревожит на каждого, через неделю перестаёт читаться и оказывается
бесполезной ровно в ту ночь, ради которой её ставили.

Поэтому время суток определяет не «работает или нет», а строгость:

  охранные часы  — «срочно», выдержка 5 секунд, пауза 15 минут;
  прочее время   — «внимание», выдержка 30 секунд, пауза час.

Тридцать секунд днём — это уже не «прошёл мимо», а «стоит и что-то
делает». Для камер, где людей не должно быть никогда (склад, дальний
загон, топливная ёмкость), есть режим `always`: там всегда «срочно».

Остальные условия, каждое против своего рода ложных срабатываний:

  - охрана включена на этой камере (у кормового стола она не нужна);
  - человек внутри обведённого периметра, если тот нарисован
    (иначе сработает на прохожего на дороге за забором);
  - человек держится в кадре (одиночная осечка модели живёт один кадр).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Срочность дневной тревоги. 'off' означает «не поднимать вовсе».
DAY_SEVERITIES = ("off", "info", "warning", "danger")


@dataclass
class GuardSettings:
    """
    Настройки охраны фермы. Значения по умолчанию совпадают с базой.

    Охранные часы означают ПОВЫШЕННУЮ СТРОГОСТЬ, а не единственное время
    работы охраны. Днём система смотрит тоже — просто ждёт дольше и
    поднимает тревогу мягче: днём по ферме ходят свои, и тревога на
    каждого приучает не читать тревоги.
    """

    guard_from: time = time(22, 0)
    guard_to: time = time(6, 0)
    min_seconds: float = 5.0
    cooldown_minutes: float = 15.0
    clear_minutes: float = 10.0
    # Дневной режим
    day_severity: str = "warning"
    day_min_seconds: float = 30.0
    day_cooldown_minutes: float = 60.0
    timezone_name: str = "Asia/Almaty"

    @classmethod
    def from_row(cls, row: dict | None, timezone_name: str | None = None) -> "GuardSettings":
        row = row or {}
        severity = str(row.get("guard_day_severity") or "warning")
        return cls(
            guard_from=parse_time(row.get("guard_from"), time(22, 0)),
            guard_to=parse_time(row.get("guard_to"), time(6, 0)),
            min_seconds=float(row.get("intruder_min_seconds") or 5),
            cooldown_minutes=float(row.get("intruder_cooldown_minutes") or 15),
            clear_minutes=float(row.get("intruder_clear_minutes") or 10),
            day_severity=severity if severity in DAY_SEVERITIES else "warning",
            day_min_seconds=float(row.get("intruder_day_min_seconds") or 30),
            day_cooldown_minutes=float(row.get("intruder_day_cooldown_minutes") or 60),
            timezone_name=timezone_name or "Asia/Almaty",
        )


def parse_time(raw, fallback: time) -> time:
    """Время из базы приходит как «22:00:00»."""
    if isinstance(raw, time):
        return raw
    if not raw:
        return fallback
    parts = str(raw).split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return fallback
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return fallback
    return time(hour, minute)


def in_guard_window(now: time, start: time, end: time) -> bool:
    """
    Попадает ли момент в охранное окно.

    Окно по умолчанию 22:00–06:00, то есть start > end. Наивная проверка
    `start <= now <= end` даёт для него пустое множество, и охрана молча
    не работает НИКОГДА — при этом всё выглядит настроенным. Это самая
    вероятная ошибка во всём модуле, поэтому она вынесена в отдельную
    функцию с тестами на оба случая.
    """
    if start == end:
        return True                       # круглосуточно
    if start < end:
        return start <= now < end         # обычное окно внутри суток
    return now >= start or now < end      # окно через полночь


def farm_now(timezone_name: str, moment: datetime | None = None) -> datetime:
    """
    Местное время фермы.

    Не время сервера: он может стоять где угодно, а «ночь» — понятие
    местное. Неизвестный пояс не должен ронять охрану, поэтому падаем
    на UTC и работаем дальше.
    """
    moment = moment or datetime.now(timezone.utc)
    try:
        return moment.astimezone(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, ValueError):
        return moment.astimezone(timezone.utc)


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Луч вправо: нечётное число пересечений — точка внутри."""
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def foot_point(bbox: tuple[float, float, float, float], width: int, height: int):
    """
    Нижняя середина рамки в долях кадра.

    Именно ноги, а не центр: человек стоит на земле, и попадание в зону
    определяется тем, где он стоит, а не где у него голова.
    """
    x1, _, x2, y2 = bbox
    if width <= 0 or height <= 0:
        return None
    return ((x1 + x2) / 2 / width, y2 / height)


@dataclass
class CameraGuardState:
    """Что модуль помнит про одну камеру между кадрами."""

    first_seen_at: float | None = None
    last_seen_at: float | None = None
    alert_open: bool = False
    last_alert_at: float | None = None
    persons: int = 0


@dataclass
class GuardDecision:
    """Что делать по итогам кадра."""

    raise_alert: bool = False
    resolve_alert: bool = False
    seconds_present: float = 0.0
    persons: int = 0
    severity: str = "danger"
    # Пришлась тревога на охранные часы или на обычное время. Нужно, чтобы
    # в интерфейсе не пришлось гадать, почему одна «срочно», а другая нет
    at_night: bool = True


@dataclass
class GuardThresholds:
    """Насколько строго смотрим прямо сейчас."""

    severity: str
    min_seconds: float
    cooldown_minutes: float
    at_night: bool

    @property
    def enabled(self) -> bool:
        return self.severity != "off"


def thresholds_for(
    settings: GuardSettings,
    moment: datetime | None = None,
    mode: str = "schedule",
) -> GuardThresholds:
    """
    Строгость на текущий момент.

    Охрана работает круглосуточно. Время суток и режим камеры определяют,
    насколько долго ждать и насколько громко сообщать:

      охранные часы — «срочно», выдержка 5 секунд;
      прочее время  — «внимание», выдержка 30 секунд;
      режим always  — «срочно» всегда, независимо от времени.

    Тридцать секунд днём — это уже не «прошёл мимо», а «стоит и что-то
    делает». Именно это стоит показать хозяину, не поднимая его с места.
    """
    local = farm_now(settings.timezone_name, moment)
    night = in_guard_window(local.time(), settings.guard_from, settings.guard_to)

    # Камера, где людей не должно быть никогда: дальний загон, склад,
    # топливная ёмкость. Там день ничем не отличается от ночи
    if mode == "always":
        return GuardThresholds(
            severity="danger",
            min_seconds=settings.min_seconds,
            cooldown_minutes=settings.cooldown_minutes,
            at_night=night,
        )

    if night:
        return GuardThresholds(
            severity="danger",
            min_seconds=settings.min_seconds,
            cooldown_minutes=settings.cooldown_minutes,
            at_night=True,
        )

    return GuardThresholds(
        severity=settings.day_severity,
        min_seconds=settings.day_min_seconds,
        cooldown_minutes=settings.day_cooldown_minutes,
        at_night=False,
    )


class SecurityWatcher:
    """
    Решает, когда человек в кадре становится тревогой.

    Чистая логика без сети и без базы: на вход кадр и находки, на выход
    решение. Всё, что может сломаться, ломается здесь, и здесь же
    проверяется тестами.
    """

    def __init__(self, settings: GuardSettings):
        self.settings = settings
        self._states: dict[str, CameraGuardState] = {}

    def state(self, camera_id: str) -> CameraGuardState:
        return self._states.setdefault(camera_id, CameraGuardState())

    def observe(
        self,
        camera_id: str,
        persons: int,
        now: float,
        moment: datetime | None = None,
        guarded: bool = True,
        mode: str = "schedule",
    ) -> GuardDecision:
        """
        `now` — монотонные секунды (для длительностей), `moment` — реальное
        время (для охранного окна). Разные часы намеренно: монотонные не
        прыгают при переводе времени, а по ним считается выдержка.
        """
        state = self.state(camera_id)

        if persons > 0:
            state.persons = persons
            state.last_seen_at = now
            if state.first_seen_at is None:
                state.first_seen_at = now
        else:
            state.persons = 0
            # Сбрасываем накопленную выдержку только когда прошло время
            # «всё чисто»: иначе человек, на секунду скрывшийся за
            # столбом, начинал бы отсчёт заново и тревога не поднималась
            # бы никогда
            if state.last_seen_at is not None:
                quiet = now - state.last_seen_at
                if quiet >= self.settings.clear_minutes * 60:
                    state.first_seen_at = None
                    if state.alert_open:
                        state.alert_open = False
                        return GuardDecision(resolve_alert=True)

        limits = thresholds_for(self.settings, moment, mode)

        def quiet(seconds: float = 0.0) -> GuardDecision:
            return GuardDecision(
                persons=persons,
                seconds_present=seconds,
                severity=limits.severity,
                at_night=limits.at_night,
            )

        if not guarded or persons == 0:
            return quiet()

        # Дневную охрану можно отключить целиком: на проходном дворе с
        # постоянным движением она даёт только шум. Ночная при этом
        # продолжает работать
        if not limits.enabled:
            return quiet()

        # Именно `is None`, а не `or`: ноль в Python ложен, и запись
        # `state.first_seen_at or now` для момента 0.0 давала бы нулевую
        # выдержку — то есть тревога не поднималась бы никогда
        started = state.first_seen_at if state.first_seen_at is not None else now
        seconds = now - started
        if seconds < limits.min_seconds:
            return quiet(seconds)

        if state.alert_open:
            return quiet(seconds)

        if state.last_alert_at is not None:
            since = now - state.last_alert_at
            if since < limits.cooldown_minutes * 60:
                return quiet(seconds)

        state.alert_open = True
        state.last_alert_at = now
        return GuardDecision(
            raise_alert=True,
            persons=persons,
            seconds_present=seconds,
            severity=limits.severity,
            at_night=limits.at_night,
        )

    def count_in_zone(
        self,
        detections,
        polygon: list[tuple[float, float]] | None,
        width: int,
        height: int,
    ) -> int:
        """
        Сколько людей считать. Без периметра — все, с периметром — только
        те, кто стоит внутри.
        """
        people = [d for d in detections if d.class_name == "person"]
        if not polygon:
            return len(people)

        inside = 0
        for detection in people:
            point = foot_point(detection.bbox, width, height)
            if point is not None and point_in_polygon(point, polygon):
                inside += 1
        return inside


def alert_row(
    farm_id: str,
    camera_id: str,
    camera_name: str,
    decision: GuardDecision,
    snapshot_path: str | None = None,
) -> dict:
    """
    Строка тревоги.

    Уровень берётся из решения, а не задан жёстко: ночью «срочно», днём
    по умолчанию «внимание». Одинаковая срочность днём и ночью приучает
    не различать их, а значит — не читать ни те, ни другие.
    """
    when = "ночью" if decision.at_night else "днём"
    return {
        "farm_id": farm_id,
        "camera_id": camera_id,
        "kind": "intruder",
        "severity": decision.severity,
        "title": f"Посторонний на территории: {camera_name}",
        "snapshot_path": snapshot_path,
        "detail": {
            "persons": decision.persons,
            "seconds_present": round(decision.seconds_present, 1),
            "at_night": decision.at_night,
            "when": when,
        },
    }


def describe_window(settings: GuardSettings) -> str:
    """
    Для журнала при запуске: видно, что охрана настроена как задумано.

    Называем именно «строже», а не «работает»: охрана работает всегда, и
    строка «с 22:00 до 06:00» иначе читалась бы как «днём не смотрит».
    """
    start = settings.guard_from.strftime("%H:%M")
    end = settings.guard_to.strftime("%H:%M")

    if settings.day_severity == "off":
        day = "днём не тревожит"
    else:
        day = f"днём мягче ({settings.day_min_seconds:.0f} с)"

    if settings.guard_from == settings.guard_to:
        return "строгий режим круглосуточно"

    through_midnight = " (через полночь)" if settings.guard_from > settings.guard_to else ""
    return f"строже с {start} до {end}{through_midnight}, {day}"


__all__ = [
    "DAY_SEVERITIES",
    "GuardSettings",
    "GuardThresholds",
    "thresholds_for",
    "GuardDecision",
    "SecurityWatcher",
    "alert_row",
    "describe_window",
    "farm_now",
    "foot_point",
    "in_guard_window",
    "parse_time",
    "point_in_polygon",
]
