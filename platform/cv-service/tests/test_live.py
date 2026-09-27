import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np

from cv_service.live import (
    Heartbeat,
    LiveWindow,
    ZoneCache,
    live_interval_s,
    parse_until,
)
from cv_service.stream import (
    FrameBuffer,
    start_stream_server,
    stream_enabled,
    stream_fps,
    stream_port,
)


def _client(rows):
    client = MagicMock()
    chain = client.table.return_value.select.return_value.eq.return_value
    chain.execute.return_value = MagicMock(data=rows)
    return client


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class TestParseUntil:
    def test_reads_the_moment_from_the_database(self):
        assert parse_until("2026-08-11T10:00:00+00:00") == datetime(
            2026, 8, 11, 10, tzinfo=timezone.utc
        )

    def test_handles_the_z_suffix(self):
        assert parse_until("2026-08-11T10:00:00Z") is not None

    def test_time_without_a_zone_is_treated_as_utc(self):
        """База отдаёт UTC; наивное время без пояса нельзя считать местным."""
        assert parse_until("2026-08-11T10:00:00").tzinfo == timezone.utc

    def test_empty_and_broken_values_are_not_a_live_request(self):
        assert parse_until(None) is None
        assert parse_until("") is None
        assert parse_until("скоро") is None


class TestLiveWindow:
    """
    Опрос базы живёт в собственном потоке, а is_live только читает память.

    Это не украшение: пока запрос шёл прямо из цикла захвата, один зависший
    вызов останавливал обработку видео целиком — вместе с тем самым живым
    просмотром, ради которого всё и затевалось.
    """

    def test_a_fresh_request_turns_the_camera_live(self):
        window = LiveWindow(_client([{"id": "cam-1", "live_until": _iso(30)}]), "farm-1")
        window.check_available()
        assert window.is_live("cam-1") is True

    def test_an_expired_request_does_not(self):
        """Хозяин закрыл вкладку — камера сама возвращается в обычный режим."""
        window = LiveWindow(_client([{"id": "cam-1", "live_until": _iso(-30)}]), "farm-1")
        window.check_available()
        assert window.is_live("cam-1") is False

    def test_other_cameras_stay_normal(self):
        window = LiveWindow(_client([{"id": "cam-1", "live_until": _iso(30)}]), "farm-1")
        window.check_available()
        assert window.is_live("cam-2") is False

    def test_is_live_never_touches_the_network(self):
        """
        Главное свойство: вызов из цикла захвата не должен ждать сеть.
        Клиент, который взрывается при обращении, это и проверяет.
        """
        exploding = MagicMock()
        exploding.table.side_effect = AssertionError("сетевой вызов в цикле захвата")
        window = LiveWindow(exploding, "farm-1")

        assert window.is_live("cam-1") is False

    def test_one_query_serves_every_camera(self):
        """
        На тридцати камерах опрос по камере означал бы тридцать запросов
        каждые три секунды. Спрашиваем один раз про всю ферму.
        """
        client = _client([{"id": "cam-1", "live_until": _iso(30)}])
        window = LiveWindow(client, "farm-1")
        window.check_available()

        for camera in ("cam-1", "cam-2", "cam-3"):
            window.is_live(camera)

        assert client.table.call_count == 1

    def test_the_polling_thread_keeps_the_answer_fresh(self):
        client = _client([{"id": "cam-1", "live_until": _iso(30)}])
        window = LiveWindow(client, "farm-1", poll_interval_s=0.05)
        window.start()
        try:
            _wait_until(lambda: window.is_live("cam-1"))
            _wait_until(lambda: client.table.call_count >= 2)
        finally:
            window.stop()

    def test_a_database_outage_keeps_the_camera_working(self):
        """Недоступность базы не должна ронять обработку видео."""
        client = MagicMock()
        client.table.side_effect = Exception("нет сети")
        window = LiveWindow(client, "farm-1")
        assert "недоступен" in window.check_available()
        assert window.is_live("cam-1") is False

    def test_a_broken_moment_is_ignored(self):
        window = LiveWindow(_client([{"id": "cam-1", "live_until": "потом"}]), "farm-1")
        window.check_available()
        assert window.is_live("cam-1") is False


def test_live_interval_is_about_a_second_by_default():
    with patch.dict("os.environ", {}, clear=True):
        assert 0.2 <= live_interval_s() <= 2.0


def test_live_interval_rejects_garbage_and_zero():
    with patch.dict("os.environ", {"LIVE_SNAPSHOT_INTERVAL_S": "часто"}, clear=True):
        assert live_interval_s() > 0
    with patch.dict("os.environ", {"LIVE_SNAPSHOT_INTERVAL_S": "0"}, clear=True):
        assert live_interval_s() > 0


