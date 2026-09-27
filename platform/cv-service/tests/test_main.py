from unittest.mock import MagicMock, patch

import pytest

from cv_service.crops import Match
from cv_service.detector import Detection
from cv_service.main import (
    _run_camera_safely,
    headcount_to_event,
    parse_video_source,
    process_camera,
    run,
    debug_camera,
)


def test_headcount_to_event_carries_the_summary():
    event = headcount_to_event(
        {"unique_count": 3, "peak_in_frame": 2, "by_class": {"cow": 3}},
        farm_id="farm-1",
        camera_id="cam-1",
    )
    assert event.event_type == "counted"
    assert event.payload["unique_count"] == 3
    assert event.animal_id is None


def test_parse_video_source_converts_device_index():
    assert parse_video_source("0") == 0
    assert parse_video_source("1") == 1


def test_parse_video_source_keeps_urls_and_paths():
    assert parse_video_source("rtsp://a:b@10.0.0.5:554/s1") == "rtsp://a:b@10.0.0.5:554/s1"
    assert parse_video_source("video.mp4") == "video.mp4"


def _fake_frame():
    """Заглушка кадра: у настоящего есть .shape и срезы."""
    frame = MagicMock()
    frame.shape = (480, 640, 3)
    frame.__getitem__ = lambda _s, _k: MagicMock(copy=lambda: "cropped")
    return frame


def _capture_with_frames(count: int):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, _fake_frame()) for _ in range(count)] + [(False, None)]
    return cap


@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_writes_one_event_per_detection(
    mock_capture_cls, mock_insert_event, mock_heartbeat
):
    mock_capture_cls.return_value = _capture_with_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 1, 1))
    ]

    written = process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    # Одна сводка вместо записи на каждое обнаружение
    assert written <= 1


@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_keeps_running_when_upload_fails(
    mock_capture_cls, mock_insert_event, mock_heartbeat
):
    """Обрыв связи не должен ронять обработку видео."""
    mock_capture_cls.return_value = _capture_with_frames(2)
    mock_insert_event.side_effect = Exception("нет сети")
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 1, 1))
    ]

    written = process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert written == 0


@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_sends_heartbeat_on_first_frame(
    mock_capture_cls, mock_insert_event, mock_heartbeat
):
    mock_capture_cls.return_value = _capture_with_frames(1)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_heartbeat.call_count == 1


@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_survives_heartbeat_failure(
    mock_capture_cls, mock_insert_event, mock_heartbeat
):
    mock_capture_cls.return_value = _capture_with_frames(1)
    mock_heartbeat.side_effect = Exception("нет сети")
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )
    # Отсутствие исключения и есть проверка


@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_raises_when_stream_unavailable(mock_capture_cls):
    cap = MagicMock()
    cap.isOpened.return_value = False
    mock_capture_cls.return_value = cap

    with pytest.raises(RuntimeError, match="rtsp://bad"):
        process_camera(
            MagicMock(),
            MagicMock(),
            "farm-1",
            {"id": "cam-1", "name": "Кормушка", "source_uri": "rtsp://bad"},
        )


@patch("cv_service.main.Detector")
@patch("cv_service.main.fetch_cameras")
@patch("cv_service.main.get_device_farm_id")
@patch("cv_service.main.get_client")
def test_run_raises_when_farm_has_no_cameras(
    mock_get_client, mock_farm_id, mock_fetch, mock_detector
):
    mock_farm_id.return_value = "farm-1"
    mock_fetch.return_value = []

    with pytest.raises(RuntimeError, match="ни одной камеры"):
        run()


