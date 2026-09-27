"""
Поток по локальной сети и автоматическая прописка его адреса.

Живое видео у нас однажды не заработало не из-за кода, а из-за пропущенного
ручного шага: адрес потока надо было собрать и вставить в админку. Эти
тесты закрывают именно ту дыру — устройство должно справляться само.
"""

import os
from unittest.mock import Mock

import pytest

from cv_service.stream import (
    DEFAULT_FPS,
    lan_ip,
    local_stream_url,
    stream_fps,
    stream_host,
    stream_port,
)
from cv_service.supabase_client import register_camera_stream


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "STREAM_ENABLED",
        "STREAM_TOKEN",
        "STREAM_PORT",
        "STREAM_FPS",
        "STREAM_HOST",
    ):
        monkeypatch.delenv(name, raising=False)


class TestFps:
    def test_thirty_by_default(self):
        """
        Пятнадцать читались как видеонаблюдение, тридцать — как жизнь.
        Разницу видно сразу, и она была главной жалобой.
        """
        assert DEFAULT_FPS == 30.0
        assert stream_fps() == 30.0

    def test_can_be_lowered_for_a_weak_machine(self, monkeypatch):
        monkeypatch.setenv("STREAM_FPS", "10")
        assert stream_fps() == 10.0

    def test_nonsense_falls_back_instead_of_crashing(self, monkeypatch):
        monkeypatch.setenv("STREAM_FPS", "быстро")
        assert stream_fps() == DEFAULT_FPS

    def test_zero_would_stop_the_stream_so_it_is_ignored(self, monkeypatch):
        monkeypatch.setenv("STREAM_FPS", "0")
        assert stream_fps() == DEFAULT_FPS


class TestHost:
    def test_env_overrides_detection(self, monkeypatch):
        """
        На ферме с несколькими сетями автоматика выбирает не тот интерфейс,
        и починить это надо настройкой, а не правкой кода.
        """
        monkeypatch.setenv("STREAM_HOST", "10.0.0.5")
        assert stream_host() == "10.0.0.5"

    def test_detected_address_looks_like_an_address(self):
        found = lan_ip()
        if found is None:
            pytest.skip("сеть недоступна")
        assert found.count(".") == 3

    def test_falls_back_to_localhost(self, monkeypatch):
        """
        Без сети адрес всё равно нужен: на одной машине с дашбордом
        поток прекрасно ходит через 127.0.0.1.
        """
        monkeypatch.setattr("cv_service.stream.lan_ip", lambda: None)
        assert stream_host() == "127.0.0.1"


class TestLocalStreamUrl:
    def test_built_from_host_port_and_token(self, monkeypatch):
        monkeypatch.setenv("STREAM_ENABLED", "1")
        monkeypatch.setenv("STREAM_TOKEN", "секрет")
        monkeypatch.setenv("STREAM_HOST", "192.168.1.50")
        monkeypatch.setenv("STREAM_PORT", "9000")

        assert (
            local_stream_url("cam-1")
            == "http://192.168.1.50:9000/stream/cam-1?token=секрет"
        )

    def test_nothing_when_the_stream_is_off(self, monkeypatch):
        monkeypatch.setenv("STREAM_TOKEN", "секрет")
        assert local_stream_url("cam-1") is None

    def test_nothing_without_a_password(self, monkeypatch):
        """
        Адрес без пароля прописывать нельзя: он открыл бы камеры любому,
        кто попал в сеть фермы.
        """
        monkeypatch.setenv("STREAM_ENABLED", "1")
        assert local_stream_url("cam-1") is None

    def test_default_port_when_not_set(self, monkeypatch):
        monkeypatch.setenv("STREAM_ENABLED", "1")
        monkeypatch.setenv("STREAM_TOKEN", "t")
        monkeypatch.setenv("STREAM_HOST", "host")
        assert f":{stream_port()}/" in local_stream_url("cam-1")


class TestRegisterCameraStream:
    def test_calls_the_function_with_both_arguments(self):
        client = Mock()
        assert register_camera_stream(client, "cam-1", "http://x/stream") is True

        client.rpc.assert_called_once_with(
            "register_camera_stream",
            {"target_camera_id": "cam-1", "new_url": "http://x/stream"},
        )

    def test_a_failure_does_not_stop_the_service(self):
        """
        Не прописанный адрес — это живой просмотр кадрами вместо видео.
        Неприятно, но ронять из-за этого обработку видео куда хуже.
        """
        client = Mock()
        client.rpc.side_effect = RuntimeError("нет сети")

        assert register_camera_stream(client, "cam-1", "http://x/stream") is False
