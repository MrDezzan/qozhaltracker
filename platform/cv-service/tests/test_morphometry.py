from unittest.mock import MagicMock

from cv_service.detector import Detection
from cv_service.morphometry import (
    MorphometryCollector,
    Silhouette,
    insert_measurement,
    measure,
    weighing_enabled,
)

WIDTH, HEIGHT = 1000, 800


def _rect_mask(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def _cow(track_id=1, x1=300, y1=300, x2=600, y2=420):
    """Силуэт вытянут по горизонтали — как корова сверху."""
    return Detection(
        track_id=track_id,
        class_name="cow",
        confidence=0.9,
        bbox=(x1, y1, x2, y2),
        mask=_rect_mask(x1, y1, x2, y2),
    )


class TestMeasure:
    def test_measures_area_and_sides(self):
        result = measure(_cow(), WIDTH, HEIGHT)
        assert result is not None
        assert round(result.area_px) == 300 * 120
        assert round(result.length_px) == 300
        assert round(result.width_px) == 120

    def test_rejects_detection_without_a_mask(self):
        """Обычная рамка не годится: площадь прямоугольника — не площадь тела."""
        detection = Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 10, 10))
        assert measure(detection, WIDTH, HEIGHT) is None

    def test_rejects_a_broken_frame(self):
        assert measure(_cow(), 0, 0) is None

    def test_rejects_a_too_small_silhouette(self):
        """Далёкое животное даёт рваный контур, площадь скачет от кадра к кадру."""
        assert measure(_cow(x1=10, y1=10, x2=40, y2=25), WIDTH, HEIGHT) is None

    def test_rejects_an_implausible_shape(self):
        """Почти квадрат — это не корова сверху, а слипшиеся объекты или мусор."""
        assert measure(_cow(x1=300, y1=300, x2=600, y2=590), WIDTH, HEIGHT) is None

    def test_lowers_quality_at_the_frame_edge(self):
        """Срезанный краем силуэт занижает площадь — это системная ошибка."""
        edge = measure(_cow(x1=0, y1=300, x2=300, y2=420), WIDTH, HEIGHT)
        assert edge is not None
        assert edge.quality < 0.8

    def test_lowers_quality_when_animals_overlap(self):
        """Две слипшиеся маски выглядят как одно очень большое животное."""
        first = _cow(track_id=1, x1=300, y1=300, x2=600, y2=420)
        second = _cow(track_id=2, x1=550, y1=310, x2=850, y2=430)
        result = measure(first, WIDTH, HEIGHT, neighbours=[first, second])
        assert result is not None
        assert result.quality < 0.8

    def test_a_lone_animal_in_the_middle_is_full_quality(self):
        result = measure(_cow(), WIDTH, HEIGHT, neighbours=[_cow()])
        assert result is not None
        assert result.quality == 1.0


class TestCollector:
    def test_needs_several_samples_before_reporting(self):
        collector = MorphometryCollector(min_samples=5)
        for _ in range(4):
            collector.add([_cow()], WIDTH, HEIGHT)
        assert collector.summarize(1) is None

        collector.add([_cow()], WIDTH, HEIGHT)
        assert collector.summarize(1) is not None

    def test_median_ignores_a_bad_frame(self):
        """
        Животное нагнулось к кормушке — на одном кадре силуэт вдвое короче.
        Медиана такой выброс отбрасывает, среднее бы его размазало.
        """
        collector = MorphometryCollector(min_samples=3)
        for _ in range(4):
            collector.add([_cow(x1=300, y1=300, x2=600, y2=420)], WIDTH, HEIGHT)
        collector.add([_cow(x1=300, y1=300, x2=450, y2=420)], WIDTH, HEIGHT)

        result = collector.summarize(1)
        assert result is not None
        assert round(result.length_px) == 300

    def test_skips_low_quality_frames(self):
        collector = MorphometryCollector(min_samples=1)
        collector.add([_cow(x1=0, y1=300, x2=300, y2=420)], WIDTH, HEIGHT)
        assert collector.summarize(1) is None

    def test_keeps_tracks_apart(self):
        collector = MorphometryCollector(min_samples=1)
        collector.add(
            [_cow(track_id=1), _cow(track_id=2, x1=100, y1=600, x2=400, y2=720)],
            WIDTH,
            HEIGHT,
        )
        assert collector.tracked() == {1, 2}

    def test_take_frees_the_track(self):
        collector = MorphometryCollector(min_samples=1)
        collector.add([_cow()], WIDTH, HEIGHT)
        assert collector.take(1) is not None
        assert collector.tracked() == set()

    def test_forget_drops_samples(self):
        collector = MorphometryCollector(min_samples=1)
        collector.add([_cow()], WIDTH, HEIGHT)
        collector.forget(1)
        assert collector.tracked() == set()


def test_insert_measurement_writes_the_raw_pixels():
    """
    В базу идут пиксели, а не килограммы: формула живёт в базе и может
    поменяться, а перемерить уже прошедшее животное будет нельзя.
    """
    client = MagicMock()
    silhouette = Silhouette(area_px=36000.0, length_px=300.0, width_px=120.0, quality=1.0)

    insert_measurement(client, "farm-1", "cam-1", 7, silhouette, animal_id="a1")

    row = client.table.return_value.insert.call_args[0][0]
    assert row["area_px"] == 36000.0
    assert row["animal_id"] == "a1"
    assert "weight_kg" not in row


def test_insert_measurement_keeps_the_scale_of_the_moment():
    """Камеру могут перевесить — старые измерения должны остаться пересчитываемыми."""
    client = MagicMock()
    silhouette = Silhouette(area_px=1.0, length_px=2.0, width_px=1.0, quality=1.0)

    insert_measurement(client, "farm-1", "cam-1", 7, silhouette, cm_per_pixel=0.42)

    assert client.table.return_value.insert.call_args[0][0]["cm_per_pixel"] == 0.42


def test_weighing_is_on_by_default():
    assert weighing_enabled() is True