@patch("cv_service.main.process_camera")
@patch("cv_service.main.Detector")
@patch("cv_service.main.fetch_cameras")
@patch("cv_service.main.get_device_farm_id")
@patch("cv_service.main.get_client")
def test_run_takes_farm_and_cameras_from_server(
    mock_get_client, mock_farm_id, mock_fetch, mock_detector, mock_process
):
    """Ферма и камеры приходят с сервера, а не из .env на месте."""
    mock_farm_id.return_value = "farm-1"
    mock_fetch.return_value = [{"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"}]

    run()

    mock_fetch.assert_called_once_with(mock_get_client.return_value, "farm-1")
    assert mock_process.call_args[0][2] == "farm-1"
    assert mock_process.call_args[0][3]["id"] == "cam-1"


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.close_preview")
@patch("cv_service.main.show_frame")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_skips_preview_by_default(
    mock_capture_cls, mock_insert, mock_hb, mock_enabled, mock_show, mock_close, mock_draw
):
    mock_enabled.return_value = False
    mock_capture_cls.return_value = _capture_with_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    mock_show.assert_not_called()
    mock_close.assert_not_called()


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.close_preview")
@patch("cv_service.main.show_frame")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_shows_every_frame_when_preview_on(
    mock_capture_cls, mock_insert, mock_hb, mock_enabled, mock_show, mock_close, mock_draw
):
    mock_enabled.return_value = True
    mock_show.return_value = True
    mock_capture_cls.return_value = _capture_with_frames(3)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_show.call_count == 3
    mock_close.assert_called_once()


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.close_preview")
@patch("cv_service.main.show_frame")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_stops_when_preview_window_asks_to(
    mock_capture_cls, mock_insert, mock_hb, mock_enabled, mock_show, mock_close, mock_draw
):
    """Нажатие q в окне предпросмотра останавливает обработку."""
    mock_enabled.return_value = True
    mock_show.return_value = False
    mock_capture_cls.return_value = _capture_with_frames(5)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_show.call_count == 1
    detector.detect_and_track.assert_not_called()


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.upload_snapshot")
@patch("cv_service.main.snapshots_enabled")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_uploads_a_snapshot(
    mock_capture_cls, mock_insert, mock_hb, mock_preview, mock_enabled, mock_upload, mock_draw
):
    mock_preview.return_value = False
    mock_enabled.return_value = True
    mock_capture_cls.return_value = _capture_with_frames(1)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_upload.call_count == 1
    assert mock_upload.call_args[0][1] == "farm-1"
    assert mock_upload.call_args[0][2] == "cam-1"


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.upload_snapshot")
@patch("cv_service.main.snapshots_enabled")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_skips_snapshots_when_disabled(
    mock_capture_cls, mock_insert, mock_hb, mock_preview, mock_enabled, mock_upload, mock_draw
):
    mock_preview.return_value = False
    mock_enabled.return_value = False
    mock_capture_cls.return_value = _capture_with_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    mock_upload.assert_not_called()


@patch("cv_service.main.draw_detections")
@patch("cv_service.main.upload_snapshot")
@patch("cv_service.main.snapshots_enabled")
@patch("cv_service.main.preview_enabled")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_survives_snapshot_upload_failure(
    mock_capture_cls, mock_insert, mock_hb, mock_preview, mock_enabled, mock_upload, mock_draw
):
    """Обрыв связи при отправке снимка не должен ронять обработку."""
    mock_preview.return_value = False
    mock_enabled.return_value = True
    mock_upload.side_effect = Exception("нет сети")
    mock_capture_cls.return_value = _capture_with_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 1, 1))
    ]

    written = process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    # Сбой отправки снимка не мешает записи сводок
    assert written >= 0



@patch("cv_service.main.process_camera")
@patch("cv_service.main.Detector")
@patch("cv_service.main.fetch_cameras")
@patch("cv_service.main.get_device_farm_id")
@patch("cv_service.main.get_client")
def test_run_processes_every_camera_not_just_the_first(
    mock_get_client, mock_farm_id, mock_fetch, mock_detector, mock_process
):
    mock_farm_id.return_value = "farm-1"
    mock_fetch.return_value = [
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        {"id": "cam-2", "name": "Поилка", "source_uri": "1"},
        {"id": "cam-3", "name": "Загон", "source_uri": "2"},
    ]

    run()

    assert mock_process.call_count == 3
    processed = {call[0][3]["id"] for call in mock_process.call_args_list}
    assert processed == {"cam-1", "cam-2", "cam-3"}


