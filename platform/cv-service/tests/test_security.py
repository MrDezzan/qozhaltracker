"""
Тревога о постороннем.

Главная опасность модуля не в том, что он не сработает, а в том, что он
будет срабатывать зря. Система, которая будит хозяина каждую ночь на его
же стороже, через неделю перестаёт читаться — и оказывается бесполезной
ровно в ту ночь, ради которой её ставили.

Поэтому больше половины тестов здесь — про то, когда тревоги быть НЕ должно.
"""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from cv_service.security import (
    GuardSettings,
    thresholds_for,
    SecurityWatcher,
    alert_row,
    describe_window,
    farm_now,
    foot_point,
    in_guard_window,
    parse_time,
    point_in_polygon,
)


class FakeDetection:
    def __init__(self, class_name, bbox):
        self.class_name = class_name
        self.bbox = bbox


ALMATY = ZoneInfo("Asia/Almaty")


def farm_time(hour: int, minute: int = 0) -> datetime:
    """
    Момент по местному времени фермы, переведённый в UTC.

    Строим именно так, а не вычитанием пяти часов руками: смещение — дело
    базы часовых поясов, и считать его в уме означает однажды написать
    отрицательный час.
    """
    return datetime(2026, 8, 13, hour, minute, tzinfo=ALMATY).astimezone(timezone.utc)


def night(hour=2, minute=0) -> datetime:
    return farm_time(hour, minute)


def day(hour=13) -> datetime:
    return farm_time(hour)


class TestGuardWindow:
    """
    Окно через полночь — самая вероятная ошибка во всём модуле.

    Наивная проверка `start <= now <= end` для окна 22:00–06:00 даёт
    пустое множество: охрана молча не работает никогда, при этом всё
    выглядит настроенным.
    """

    def test_window_through_midnight_covers_the_night(self):
        assert in_guard_window(time(23, 30), time(22, 0), time(6, 0)) is True
        assert in_guard_window(time(2, 0), time(22, 0), time(6, 0)) is True
        assert in_guard_window(time(22, 0), time(22, 0), time(6, 0)) is True

    def test_window_through_midnight_excludes_the_day(self):
        assert in_guard_window(time(12, 0), time(22, 0), time(6, 0)) is False
        assert in_guard_window(time(6, 0), time(22, 0), time(6, 0)) is False
        assert in_guard_window(time(21, 59), time(22, 0), time(6, 0)) is False

    def test_an_ordinary_window_still_works(self):
        assert in_guard_window(time(12, 0), time(9, 0), time(18, 0)) is True
        assert in_guard_window(time(2, 0), time(9, 0), time(18, 0)) is False

    def test_equal_bounds_mean_round_the_clock(self):
        assert in_guard_window(time(3, 0), time(0, 0), time(0, 0)) is True
        assert in_guard_window(time(15, 0), time(0, 0), time(0, 0)) is True


class TestFarmTime:
    def test_night_is_local_not_server_time(self):
        """
        Сервер может стоять где угодно, а «ночь» — понятие местное.
        21:00 UTC в Алматы это уже два часа ночи.
        """
        local = farm_now("Asia/Almaty", datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc))
        assert local.hour == 2

    def test_an_unknown_timezone_does_not_break_the_guard(self):
        local = farm_now("Марс/Олимп", datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc))
        assert local.hour == 21


class TestParseTime:
    def test_reads_what_the_database_sends(self):
        assert parse_time("22:00:00", time(0, 0)) == time(22, 0)
        assert parse_time("06:30", time(0, 0)) == time(6, 30)

    def test_nonsense_falls_back_instead_of_crashing(self):
        assert parse_time("ночью", time(22, 0)) == time(22, 0)
        assert parse_time("", time(22, 0)) == time(22, 0)
        assert parse_time(None, time(22, 0)) == time(22, 0)
        assert parse_time("99:00", time(22, 0)) == time(22, 0)


