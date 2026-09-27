"""
Публикация видео на сервер ретрансляции.

Проверяем логику приведения запущенного к желаемому: ни камеры, ни сети,
ни настоящего ffmpeg. Всё, что может сломаться в этом модуле, ломается
именно здесь — в решении «запускать, останавливать или перезапускать».
"""

import time
from unittest.mock import Mock

import pytest

from cv_service.remote import (
    RESTART_DELAY_S,
    Publication,
    RemotePublisher,
    build_publish_command,
    relay_enabled,
    relay_url,
)

CAMERAS = [
    {"id": "cam-1", "name": "Загон 1", "source_uri": "rtsp://cam1/sub"},
    {"id": "cam-2", "name": "Загон 2", "source_uri": "rtsp://cam2/sub"},
]


class FakeProcess:
    """Процесс, которым можно управлять из теста."""

    def __init__(self):
        self.alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated = True
        self.alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self.alive = False


def make_publisher(monkeypatch, spawned=None):
    monkeypatch.setenv("RELAY_URL", "https://relay.example/")
    spawned = spawned if spawned is not None else []

    def spawn(source, target):
        process = FakeProcess()
        spawned.append({"source": source, "target": target, "process": process})
        return process

    return RemotePublisher(Mock(), "farm-1", CAMERAS, spawn=spawn), spawned


class TestCommand:
    def test_does_not_re_encode(self):
        """
        Главное свойство модуля. Камера уже отдаёт H.264; перекодирование
        съело бы ядро на камеру и ухудшило картинку ради ничего.
        """
        command = build_publish_command("rtsp://cam/sub", "https://relay/x/whip")
        assert "-c" in command
        assert command[command.index("-c") + 1] == "copy"

    def test_drops_audio(self):
        """Звук занимает канал, а запись разговоров работников — отдельный
        юридический разговор, в который мы не идём."""
        assert "-an" in build_publish_command("rtsp://cam", "https://relay/x")

    def test_uses_tcp_for_rtsp(self):
        command = build_publish_command("rtsp://cam", "https://relay/x")
        assert command[command.index("-rtsp_transport") + 1] == "tcp"

    def test_source_and_target_land_in_the_right_places(self):
        command = build_publish_command("rtsp://cam/sub", "https://relay/abc/whip")
        assert command[command.index("-i") + 1] == "rtsp://cam/sub"
        assert command[-1] == "https://relay/abc/whip"


class TestRelayUrl:
    def test_disabled_when_unset(self, monkeypatch):
        monkeypatch.delenv("RELAY_URL", raising=False)
        assert relay_enabled() is False

    def test_trailing_slash_is_dropped(self, monkeypatch):
        """Иначе адрес публикации собирался бы с двойным слэшем."""
        monkeypatch.setenv("RELAY_URL", "https://relay.example/")
        assert relay_url() == "https://relay.example"


class TestReconcile:
    def test_starts_a_publication_when_someone_watches(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc123"})

        assert len(spawned) == 1
        assert spawned[0]["source"] == "rtsp://cam1/sub"
        assert spawned[0]["target"] == "https://relay.example/abc123/whip"

    def test_nothing_runs_when_nobody_watches(self, monkeypatch):
        """
        Без этого тридцать камер отдавали бы поток круглосуточно ради
        картинки, на которую никто не глядит, — и съели бы канал фермы.
        """
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({})
        assert spawned == []

    def test_stops_when_the_viewer_leaves(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc123"})
        publisher.reconcile({})

        assert spawned[0]["process"].terminated is True
        assert publisher._active == {}

    def test_does_not_restart_what_already_runs(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc123"})
        publisher.reconcile({"cam-1": "abc123"})
        publisher.reconcile({"cam-1": "abc123"})

        assert len(spawned) == 1

    def test_restarts_when_the_session_changes(self, monkeypatch):
        """
        Открыли просмотр заново — путь стал другим, и старая публикация
        теперь льёт в никуда. Это надо заметить, иначе зритель смотрит
        в пустой поток и уверен, что система сломалась.
        """
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "старый"})
        publisher.reconcile({"cam-1": "новый"})

        assert spawned[0]["process"].terminated is True
        assert len(spawned) == 2
        assert spawned[1]["target"].endswith("/новый/whip")

    def test_switches_cameras(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "p1"})
        publisher.reconcile({"cam-2": "p2"})

        assert spawned[0]["process"].terminated is True
        assert spawned[1]["source"] == "rtsp://cam2/sub"

    def test_unknown_camera_is_ignored(self, monkeypatch):
        """Сессия на камеру, которой у этого устройства нет, — не повод падать."""
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-чужая": "p1"})
        assert spawned == []