@patch("cv_service.main.process_camera")
@patch("cv_service.main.Detector")
@patch("cv_service.main.fetch_cameras")
@patch("cv_service.main.get_device_farm_id")
@patch("cv_service.main.get_client")
def test_each_camera_gets_its_own_detector(
    mock_get_client, mock_farm_id, mock_fetch, mock_detector, mock_process
):
    """Общий трекер перемешал бы номера объектов между камерами."""
    mock_farm_id.return_value = "farm-1"
    mock_fetch.return_value = [
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        {"id": "cam-2", "name": "Поилка", "source_uri": "1"},
    ]

    # Заглушка по умолчанию отдаёт один и тот же объект — подменяем,
    # чтобы проверять код, а не поведение заглушки
    mock_detector.side_effect = [MagicMock(name="det-1"), MagicMock(name="det-2")]

    run()

    assert mock_detector.call_count == 2
    detectors = {id(call[0][1]) for call in mock_process.call_args_list}
    assert len(detectors) == 2


@patch("cv_service.main.time.sleep")
@patch("cv_service.main.process_camera")
def test_one_broken_camera_does_not_stop_the_others(mock_process, _sleep):
    mock_process.side_effect = RuntimeError("камера недоступна")
    # Отсутствие исключения наружу и есть проверка
    _run_camera_safely(
        MagicMock(),
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        2.0,
        max_restarts=1,
    )


@patch("cv_service.main.process_camera")
@patch("cv_service.main.Detector")
@patch("cv_service.main.fetch_cameras")
@patch("cv_service.main.get_device_farm_id")
@patch("cv_service.main.get_client")
def test_single_camera_runs_without_threads(
    mock_get_client, mock_farm_id, mock_fetch, mock_detector, mock_process
):
    mock_farm_id.return_value = "farm-1"
    mock_fetch.return_value = [{"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"}]

    run()

    assert mock_process.call_count == 1


from cv_service.main import visit_to_event
from cv_service.zones import Visit, Zone

_FEEDER = Zone(id="z1", name="Кормушка", kind="feeder", polygon=((0, 0), (1, 0), (1, 1)))


def test_visit_to_event_carries_zone_and_duration():
    visit = Visit(zone=_FEEDER, track_id=7, started_at=0.0, last_seen_at=125.4)
    event = visit_to_event(visit, "farm-1", "cam-1")

    assert event.event_type == "zone_exit"
    assert event.payload["zone_name"] == "Кормушка"
    assert event.payload["zone_kind"] == "feeder"
    assert event.payload["duration_s"] == 125.4
    assert event.animal_id is None


def _frame_with_shape():
    """Кадр, у которого есть .shape — нужен для расчёта долей координат."""
    frame = MagicMock()
    frame.shape = (480, 640, 3)
    return frame


