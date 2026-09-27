from unittest.mock import MagicMock, patch

import numpy as np

from cv_service.detector import Detection
from cv_service.preview import (
    TRACK_COLORS,
    color_for_track,
    draw_detections,
    preview_enabled,
    show_frame,
    draw_heads,
)


class TestPreviewEnabled:
    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert preview_enabled() is False

    def test_enabled_by_one(self):
        with patch.dict("os.environ", {"SHOW_PREVIEW": "1"}, clear=True):
            assert preview_enabled() is True

    def test_enabled_by_true(self):
        with patch.dict("os.environ", {"SHOW_PREVIEW": "true"}, clear=True):
            assert preview_enabled() is True

    def test_ignores_other_values(self):
        with patch.dict("os.environ", {"SHOW_PREVIEW": "0"}, clear=True):
            assert preview_enabled() is False


def _frame():
    return np.zeros((240, 320, 3), dtype=np.uint8)


def test_draw_detections_does_not_modify_the_original_frame():
    frame = _frame()
    original = frame.copy()
    draw_detections(
        frame,
        [Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(10, 10, 100, 100))],
    )
    assert np.array_equal(frame, original)


def test_draw_detections_marks_the_frame():
    frame = _frame()
    annotated = draw_detections(
        frame,
        [Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(10, 10, 100, 100))],
    )
    # На пустом чёрном кадре любые ненулевые пиксели — это нарисованное
    assert annotated.sum() > 0


def test_draw_detections_still_shows_the_counter_when_empty():
    annotated = draw_detections(_frame(), [])
    assert annotated.sum() > 0


def test_draw_detections_handles_boxes_touching_the_edge():
    """Подпись над рамкой у верхнего края не должна уходить в отрицательные координаты."""
    annotated = draw_detections(
        _frame(),
        [Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 50, 50))],
    )
    assert annotated.shape == (240, 320, 3)


@patch("cv_service.preview.cv2")
def test_show_frame_continues_without_key(mock_cv2):
    mock_cv2.waitKey.return_value = 255
    mock_cv2.imshow = MagicMock()
    assert show_frame("test", _frame()) is True


@patch("cv_service.preview.cv2")
def test_show_frame_stops_on_q(mock_cv2):
    mock_cv2.waitKey.return_value = ord("q")
    mock_cv2.imshow = MagicMock()
    assert show_frame("test", _frame()) is False


class TestTrackColors:
    def test_same_track_always_gets_the_same_colour(self):
        assert color_for_track(7) == color_for_track(7)

    def test_neighbouring_tracks_differ(self):
        assert color_for_track(1) != color_for_track(2)

    def test_colour_stays_valid_for_large_ids(self):
        assert color_for_track(9999) in TRACK_COLORS

    def test_palette_has_no_duplicates(self):
        assert len(set(TRACK_COLORS)) == len(TRACK_COLORS)