class TestRaisingAnAlert:
    def test_a_person_at_night_raises_one(self):
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=6.0, moment=night())

        assert decision.raise_alert is True
        assert decision.persons == 1

    def test_a_brief_flicker_does_not(self):
        """
        Одиночная осечка модели живёт один кадр, человек — секунды.
        Без выдержки тревоги сыпались бы на теней и дождь.
        """
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=2.0, moment=night())

        assert decision.raise_alert is False

    def test_daytime_raises_too_but_later_and_quieter(self):
        """
        Охрана работает круглосуточно: воруют и среди бела дня. Но днём
        по ферме ходят свои, поэтому ждём дольше и сообщаем мягче.
        """
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=day())

        # Ночью этого хватило бы, днём — нет
        early = watcher.observe("cam-1", persons=1, now=6.0, moment=day())
        assert early.raise_alert is False

        late = watcher.observe("cam-1", persons=1, now=35.0, moment=day())
        assert late.raise_alert is True
        assert late.severity == "warning"
        assert late.at_night is False

    def test_night_alerts_are_urgent(self):
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=6.0, moment=night())

        assert decision.severity == "danger"
        assert decision.at_night is True

    def test_the_day_can_be_silenced_without_losing_the_night(self):
        """
        На проходном дворе с постоянным движением дневная охрана даёт
        только шум. Выключать её целиком вместе с ночной — потерять всё.
        """
        settings = GuardSettings(day_severity="off")
        watcher = SecurityWatcher(settings)

        watcher.observe("cam-1", persons=1, now=0.0, moment=day())
        assert (
            watcher.observe("cam-1", persons=1, now=120.0, moment=day()).raise_alert
            is False
        )

        watcher.observe("cam-2", persons=1, now=0.0, moment=night())
        assert (
            watcher.observe("cam-2", persons=1, now=10.0, moment=night()).raise_alert
            is True
        )

    def test_a_camera_where_people_never_belong_is_strict_by_day(self):
        """Склад, дальний загон, топливная ёмкость."""
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=day(), mode="always")
        decision = watcher.observe(
            "cam-1", persons=1, now=6.0, moment=day(), mode="always"
        )

        assert decision.raise_alert is True
        assert decision.severity == "danger"

    def test_a_camera_with_guarding_off_never_raises(self):
        """У кормового стола охрана не нужна: там утренняя раздача."""
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=night(), guarded=False)
        decision = watcher.observe(
            "cam-1", persons=1, now=60.0, moment=night(), guarded=False
        )

        assert decision.raise_alert is False

    def test_only_one_alert_while_the_person_stays(self):
        """
        Иначе за ночь набежали бы тысячи одинаковых записей, и утром
        хозяин увидел бы не тревогу, а мусор.
        """
        watcher = SecurityWatcher(GuardSettings())
        watcher.observe("cam-1", persons=1, now=0.0, moment=night())

        first = watcher.observe("cam-1", persons=1, now=6.0, moment=night())
        second = watcher.observe("cam-1", persons=1, now=7.0, moment=night())
        third = watcher.observe("cam-1", persons=1, now=120.0, moment=night())

        assert [first.raise_alert, second.raise_alert, third.raise_alert] == [
            True,
            False,
            False,
        ]

    def test_cameras_are_counted_separately(self):
        watcher = SecurityWatcher(GuardSettings())

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        watcher.observe("cam-2", persons=1, now=0.0, moment=night())

        assert watcher.observe("cam-1", persons=1, now=6.0, moment=night()).raise_alert
        assert watcher.observe("cam-2", persons=1, now=6.0, moment=night()).raise_alert


