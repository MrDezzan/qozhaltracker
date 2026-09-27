import os
import uuid
import pytest
from supabase import create_client

pytestmark = pytest.mark.integration


def _client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        pytest.skip("SUPABASE_URL / SUPABASE_SERVICE_KEY не заданы")
    return create_client(url, key)


def test_full_row_chain_can_be_inserted_and_read_back():
    client = _client()
    farm_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())

    client.table("farms").insert(
        {"id": farm_id, "name": "Тестовая ферма", "owner_user_id": owner_id}
    ).execute()

    camera = (
        client.table("cameras")
        .insert({"farm_id": farm_id, "name": "Камера 1", "source_uri": "0"})
        .execute()
        .data[0]
    )

    event = (
        client.table("events")
        .insert(
            {
                "farm_id": farm_id,
                "camera_id": camera["id"],
                "event_type": "detected",
                "payload": {"track_id": 1},
            }
        )
        .execute()
        .data[0]
    )

    fetched = (
        client.table("events").select("*").eq("id", event["id"]).single().execute().data
    )
    assert fetched["event_type"] == "detected"
    assert fetched["farm_id"] == farm_id

    client.table("farms").delete().eq("id", farm_id).execute()