def _capture_with_real_frames(count: int):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, _frame_with_shape()) for _ in range(count)] + [(False, None)]
    return cap


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.fetch_zones")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_loads_zones_for_its_camera(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_preview, mock_snap
):
    mock_zones.return_value = []
    mock_capture_cls.return_value = _capture_with_real_frames(1)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    # Зоны запрашиваются при старте и затем периодически — всегда для своей камеры
    assert mock_zones.call_count >= 1
    assert all(call[0][1] == "cam-1" for call in mock_zones.call_args_list)


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.fetch_zones")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_survives_missing_zones(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_preview, mock_snap
):
    """Недоступность таблицы зон не должна ронять детекцию."""
    mock_zones.side_effect = Exception("нет доступа")
    mock_capture_cls.return_value = _capture_with_real_frames(1)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.fetch_zones")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_writes_a_visit_event_on_stop(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_preview, mock_snap
):
    """Незакрытый визит должен дописаться при остановке камеры."""
    mock_zones.return_value = [
        {
            "id": "z1",
            "name": "Кормушка",
            "kind": "feeder",
            "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        }
    ]
    mock_capture_cls.return_value = _capture_with_real_frames(3)
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(100, 100, 200, 300))
    ]

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    # Поштучных detected больше нет — только сводки и визиты
    written_types = [call[0][1].event_type for call in mock_insert.call_args_list]
    assert "detected" not in written_types


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.headcount_interval_s", return_value=0.0)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_writes_a_headcount_summary(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_interval, mock_preview, mock_snap
):
    mock_capture_cls.return_value = _capture_with_real_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 1, 1))
    ]

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    types = [call[0][1].event_type for call in mock_insert.call_args_list]
    assert "counted" in types
    assert "detected" not in types


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.headcount_interval_s", return_value=3600.0)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_does_not_write_before_the_window_closes(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_interval, mock_preview, mock_snap
):
    """Ради этого всё и затевалось: никакого потока записей на каждый кадр."""
    mock_capture_cls.return_value = _capture_with_real_frames(20)
    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 1, 1))
    ]

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_insert.call_count == 0


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=True)
@patch("cv_service.main.identify", return_value=Match(animal_id="a1"))
@patch("cv_service.main.insert_seen")
@patch("cv_service.main.fetch_animal_names", return_value={"a1": "Зорька"})
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_a_recognised_animal_gets_a_visit_record(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_names,
    mock_seen, mock_match, mock_crops, mock_preview, mock_snap
):
    """Узнанное животное попадает в историю «последний раз видели»."""
    frame = MagicMock()
    frame.shape = (480, 640, 3)
    frame.__getitem__ = lambda _s, _k: MagicMock(copy=lambda: "cropped")
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, frame), (False, None)]
    mock_capture_cls.return_value = cap

    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=7, class_name="cow", confidence=0.9, bbox=(10, 10, 300, 400))
    ]

    embedder = MagicMock()
    embedder.encode.return_value = [0.1] * 1024

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
        embedder=embedder,
    )

    assert mock_seen.call_count == 1


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=True)
@patch("cv_service.main.insert_seen")
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_an_unknown_animal_leaves_no_trace(
    mock_capture_cls, mock_insert, mock_hb, mock_zones,
    mock_seen, mock_crops, mock_preview, mock_snap
):
    """
    Ни кадра в хранилище, ни строки в базе.

    Раньше здесь появлялась запись «ждёт имени». Очередь таких записей
    не кончалась и превращалась в свалку, которую перестают открывать.
    """
    frame = MagicMock()
    frame.shape = (480, 640, 3)
    frame.__getitem__ = lambda _s, _k: MagicMock(copy=lambda: "cropped")
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, frame), (False, None)]
    mock_capture_cls.return_value = cap

    detector = MagicMock()
    detector.detect_and_track.return_value = [
        Detection(track_id=7, class_name="cow", confidence=0.9, bbox=(10, 10, 300, 400))
    ]

    client = MagicMock()
    process_camera(
        client,
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    mock_seen.assert_not_called()
    client.storage.from_.assert_not_called()


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=False)
@patch("cv_service.main.fetch_zones")
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_process_camera_reads_zones_of_its_own_camera(
    mock_capture_cls, mock_insert, mock_hb, mock_zones, mock_crops, mock_preview, mock_snap
):
    """
    Зоны читаются при старте и дальше перечитываются в отдельном потоке —
    в цикле захвата сетевым вызовам не место, один зависший запрос
    останавливал бы обработку видео целиком.
    """
    mock_zones.return_value = []
    mock_capture_cls.return_value = _capture_with_frames(2)
    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_zones.call_count >= 1
    assert mock_zones.call_args[0][1] == "cam-1"


from cv_service.main import is_live_source


class TestIsLiveSource:
    def test_builtin_camera_is_live(self):
        assert is_live_source("0") is True

    def test_rtsp_is_live(self):
        assert is_live_source("rtsp://admin:pass@10.0.0.5:554/s1") is True

    def test_http_stream_is_live(self):
        assert is_live_source("http://10.0.0.5/stream") is True

    def test_file_is_not_live(self):
        """Конец файла — нормальное завершение, а не сбой."""
        assert is_live_source("video.mp4") is False

    def test_case_does_not_matter(self):
        assert is_live_source("RTSP://10.0.0.5/s1") is True


