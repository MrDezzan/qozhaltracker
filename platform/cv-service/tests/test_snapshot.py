from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.snapshot import (
    DEFAULT_INTERVAL_S,
    explain_upload_error,
    SNAPSHOT_BUCKET,
    encode_snapshot,
    snapshot_interval_s,
    snapshot_path,
    snapshots_enabled,
    upload_snapshot,
)


class TestInterval:
    def test_default_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            assert snapshot_interval_s() == DEFAULT_INTERVAL_S

    def test_reads_the_override(self):
        with patch.dict("os.environ", {"SNAPSHOT_INTERVAL_S": "30"}, clear=True):
            assert snapshot_interval_s() == 30.0

    def test_falls_back_on_garbage(self):
        with patch.dict("os.environ", {"SNAPSHOT_INTERVAL_S": "быстро"}, clear=True):
            assert snapshot_interval_s() == DEFAULT_INTERVAL_S

    def test_zero_disables_snapshots(self):
        with patch.dict("os.environ", {"SNAPSHOT_INTERVAL_S": "0"}, clear=True):
            assert snapshots_enabled() is False

    def test_enabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert snapshots_enabled() is True


def test_snapshot_path_starts_with_the_farm():
    """На первом сегменте пути держатся права доступа — он обязан быть фермой."""
    path = snapshot_path("farm-1", "cam-2")
    assert path == "farm-1/cam-2.jpg"
    assert path.split("/")[0] == "farm-1"


def _frame(width=1920, height=1080):
    rng = np.random.default_rng(seed=1)
    return rng.integers(0, 255, (height, width, 3), dtype=np.uint8)


def test_encode_snapshot_returns_jpeg_bytes():
    data = encode_snapshot(_frame())
    assert isinstance(data, bytes)
    # Признак JPEG: файл начинается с FF D8
    assert data[:2] == b"\xff\xd8"


def test_encode_snapshot_shrinks_wide_frames():
    big = encode_snapshot(_frame(1920, 1080))
    small = encode_snapshot(_frame(640, 360))
    assert len(big) < 400_000
    assert len(small) < len(big)


def test_encode_snapshot_keeps_small_frames_as_is():
    data = encode_snapshot(_frame(320, 240))
    assert data[:2] == b"\xff\xd8"


def test_encode_snapshot_quality_affects_size():
    high = encode_snapshot(_frame(640, 480), quality=90)
    low = encode_snapshot(_frame(640, 480), quality=30)
    assert len(low) < len(high)


def test_upload_snapshot_writes_to_the_bucket_with_upsert():
    client = MagicMock()
    path = upload_snapshot(client, "farm-1", "cam-2", _frame(640, 480))

    client.storage.from_.assert_called_once_with(SNAPSHOT_BUCKET)
    upload = client.storage.from_.return_value.upload
    kwargs = upload.call_args.kwargs
    assert kwargs["path"] == "farm-1/cam-2.jpg"
    assert kwargs["file_options"]["upsert"] == "true"
    assert kwargs["file_options"]["content-type"] == "image/jpeg"
    assert path == "farm-1/cam-2.jpg"


def test_encode_snapshot_raises_on_bad_frame():
    with patch("cv_service.snapshot.cv2.imencode", return_value=(False, None)):
        with pytest.raises(RuntimeError, match="закодировать снимок"):
            encode_snapshot(_frame(320, 240))


class TestUploadErrorHints:
    def test_missing_bucket_points_to_the_migration(self):
        hint = explain_upload_error(Exception('{"message":"Bucket not found"}'))
        assert "0003_snapshots.sql" in hint

    def test_denied_access_points_to_the_policy_fix(self):
        hint = explain_upload_error(
            Exception("new row violates row-level security policy")
        )
        assert "0005_fix_snapshot_policies.sql" in hint

    def test_unauthorized_points_to_the_policy_fix(self):
        assert "0005" in explain_upload_error(Exception("Unauthorized"))

    def test_unknown_error_is_passed_through(self):
        assert explain_upload_error(Exception("что-то новое")) == "что-то новое"


def test_upload_snapshot_wraps_storage_errors_with_a_hint():
    client = MagicMock()
    client.storage.from_.return_value.upload.side_effect = Exception("Bucket not found")

    with pytest.raises(RuntimeError, match="0003_snapshots.sql"):
        upload_snapshot(client, "farm-1", "cam-2", _frame(320, 240))


def test_snapshot_upload_forbids_caching():
    """
    Путь снимка постоянный, файл перезаписывается. Со стандартным часом
    жизни в кэше браузер и сеть доставки продолжали бы отдавать первый
    кадр — живой просмотр замирал бы на картинке.
    """
    from unittest.mock import MagicMock
    import numpy as np

    client = MagicMock()
    rng = np.random.default_rng(seed=1)
    frame = rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)

    upload_snapshot(client, "farm-1", "cam-1", frame)

    options = client.storage.from_.return_value.upload.call_args[1]["file_options"]
    assert options["upsert"] == "true"

    # Только число: библиотека подставляет значение в шаблон «max-age=…»,
    # и слово превращает заголовок в недействительный «max-age=no-store»
    assert options["cache-control"].isdigit()
    assert int(options["cache-control"]) == 0