class TestClearingAndCooldown:
    def test_the_alert_closes_when_everyone_leaves(self):
        settings = GuardSettings(clear_minutes=1.0)
        watcher = SecurityWatcher(settings)

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        watcher.observe("cam-1", persons=1, now=6.0, moment=night())

        decision = watcher.observe("cam-1", persons=0, now=70.0, moment=night())
        assert decision.resolve_alert is True

    def test_a_moment_out_of_sight_does_not_reset_the_wait(self):
        """
        Человек на секунду зашёл за столб. Если сбрасывать отсчёт на
        каждом пропавшем кадре, выдержка не наберётся никогда и тревога
        не поднимется вовсе.
        """
        settings = GuardSettings(min_seconds=5.0, clear_minutes=10.0)
        watcher = SecurityWatcher(settings)

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        watcher.observe("cam-1", persons=0, now=2.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=6.0, moment=night())

        assert decision.raise_alert is True

    def test_a_second_alert_waits_out_the_cooldown(self):
        settings = GuardSettings(clear_minutes=0.5, cooldown_minutes=15.0)
        watcher = SecurityWatcher(settings)

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        watcher.observe("cam-1", persons=1, now=6.0, moment=night())
        watcher.observe("cam-1", persons=0, now=40.0, moment=night())

        watcher.observe("cam-1", persons=1, now=100.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=110.0, moment=night())
        assert decision.raise_alert is False

    def test_after_the_cooldown_a_new_alert_is_allowed(self):
        settings = GuardSettings(clear_minutes=0.5, cooldown_minutes=1.0)
        watcher = SecurityWatcher(settings)

        watcher.observe("cam-1", persons=1, now=0.0, moment=night())
        watcher.observe("cam-1", persons=1, now=6.0, moment=night())
        watcher.observe("cam-1", persons=0, now=40.0, moment=night())

        watcher.observe("cam-1", persons=1, now=100.0, moment=night())
        decision = watcher.observe("cam-1", persons=1, now=110.0, moment=night())
        assert decision.raise_alert is True


class TestPerimeter:
    SQUARE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]

    def test_counts_everyone_without_a_perimeter(self):
        watcher = SecurityWatcher(GuardSettings())
        people = [
            FakeDetection("person", (10, 10, 20, 20)),
            FakeDetection("person", (900, 900, 950, 950)),
        ]
        assert watcher.count_in_zone(people, None, 1000, 1000) == 2

    def test_counts_only_those_inside_the_perimeter(self):
        """Без этого тревога сработает на дорогу за забором."""
        watcher = SecurityWatcher(GuardSettings())
        people = [
            FakeDetection("person", (450, 400, 550, 500)),   # ноги в центре
            FakeDetection("person", (10, 10, 60, 60)),       # угол, снаружи
        ]
        assert watcher.count_in_zone(people, self.SQUARE, 1000, 1000) == 1

    def test_animals_are_not_people(self):
        """
        Разделение классов должно доходить и сюда: корова в периметре
        ночью — это норма, а не посторонний.
        """
        watcher = SecurityWatcher(GuardSettings())
        mixed = [
            FakeDetection("cow", (450, 400, 550, 500)),
            FakeDetection("person", (450, 400, 550, 500)),
        ]
        assert watcher.count_in_zone(mixed, self.SQUARE, 1000, 1000) == 1


class TestGeometry:
    def test_foot_point_uses_the_bottom_not_the_centre(self):
        """
        Человек стоит на земле: попадание в зону определяется тем, где он
        стоит, а не где у него голова.
        """
        assert foot_point((100, 0, 300, 400), 1000, 800) == (0.2, 0.5)

    def test_an_empty_frame_gives_nothing(self):
        assert foot_point((0, 0, 10, 10), 0, 0) is None

    def test_point_in_polygon(self):
        square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert point_in_polygon((0.5, 0.5), square) is True
        assert point_in_polygon((1.5, 0.5), square) is False

    def test_a_degenerate_polygon_contains_nothing(self):
        assert point_in_polygon((0.5, 0.5), [(0.0, 0.0), (1.0, 1.0)]) is False