class TestRestartAfterFailure:
    def test_a_dead_publication_is_noticed(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc"})
        spawned[0]["process"].alive = False

        publisher.reconcile({"cam-1": "abc"})
        assert publisher._active == {}

    def test_restart_waits_instead_of_hammering(self, monkeypatch):
        """
        Сорванный канал без паузы означал бы запуск ffmpeg по нескольку
        раз в секунду — и загруженный процессор вместо видео.
        """
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc"})
        spawned[0]["process"].alive = False

        publisher.reconcile({"cam-1": "abc"})   # заметил падение
        publisher.reconcile({"cam-1": "abc"})   # слишком рано
        assert len(spawned) == 1

    def test_restart_happens_after_the_pause(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc"})
        spawned[0]["process"].alive = False
        publisher.reconcile({"cam-1": "abc"})

        publisher._failed_at["cam-1"] = time.monotonic() - RESTART_DELAY_S - 1
        publisher.reconcile({"cam-1": "abc"})
        assert len(spawned) == 2

    def test_a_failing_spawn_does_not_kill_the_thread(self, monkeypatch):
        monkeypatch.setenv("RELAY_URL", "https://relay.example")

        def boom(source, target):
            raise OSError("ffmpeg не найден")

        publisher = RemotePublisher(Mock(), "farm-1", CAMERAS, spawn=boom)
        publisher.reconcile({"cam-1": "abc"})   # не должно бросить наружу
        assert publisher._active == {}


class TestStop:
    def test_stopping_the_service_stops_the_publications(self, monkeypatch):
        publisher, spawned = make_publisher(monkeypatch)
        publisher.reconcile({"cam-1": "abc"})
        publisher.stop()

        assert spawned[0]["process"].terminated is True
        assert publisher._active == {}


class TestPublication:
    def test_kills_what_refuses_to_stop(self):
        """Зависший ffmpeg держит соединение с камерой — оставлять нельзя."""
        process = FakeProcess()

        def stubborn(timeout=None):
            raise RuntimeError("не отвечает")

        process.wait = stubborn
        publication = Publication("cam-1", "abc", process)
        publication.stop()

        assert process.killed is True

    def test_stopping_an_already_dead_process_is_fine(self):
        process = FakeProcess()
        process.alive = False
        Publication("cam-1", "abc", process).stop()
        assert process.terminated is False


class TestFetchSessions:
    def test_reads_camera_and_path(self, monkeypatch):
        monkeypatch.setenv("RELAY_URL", "https://relay.example")
        client = Mock()
        chain = client.table.return_value.select.return_value.eq.return_value
        chain.execute.return_value = Mock(
            data=[{"camera_id": "cam-1", "path": "abc"}]
        )

        publisher = RemotePublisher(client, "farm-1", CAMERAS)
        assert publisher._fetch_sessions() == {"cam-1": "abc"}

    def test_rows_without_a_path_are_skipped(self, monkeypatch):
        monkeypatch.setenv("RELAY_URL", "https://relay.example")
        client = Mock()
        chain = client.table.return_value.select.return_value.eq.return_value
        chain.execute.return_value = Mock(
            data=[{"camera_id": "cam-1", "path": None}]
        )

        publisher = RemotePublisher(client, "farm-1", CAMERAS)
        assert publisher._fetch_sessions() == {}


class TestThreadItself:
    """
    Класс наследует threading.Thread, и это уже подвело один раз.

    Методы `_target` и `_stop` перекрыли внутренние поля Thread: под первым
    именем Thread держит функцию потока, второе вызывает сам при завершении.
    Публикация падала с «'NoneType' object is not callable», а учёт живых
    потоков ломался молча. Тесты на reconcile этого не видели — они не
    запускали поток.
    """

    def test_the_thread_actually_starts_and_stops(self, monkeypatch):
        publisher, _ = make_publisher(monkeypatch)
        publisher._fetch_sessions = lambda: {}

        publisher.start()
        try:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and not publisher.is_alive():
                time.sleep(0.01)
            assert publisher.is_alive()
        finally:
            publisher.stop()

        publisher.join(2.0)
        assert not publisher.is_alive()

    def test_thread_internals_are_not_shadowed(self, monkeypatch):
        publisher, _ = make_publisher(monkeypatch)
        # У живого Thread это поле — функция потока (у нас None), а не метод
        assert not callable(getattr(publisher, "_target", None))


class TestCheckAvailable:
    def test_says_when_it_is_off(self, monkeypatch):
        monkeypatch.delenv("RELAY_URL", raising=False)
        publisher = RemotePublisher(Mock(), "farm-1", CAMERAS)
        assert "выключена" in publisher.check_available()

    def test_says_when_ffmpeg_is_missing(self, monkeypatch):
        monkeypatch.setenv("RELAY_URL", "https://relay.example")
        monkeypatch.setattr("cv_service.remote.ffmpeg_path", lambda: None)
        publisher = RemotePublisher(Mock(), "farm-1", CAMERAS)
        assert "ffmpeg" in publisher.check_available()
