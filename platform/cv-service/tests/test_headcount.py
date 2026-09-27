from unittest.mock import patch

from cv_service.detector import Detection
from cv_service.headcount import (
    DEFAULT_INTERVAL_S,
    HeadcountAggregator,
    headcount_interval_s,
)


def _cow(track_id: int, name: str = "cow") -> Detection:
    return Detection(track_id=track_id, class_name=name, confidence=0.9, bbox=(0, 0, 1, 1))


class TestInterval:
    def test_default_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            assert headcount_interval_s() == DEFAULT_INTERVAL_S

    def test_reads_the_override(self):
        with patch.dict("os.environ", {"HEADCOUNT_INTERVAL_S": "30"}, clear=True):
            assert headcount_interval_s() == 30.0

    def test_falls_back_on_garbage(self):
        with patch.dict("os.environ", {"HEADCOUNT_INTERVAL_S": "часто"}, clear=True):
            assert headcount_interval_s() == DEFAULT_INTERVAL_S


class TestAggregator:
    def test_not_due_before_the_interval_passes(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1)], now=0.0)
        assert agg.due(now=30.0) is False

    def test_due_after_the_interval(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1)], now=0.0)
        assert agg.due(now=60.0) is True

    def test_not_due_before_anything_was_seen(self):
        assert HeadcountAggregator(interval_s=60).due(now=1000.0) is False

    def test_counts_distinct_animals_not_observations(self):
        """Одна корова, замеченная 30 раз, — это одна корова."""
        agg = HeadcountAggregator(interval_s=60)
        for moment in range(0, 60, 2):
            agg.add([_cow(1)], now=float(moment))
        summary = agg.take()
        assert summary["unique_count"] == 1

    def test_counts_several_animals(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1), _cow(2)], now=0.0)
        agg.add([_cow(2), _cow(3)], now=10.0)
        assert agg.take()["unique_count"] == 3

    def test_records_the_peak_in_a_single_frame(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1)], now=0.0)
        agg.add([_cow(1), _cow(2), _cow(3)], now=10.0)
        agg.add([_cow(1)], now=20.0)
        assert agg.take()["peak_in_frame"] == 3

    def test_splits_counts_by_class(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1), _cow(2), _cow(3, "sheep")], now=0.0)
        summary = agg.take()
        assert summary["by_class"] == {"cow": 2, "sheep": 1}

    def test_returns_nothing_when_nobody_was_seen(self):
        """Писать нули каждую минуту круглосуточно незачем."""
        agg = HeadcountAggregator(interval_s=60)
        agg.add([], now=0.0)
        assert agg.take() is None

    def test_resets_between_windows(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1), _cow(2)], now=0.0)
        agg.take()
        agg.add([_cow(5)], now=60.0)
        summary = agg.take()
        assert summary["unique_count"] == 1

    def test_window_restarts_after_take(self):
        agg = HeadcountAggregator(interval_s=60)
        agg.add([_cow(1)], now=0.0)
        agg.take()
        assert agg.due(now=61.0) is False