class TestAlertRow:
    def test_carries_what_is_needed_to_act(self):
        watcher = SecurityWatcher(GuardSettings())
        watcher.observe("cam-1", persons=2, now=0.0, moment=night())
        decision = watcher.observe("cam-1", persons=2, now=8.0, moment=night())

        row = alert_row("farm-1", "cam-1", "Въезд", decision, "farm-1/intruder.jpg")

        assert row["kind"] == "intruder"
        assert row["severity"] == "danger"
        assert row["camera_id"] == "cam-1"
        assert "Въезд" in row["title"]
        assert row["detail"]["persons"] == 2
        assert row["detail"]["seconds_present"] == 8.0
        assert row["snapshot_path"] == "farm-1/intruder.jpg"


class TestSettingsFromDatabase:
    def test_reads_a_row(self):
        settings = GuardSettings.from_row(
            {
                "guard_from": "23:00:00",
                "guard_to": "05:00:00",
                "intruder_min_seconds": 10,
                "intruder_cooldown_minutes": 30,
                "intruder_clear_minutes": 5,
            },
            timezone_name="Asia/Almaty",
        )

        assert settings.guard_from == time(23, 0)
        assert settings.min_seconds == 10.0
        assert settings.cooldown_minutes == 30.0

    def test_a_farm_without_settings_gets_the_defaults(self):
        settings = GuardSettings.from_row(None)
        assert settings.guard_from == time(22, 0)
        assert settings.guard_to == time(6, 0)


class TestDescribeWindow:
    def test_says_when_the_window_crosses_midnight(self):
        # В журнале при запуске должно быть видно, что настроено именно то,
        # что задумано — иначе неверное окно обнаружится через месяц
        assert "через полночь" in describe_window(GuardSettings())

    def test_says_when_the_strict_mode_is_round_the_clock(self):
        settings = GuardSettings(guard_from=time(0, 0), guard_to=time(0, 0))
        assert describe_window(settings) == "строгий режим круглосуточно"

    def test_never_reads_as_if_the_guard_slept_by_day(self):
        """
        Строка «с 09:00 до 18:00» читалась бы как «в остальное время не
        смотрит». Охрана работает всегда, и в журнале это должно быть видно.
        """
        settings = GuardSettings(guard_from=time(9, 0), guard_to=time(18, 0))
        line = describe_window(settings)

        assert "строже" in line
        assert "днём мягче" in line

    def test_says_when_the_day_is_silenced(self):
        settings = GuardSettings(day_severity="off")
        assert "днём не тревожит" in describe_window(settings)


class TestThresholds:
    """
    Строгость по времени суток. Вынесена отдельной функцией, потому что
    именно здесь решается главный вопрос модуля: работать всегда, но не
    одинаково громко.
    """

    def test_night_is_strict(self):
        limits = thresholds_for(GuardSettings(), night())
        assert limits.severity == "danger"
        assert limits.min_seconds == 5.0
        assert limits.at_night is True

    def test_day_is_softer_but_still_on(self):
        limits = thresholds_for(GuardSettings(), day())
        assert limits.enabled is True
        assert limits.severity == "warning"
        assert limits.min_seconds == 30.0
        assert limits.cooldown_minutes == 60.0

    def test_always_mode_ignores_the_clock(self):
        limits = thresholds_for(GuardSettings(), day(), mode="always")
        assert limits.severity == "danger"
        assert limits.min_seconds == 5.0
        # Время всё равно помним: в тревоге пишем, днём это было или ночью
        assert limits.at_night is False

    def test_silenced_day_reports_itself_as_off(self):
        limits = thresholds_for(GuardSettings(day_severity="off"), day())
        assert limits.enabled is False

    def test_silenced_day_does_not_silence_the_night(self):
        limits = thresholds_for(GuardSettings(day_severity="off"), night())
        assert limits.enabled is True
        assert limits.severity == "danger"

    def test_nonsense_severity_from_the_database_falls_back(self):
        settings = GuardSettings.from_row({"guard_day_severity": "очень срочно"})
        assert settings.day_severity == "warning"
