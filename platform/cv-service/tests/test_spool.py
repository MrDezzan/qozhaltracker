import json
import sqlite3

import pytest

from cv_service.spool import EventSpool, drain


@pytest.fixture
def spool(tmp_path):
    s = EventSpool(path=str(tmp_path / "spool.db"))
    yield s
    s.close()


def _event(n: int) -> dict:
    return {"event_type": "counted", "payload": {"unique_count": n}}


class TestSpool:
    def test_keeps_what_it_was_given(self, spool):
        spool.put(_event(1))
        assert spool.count() == 1
        assert spool.take()[0][1] == _event(1)

    def test_returns_events_in_order(self, spool):
        for n in range(5):
            spool.put(_event(n))
        counts = [row["payload"]["unique_count"] for _, row in spool.take()]
        assert counts == [0, 1, 2, 3, 4]

    def test_remove_frees_the_queue(self, spool):
        spool.put(_event(1))
        row_id, _ = spool.take()[0]
        spool.remove([row_id])
        assert spool.count() == 0

    def test_survives_a_restart(self, tmp_path):
        """Ради этого и взят SQLite: выключение питания не должно стирать очередь."""
        path = str(tmp_path / "spool.db")
        first = EventSpool(path=path)
        first.put(_event(7))
        first.close()

        second = EventSpool(path=path)
        assert second.count() == 1
        second.close()

    def test_drops_the_oldest_when_full(self, tmp_path):
        """Связи нет неделями — свежие данные полезнее самых старых."""
        spool = EventSpool(path=str(tmp_path / "spool.db"), capacity=3)
        for n in range(6):
            spool.put(_event(n))

        assert spool.count() == 3
        counts = [row["payload"]["unique_count"] for _, row in spool.take()]
        assert counts == [3, 4, 5]
        spool.close()

    def test_a_corrupted_row_does_not_block_the_queue(self, tmp_path):
        path = str(tmp_path / "spool.db")
        spool = EventSpool(path=path)
        spool.put(_event(1))
        spool.close()

        conn = sqlite3.connect(path)
        conn.execute("update pending set body = ?", ("{не json",))
        conn.commit()
        conn.close()

        spool = EventSpool(path=path)
        assert spool.take() == []
        assert spool.count() == 0
        spool.close()

    def test_creates_missing_directories(self, tmp_path):
        spool = EventSpool(path=str(tmp_path / "a" / "b" / "spool.db"))
        spool.put(_event(1))
        assert spool.count() == 1
        spool.close()


class TestDrain:
    def test_sends_and_clears(self, spool):
        for n in range(3):
            spool.put(_event(n))
        sent = []

        assert drain(spool, sent.append) == 3
        assert spool.count() == 0
        assert len(sent) == 3

    def test_stops_at_the_first_failure_and_keeps_the_rest(self, spool):
        """
        Если связи нет, перебирать очередь до конца бессмысленно.
        Главное — ничего не потерять и не переставить местами.
        """
        for n in range(3):
            spool.put(_event(n))

        calls = []

        def send(row):
            calls.append(row)
            if len(calls) == 2:
                raise RuntimeError("нет сети")

        assert drain(spool, send) == 1
        assert spool.count() == 2
        remaining = [row["payload"]["unique_count"] for _, row in spool.take()]
        assert remaining == [1, 2]

    def test_empty_queue_is_not_an_error(self, spool):
        assert drain(spool, lambda row: None) == 0

    def test_survives_a_full_outage_and_recovers(self, spool):
        """Полный сценарий: связь пропала, события копились, связь вернулась."""
        offline = True

        def send(row):
            if offline:
                raise RuntimeError("нет сети")

        for n in range(10):
            spool.put(_event(n))
        assert drain(spool, send) == 0
        assert spool.count() == 10

        offline = False
        assert drain(spool, send) == 10
        assert spool.count() == 0

    def test_the_stored_row_is_plain_json(self, spool):
        """Буфер не должен зависеть от версии моделей: внутри обычный JSON."""
        spool.put(_event(1))
        assert json.dumps(spool.take()[0][1])