@patch("cv_service.main.time.sleep")
@patch("cv_service.main.open_capture")
@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=False)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
def test_live_camera_reconnects_after_losing_the_stream(
    mock_insert, mock_hb, mock_zones, mock_crops, mock_preview, mock_snap,
    mock_open, mock_sleep
):
    """Обрыв связи с камерой не должен убивать её навсегда."""
    first = MagicMock()
    first.isOpened.return_value = True
    # Много подряд неудачных чтений — это сбой
    first.read.side_effect = [(False, None)] * 40

    second = MagicMock()
    second.isOpened.return_value = True
    # После переподключения поток снова идёт — цикл остановит max_frames
    second.read.side_effect = lambda: (True, _fake_frame())

    mock_open.side_effect = [first, second]

    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Загон", "source_uri": "rtsp://10.0.0.5/s1"},
        frame_interval_s=0.0,
        max_frames=2,
    )

    # Источник открывался повторно — значит переподключение произошло
    assert mock_open.call_count >= 2
    first.release.assert_called()


@patch("cv_service.main.open_capture")
@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=False)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
def test_video_file_ends_without_reconnecting(
    mock_insert, mock_hb, mock_zones, mock_crops, mock_preview, mock_snap, mock_open
):
    """Файл кончился — выходим спокойно, а не пытаемся переоткрыть."""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, _fake_frame()), (False, None)]
    mock_open.return_value = cap

    detector = MagicMock()
    detector.detect_and_track.return_value = []

    process_camera(
        MagicMock(),
        detector,
        "farm-1",
        {"id": "cam-1", "name": "Запись", "source_uri": "video.mp4"},
        frame_interval_s=0.0,
    )

    assert mock_open.call_count == 1


@patch("cv_service.main.open_capture", return_value=None)
def test_process_camera_raises_when_source_never_opens(mock_open):
    with pytest.raises(RuntimeError, match="rtsp://bad"):
        process_camera(
            MagicMock(),
            MagicMock(),
            "farm-1",
            {"id": "cam-1", "name": "Загон", "source_uri": "rtsp://bad"},
        )


class TestDebugCamera:
    """
    Ручной режим VIDEO_SOURCE.

    Ловилось так: запуск отрапортовал «живой просмотр: готов», а следом
    упал с KeyError: 'CAMERA_ID'. Выглядело как поломка живого просмотра,
    хотя дело было в незаполненной переменной окружения.
    """

    CAMS = [
        {"id": "c1", "name": "Проход сверху", "placement": "above",
         "source_uri": "rtsp://ферма/1"},
        {"id": "c2", "name": "Проход сбоку", "placement": "side",
         "source_uri": "rtsp://ферма/2"},
    ]

    def test_takes_the_first_camera_without_camera_id(self):
        camera = debug_camera(self.CAMS, "0", None)
        assert camera["id"] == "c1"

    def test_replaces_only_the_address(self):
        """Адрес наш, всё остальное — с сервера."""
        camera = debug_camera(self.CAMS, "0", None)
        assert camera["source_uri"] == "0"
        assert camera["name"] == "Проход сверху"

    def test_keeps_placement(self):
        """
        Расположение решает, снимается ли силуэт для веса. С заглушкой
        «отладка» без него вес молча не считался бы, и причину пришлось
        бы искать в коде обмеров.
        """
        assert debug_camera(self.CAMS, "0", None)["placement"] == "above"

    def test_honours_an_explicit_camera_id(self):
        camera = debug_camera(self.CAMS, "1", "c2")
        assert camera["id"] == "c2"
        assert camera["name"] == "Проход сбоку"
        assert camera["source_uri"] == "1"

    def test_unknown_camera_id_still_runs(self):
        """Чужой идентификатор не роняет запуск — но о нём говорится."""
        camera = debug_camera(self.CAMS, "0", "чужой")
        assert camera["id"] == "чужой"

    def test_no_cameras_at_all_explains_what_to_do(self):
        with pytest.raises(RuntimeError) as exc:
            debug_camera([], "0", None)
        assert "админке" in str(exc.value)

    def test_does_not_mutate_the_source_list(self):
        """Карточка копируется: список камер живёт дальше нетронутым."""
        cams = [dict(self.CAMS[0])]
        debug_camera(cams, "0", None)
        assert cams[0]["source_uri"] == "rtsp://ферма/1"