class TestFrameBuffer:
    def _frame(self):
        rng = np.random.default_rng(seed=5)
        return rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)

    def test_keeps_the_latest_frame_per_camera(self):
        buffer = FrameBuffer()
        buffer.put("cam-1", self._frame())
        assert buffer.get("cam-1")[:2] == b"\xff\xd8"

    def test_an_unknown_camera_has_nothing(self):
        assert FrameBuffer().get("cam-9") is None

    def test_only_one_frame_is_held(self):
        """
        Зритель должен видеть настоящее, а не догонять очередь: медленный
        канал приводит к пропуску кадров, а не к отставанию на минуту.
        """
        buffer = FrameBuffer()
        buffer.put("cam-1", self._frame())
        first = buffer.get("cam-1")
        buffer.put("cam-1", self._frame() // 2)
        assert buffer.get("cam-1") != first

    def test_lists_the_cameras_it_has_seen(self):
        buffer = FrameBuffer()
        buffer.put("cam-1", self._frame())
        buffer.put("cam-2", self._frame())
        assert set(buffer.cameras()) == {"cam-1", "cam-2"}


class TestStreamServer:
    def test_off_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert stream_enabled() is False
            assert start_stream_server(FrameBuffer()) is None

    def test_refuses_to_start_without_a_password(self):
        """Иначе камеры увидит любой, кто попал в сеть фермы."""
        with patch.dict("os.environ", {"STREAM_ENABLED": "1"}, clear=True):
            assert start_stream_server(FrameBuffer()) is None

    def test_port_and_rate_fall_back_to_defaults(self):
        with patch.dict("os.environ", {"STREAM_PORT": "порт", "STREAM_FPS": "-1"}, clear=True):
            assert stream_port() > 0
            assert stream_fps() > 0


class TestAvailabilityCheck:
    """
    Проверка при запуске. Без неё «работает ли живой просмотр» приходилось
    выяснять по возрасту кадра в браузере — и путать со старым кодом.
    """

    def test_says_ready_when_the_database_answers(self):
        window = LiveWindow(_client([]), "farm-1")
        assert window.check_available() == "готов"

    def test_names_the_reason_when_it_cannot(self):
        client = MagicMock()
        client.table.side_effect = Exception("column live_until does not exist")
        assert "недоступен" in LiveWindow(client, "farm-1").check_available()
        assert "live_until" in LiveWindow(client, "farm-1").check_available()


def test_refresh_reads_every_camera_of_the_farm():
    """
    Отсев пустых отметок делаем у себя, а не отрицающим фильтром в базе:
    камер единицы, а тихая осечка фильтра стоила бы неработающего просмотра.
    """
    client = _client(
        [
            {"id": "cam-1", "live_until": _iso(30)},
            {"id": "cam-2", "live_until": None},
        ]
    )
    window = LiveWindow(client, "farm-1")
    window.check_available()

    assert window.is_live("cam-1") is True
    assert window.is_live("cam-2") is False


class TestHeartbeat:
    def test_beats_in_its_own_thread(self):
        beats = []
        heart = Heartbeat(lambda: beats.append(1), interval_s=0.05)
        heart.start()
        try:
            _wait_until(lambda: len(beats) >= 2)
        finally:
            heart.stop()

    def test_a_failed_beat_does_not_kill_the_thread(self):
        """Обрыв связи не должен оставлять ферму без отметок навсегда."""
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("нет сети")

        heart = Heartbeat(flaky, interval_s=0.05)
        heart.start()
        try:
            _wait_until(lambda: len(calls) >= 3)
            assert heart.is_alive()
        finally:
            heart.stop()


class TestZoneCache:
    def test_first_read_happens_before_the_thread_starts(self):
        """Зоны должны быть сразу, а не через минуту после запуска."""
        cache = ZoneCache(lambda: [{"id": "z1"}], interval_s=10)
        assert cache.prime() == [{"id": "z1"}]

    def test_a_broken_read_does_not_stop_the_camera(self):
        def boom():
            raise RuntimeError("нет сети")

        assert ZoneCache(boom, interval_s=10).prime() == []

    def test_reports_a_change_only_once(self):
        cache = ZoneCache(lambda: [{"id": "z1"}], interval_s=10)
        cache.prime()

        version, rows = cache.take_if_changed(0)
        assert rows == [{"id": "z1"}]
        assert cache.take_if_changed(version) is None

    def test_a_new_read_is_reported_again(self):
        cache = ZoneCache(lambda: [{"id": "z1"}], interval_s=10)
        cache.prime()
        version, _ = cache.take_if_changed(0)

        cache.prime()
        assert cache.take_if_changed(version) is not None


def _wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("условие не выполнилось за отведённое время")
