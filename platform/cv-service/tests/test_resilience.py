"""
Сценарии сбоев: проверяем, что система переживает то, что случится на ферме.
Каждый тест отвечает на вопрос «что будет, если...».
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.crops import CropCollector, insert_seen, match_known_animal
from cv_service.detector import Detection
from cv_service.headcount import HeadcountAggregator
from cv_service.main import process_camera
from cv_service.snapshot import encode_snapshot
from cv_service.zones import ZoneTracker, Zone, parse_zones


def _frame(w=640, h=480):
    rng = np.random.default_rng(seed=7)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def _mock_frame():
    f = MagicMock()
    f.shape = (480, 640, 3)
    f.__getitem__ = lambda _s, _k: MagicMock(copy=lambda: "cropped")
    return f


def _cap(frames):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, _mock_frame()) for _ in range(frames)] + [(False, None)]
    return cap


CAM = {"id": "cam-1", "name": "Загон", "source_uri": "test.mp4"}


class TestNetworkLoss:
    """Что будет, если пропадёт интернет."""

    @patch("cv_service.main.snapshots_enabled", return_value=True)
    @patch("cv_service.main.upload_snapshot", side_effect=Exception("нет сети"))
    @patch("cv_service.main.preview_enabled", return_value=False)
    @patch("cv_service.main.crops_enabled", return_value=False)
    @patch("cv_service.main.fetch_zones", side_effect=Exception("нет сети"))
    @patch("cv_service.main.send_heartbeat", side_effect=Exception("нет сети"))
    @patch("cv_service.main.insert_event", side_effect=Exception("нет сети"))
    @patch("cv_service.main.cv2.VideoCapture")
    def test_everything_fails_but_processing_continues(
        self, cap_cls, *_mocks
    ):
        """Всё, что ходит в сеть, падает — обработка видео обязана продолжаться."""
        cap_cls.return_value = _cap(5)
        detector = MagicMock()
        detector.detect_and_track.return_value = [
            Detection(1, "cow", 0.9, (10, 10, 200, 300))
        ]
        # Отсутствие исключения наружу — и есть проверка
        process_camera(MagicMock(), detector, "farm-1", CAM, frame_interval_s=0.0)

    @patch("cv_service.main.snapshots_enabled", return_value=False)
    @patch("cv_service.main.preview_enabled", return_value=False)
    @patch("cv_service.main.crops_enabled", return_value=True)
    @patch("cv_service.main.insert_seen")
    @patch("cv_service.main.fetch_zones", return_value=[])
    @patch("cv_service.main.send_heartbeat")
    @patch("cv_service.main.insert_event")
    @patch("cv_service.main.cv2.VideoCapture")
    def test_an_unknown_animal_is_not_recorded(
        self, cap_cls, _ev, _hb, _z, mock_seen, *_m
    ):
        """
        Незнакомое животное не попадает в базу вовсе.

        Раньше оно ложилось в очередь «ждут имени», которая не кончалась:
        каждый проход мимо камеры добавлял кадр, разбирать их было некому,
        и очередь превращалась в свалку.
        """
        cap_cls.return_value = _cap(3)
        detector = MagicMock()
        detector.detect_and_track.return_value = [
            Detection(1, "cow", 0.9, (10, 10, 200, 300))
        ]
        process_camera(MagicMock(), detector, "farm-1", CAM, frame_interval_s=0.0)
        mock_seen.assert_not_called()


class TestBadData:
    """Что будет, если придёт мусор."""

    def test_zones_survive_garbage_from_database(self):
        rows = [
            {"id": "z1", "polygon": None},
            {"id": "z2", "polygon": "не список"},
            {"id": "z3", "polygon": [[0, 0]]},
            {"id": "z4", "polygon": [["a", "b"], [1, 1], [2, 2]]},
            {"id": "z5", "polygon": [[0, 0], [1, 0], [1, 1]]},
        ]
        zones = parse_zones(rows)
        assert len(zones) == 1
        assert zones[0].id == "z5"

    def test_zone_tracker_survives_zero_sized_frame(self):
        """Битый кадр приходит с плохой сети — ронять обработку нельзя."""
        tracker = ZoneTracker(zones=[
            Zone("z1", "Кормушка", "feeder", ((0, 0), (1, 0), (1, 1)))
        ])
        started, finished = tracker.update(
            [Detection(1, "cow", 0.9, (0, 0, 10, 10))], 0, 0, now=0.0
        )
        assert started == [] and finished == []

    def test_match_survives_broken_response(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = MagicMock(data=[{}])
        assert match_known_animal(client, "farm-1", [0.1]) is None

    def test_snapshot_survives_one_pixel_frame(self):
        data = encode_snapshot(_frame(1, 1))
        assert data[:2] == b"\xff\xd8"


class TestOverload:
    """Что будет при большом стаде."""

    def test_hundred_animals_in_one_frame(self):
        collector = CropCollector()
        detections = [
            Detection(i, "cow", 0.9, (i * 5, 10, i * 5 + 100, 200))
            for i in range(100)
        ]
        collector.add(_frame(1920, 1080), detections, now=0.0)
        assert len(collector.flush()) <= 100

    def test_headcount_counts_distinct_not_observations(self):
        agg = HeadcountAggregator(interval_s=60)
        for moment in range(0, 60, 2):
            agg.add(
                [Detection(i, "cow", 0.9, (0, 0, 1, 1)) for i in range(50)],
                now=float(moment),
            )
        summary = agg.take()
        assert summary["unique_count"] == 50

    def test_many_zones_and_animals(self):
        zones = [
            Zone(f"z{i}", f"Зона {i}", "feeder",
                 ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
            for i in range(10)
        ]
        tracker = ZoneTracker(zones=zones)
        detections = [
            Detection(i, "cow", 0.9, (50, 50, 60, 60)) for i in range(50)
        ]
        started, _ = tracker.update(detections, 100, 100, now=0.0)
        # 50 животных в 10 зонах — 500 визитов
        assert len(started) == 500


class TestRestart:
    """Что будет при перезапуске сервиса."""

    def test_open_visits_are_written_before_shutdown(self):
        tracker = ZoneTracker(zones=[
            Zone("z1", "Кормушка", "feeder",
                 ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
        ])
        tracker.update([Detection(1, "cow", 0.9, (40, 40, 60, 60))], 100, 100, now=0.0)
        tracker.update([Detection(1, "cow", 0.9, (40, 40, 60, 60))], 100, 100, now=60.0)
        assert len(tracker.flush(now=60.0)) == 1

    def test_crops_are_written_before_shutdown(self):
        collector = CropCollector()
        collector.add(_frame(), [Detection(1, "cow", 0.9, (10, 10, 200, 300))], now=0.0)
        assert len(collector.flush()) == 1
