import pytest
from pydantic import ValidationError

from cv_service.events import AnimalEvent


def test_valid_event_serializes_to_row():
    event = AnimalEvent(
        farm_id="11111111-1111-1111-1111-111111111111",
        camera_id="22222222-2222-2222-2222-222222222222",
        event_type="detected",
        payload={"track_id": 7, "bbox": [10, 20, 100, 200], "confidence": 0.91},
    )
    row = event.to_row()
    assert row["farm_id"] == "11111111-1111-1111-1111-111111111111"
    assert row["event_type"] == "detected"
    assert row["payload"]["track_id"] == 7
    assert "occurred_at" in row


def test_invalid_event_type_rejected():
    with pytest.raises(ValidationError):
        AnimalEvent(
            farm_id="11111111-1111-1111-1111-111111111111",
            camera_id="22222222-2222-2222-2222-222222222222",
            event_type="not_a_real_type",
            payload={},
        )


def test_animal_id_optional_for_unidentified_tracks():
    event = AnimalEvent(
        farm_id="11111111-1111-1111-1111-111111111111",
        camera_id="22222222-2222-2222-2222-222222222222",
        event_type="detected",
        payload={},
    )
    assert event.animal_id is None