def _mask_square(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def test_draw_detections_fills_the_mask_area():
    frame = _frame()
    annotated = draw_detections(
        frame,
        [
            Detection(
                track_id=1,
                class_name="cow",
                confidence=0.9,
                bbox=(20, 20, 120, 120),
                mask=_mask_square(20, 20, 120, 120),
            )
        ],
    )
    # Внутри контура появился цвет
    assert annotated[70, 70].sum() > 0


def test_draw_detections_paints_two_animals_differently():
    """Ради этого всё и делалось: соседние животные не должны сливаться."""
    frame = _frame()
    annotated = draw_detections(
        frame,
        [
            Detection(1, "cow", 0.9, (10, 10, 90, 90), mask=_mask_square(10, 10, 90, 90)),
            Detection(2, "cow", 0.9, (150, 10, 230, 90), mask=_mask_square(150, 10, 230, 90)),
        ],
    )
    first = tuple(int(v) for v in annotated[50, 50])
    second = tuple(int(v) for v in annotated[50, 190])
    assert first != second


def test_draw_detections_falls_back_to_a_box_without_a_mask():
    annotated = draw_detections(
        _frame(),
        [Detection(1, "cow", 0.9, (20, 20, 120, 120), mask=None)],
    )
    assert annotated.sum() > 0


def test_draw_detections_ignores_a_degenerate_mask():
    annotated = draw_detections(
        _frame(),
        [Detection(1, "cow", 0.9, (20, 20, 120, 120), mask=[(0, 0), (1, 1)])],
    )
    assert annotated.shape == (240, 320, 3)


def test_draw_detections_shows_the_name_when_known():
    """Фермеру нужна «Зорька», а не «#7»."""
    annotated = draw_detections(
        _frame(),
        [Detection(7, "cow", 0.9, (20, 20, 120, 120), mask=_mask_square(20, 20, 120, 120))],
        names={7: "Зорька"},
    )
    assert annotated.sum() > 0


def test_draw_detections_falls_back_to_the_track_number():
    annotated = draw_detections(
        _frame(),
        [Detection(7, "cow", 0.9, (20, 20, 120, 120))],
        names={},
    )
    assert annotated.sum() > 0


def test_draw_detections_ignores_an_empty_name():
    """Пустая кличка — метка «не опознано», показываем номер."""
    a = draw_detections(_frame(), [Detection(7, "cow", 0.9, (20, 20, 120, 120))], names={7: ""})
    b = draw_detections(_frame(), [Detection(7, "cow", 0.9, (20, 20, 120, 120))], names={})
    assert (a == b).all()


def test_draw_detections_works_without_names_argument():
    annotated = draw_detections(_frame(), [Detection(1, "cow", 0.9, (20, 20, 120, 120))])
    assert annotated.shape == (240, 320, 3)


class TestDrawHeads:
    """
    Отметка морды на кадре.

    Нужна ровно для одного: при наведении камеры на кормовой стол
    человек должен своими глазами убедиться, что отметка стоит на морде,
    а не на ухе или на спине соседа. Без этой проверки ошибка в разметке
    зоны обнаружилась бы через две недели по странным отчётам.
    """

    def _frame(self):
        return np.zeros((200, 400, 3), dtype=np.uint8)

    def test_marks_the_muzzle(self):
        frame = self._frame()
        before = frame.copy()
        draw_heads(frame, {7: (0.5, 0.5)})
        assert not np.array_equal(frame, before)

    def test_draws_where_told(self):
        frame = self._frame()
        draw_heads(frame, {7: (0.25, 0.5)})
        # Слева нарисовано, справа чисто
        assert frame[:, :200].any()
        assert not frame[:, 300:].any()

    def test_nothing_to_draw_leaves_the_frame_alone(self):
        frame = self._frame()
        draw_heads(frame, {})
        assert not frame.any()
        draw_heads(frame, None)
        assert not frame.any()

    def test_heads_do_not_replace_the_body(self):
        """
        Голова ДОБАВЛЯЕТСЯ к контуру, а не заменяет его. Контур нужен
        для веса и промеров, отметка морды — чтобы видеть, что засчитано
        кормление, а не стояние рядом.
        """
        detection = Detection(
            track_id=1, class_name="cow", confidence=0.9,
            bbox=(50, 50, 150, 150),
            mask=[(50, 50), (150, 50), (150, 150), (50, 150)],
        )
        with_head = draw_detections(self._frame(), [detection], {}, {1: (0.5, 0.5)})
        without = draw_detections(self._frame(), [detection], {}, None)

        # Контур нарисован в обоих случаях
        assert with_head.any() and without.any()
        # А отметка — только в первом
        assert not np.array_equal(with_head, without)

    def test_the_counter_shows_how_many_are_feeding(self):
        detection = Detection(
            track_id=1, class_name="cow", confidence=0.9, bbox=(50, 50, 150, 150)
        )
        plain = draw_detections(self._frame(), [detection], {}, None)
        feeding = draw_detections(self._frame(), [detection], {}, {1: (0.5, 0.5)})
        assert not np.array_equal(plain[:40], feeding[:40])
