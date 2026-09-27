from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.detector import (
    DEFAULT_TRACKED_CLASS_NAMES,
    Detection,
    Detector,
    get_tracked_class_names,
)


def _fake_results():
    fake_boxes = MagicMock()
    fake_boxes.xyxy.tolist.return_value = [[10.0, 20.0, 110.0, 220.0]]
    fake_boxes.id.tolist.return_value = [5.0]
    fake_boxes.cls.tolist.return_value = [0.0]
    fake_boxes.conf.tolist.return_value = [0.87]
    fake_result = MagicMock()
    fake_result.boxes = fake_boxes
    return [fake_result]


@patch("cv_service.detector.YOLO")
def test_detect_and_track_returns_detection_for_tracked_class(mock_yolo_cls):
    mock_model = MagicMock()
    mock_model.names = {0: "cow"}
    mock_model.track.return_value = _fake_results()
    mock_yolo_cls.return_value = mock_model

    detector = Detector(model_path="unused.pt")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect_and_track(frame)

    assert len(detections) == 1
    assert detections[0] == Detection(
        track_id=5, class_name="cow", confidence=0.87, bbox=(10.0, 20.0, 110.0, 220.0)
    )


@patch("cv_service.detector.YOLO")
def test_detect_and_track_filters_out_untracked_classes(mock_yolo_cls):
    mock_model = MagicMock()
    mock_model.names = {0: "person"}
    mock_model.track.return_value = _fake_results()
    mock_yolo_cls.return_value = mock_model

    detector = Detector(model_path="unused.pt")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect_and_track(frame)

    assert detections == []


@pytest.mark.slow
def test_real_yolo_model_loads_and_runs_on_blank_frame():
    detector = Detector(model_path="yolov8n.pt")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect_and_track(frame)
    assert isinstance(detections, list)


class TestTrackedClassesConfig:
    def test_defaults_to_livestock(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_tracked_class_names() == DEFAULT_TRACKED_CLASS_NAMES

    def test_reads_the_env_override(self):
        with patch.dict("os.environ", {"TRACKED_CLASSES": "person,dog"}, clear=True):
            assert get_tracked_class_names() == frozenset({"person", "dog"})

    def test_trims_spaces_and_lowercases(self):
        with patch.dict("os.environ", {"TRACKED_CLASSES": " Person , DOG "}, clear=True):
            assert get_tracked_class_names() == frozenset({"person", "dog"})

    def test_falls_back_to_defaults_when_blank(self):
        with patch.dict("os.environ", {"TRACKED_CLASSES": "   "}, clear=True):
            assert get_tracked_class_names() == DEFAULT_TRACKED_CLASS_NAMES

    def test_ignores_empty_items(self):
        with patch.dict("os.environ", {"TRACKED_CLASSES": "person,,"}, clear=True):
            assert get_tracked_class_names() == frozenset({"person"})


@patch("cv_service.detector.YOLO")
def test_detector_honours_the_configured_classes(mock_yolo_cls):
    """Отладка на ноутбучной камере: person должен проходить фильтр."""
    mock_model = MagicMock()
    mock_model.names = {0: "person"}
    mock_model.track.return_value = _fake_results()
    mock_yolo_cls.return_value = mock_model

    with patch.dict("os.environ", {"TRACKED_CLASSES": "person"}, clear=True):
        detector = Detector(model_path="unused.pt")

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = detector.detect_and_track(frame)

    assert len(detections) == 1
    assert detections[0].class_name == "person"


@patch("cv_service.detector.YOLO")
def test_explicit_argument_wins_over_env(mock_yolo_cls):
    mock_model = MagicMock()
    mock_model.names = {0: "person"}
    mock_model.track.return_value = _fake_results()
    mock_yolo_cls.return_value = mock_model

    with patch.dict("os.environ", {"TRACKED_CLASSES": "cow"}, clear=True):
        detector = Detector(model_path="unused.pt", tracked_classes=frozenset({"person"}))

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    assert len(detector.detect_and_track(frame)) == 1


# ---------------------------------------------------------------------------
# Что считаем скотом
# ---------------------------------------------------------------------------

from cv_service.detector import DEBUG_ONLY_CLASSES


class TestTrackedClasses:
    def test_livestock_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_tracked_class_names() == {"cow", "sheep", "horse"}

    def test_birds_are_not_livestock_by_default(self):
        """Вороны и голуби над загоном раздули бы поголовье."""
        with patch.dict("os.environ", {}, clear=True):
            assert "bird" not in get_tracked_class_names()

    def test_dogs_are_not_livestock_by_default(self):
        """Собака у кормушки записалась бы как визит животного."""
        with patch.dict("os.environ", {}, clear=True):
            assert "dog" not in get_tracked_class_names()

    def test_a_poultry_farm_can_add_birds(self):
        with patch.dict("os.environ", {"TRACKED_CLASSES": "bird"}, clear=True):
            assert get_tracked_class_names() == {"bird"}

    def test_a_forgotten_debug_setting_is_announced(self, capsys):
        """
        Тихая беда: сервис работает, а скот не считается вовсе.
        Пусть говорит об этом вслух при запуске.
        """
        with patch.dict("os.environ", {"TRACKED_CLASSES": "person"}, clear=True):
            get_tracked_class_names()
        assert "ВНИМАНИЕ" in capsys.readouterr().out

    def test_a_normal_setting_says_nothing(self, capsys):
        with patch.dict("os.environ", {"TRACKED_CLASSES": "cow"}, clear=True):
            get_tracked_class_names()
        assert capsys.readouterr().out == ""

    def test_debug_classes_are_named_explicitly(self):
        assert "person" in DEBUG_ONLY_CLASSES
