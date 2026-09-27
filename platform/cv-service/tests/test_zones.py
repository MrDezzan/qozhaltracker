import pytest

from cv_service.detector import Detection
from cv_service.zones import (
    FEEDER_GRACE_SECONDS,
    LOST_GRACE_SECONDS,
    Zone,
    grace_for,
    head_in_zone,
    in_zone,
    describe_zone_change,
    ZoneTracker,
    anchor_point,
    parse_zones,
    point_in_polygon,
)

SQUARE = ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8))
FEEDER = Zone(id="z1", name="Кормушка", kind="feeder", polygon=SQUARE)
# У кормушки пауза длинная — поднятая голова не должна рвать кормёжку.
# Там, где проверяется именно короткая пауза, берём зону прохода
GATE = Zone(id="z2", name="Проход", kind="gate", polygon=SQUARE)


class TestPointInPolygon:
    def test_point_inside(self):
        assert point_in_polygon((0.5, 0.5), SQUARE) is True

    def test_point_outside(self):
        assert point_in_polygon((0.1, 0.1), SQUARE) is False

    def test_point_far_right(self):
        assert point_in_polygon((0.95, 0.5), SQUARE) is False

    def test_degenerate_polygon_never_contains_anything(self):
        assert point_in_polygon((0.5, 0.5), ((0.0, 0.0), (1.0, 1.0))) is False

    def test_concave_polygon(self):
        # П-образная зона: середина выреза снаружи
        shape = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.6, 1.0),
                 (0.6, 0.4), (0.4, 0.4), (0.4, 1.0), (0.0, 1.0))
        assert point_in_polygon((0.5, 0.8), shape) is False
        assert point_in_polygon((0.2, 0.8), shape) is True


class TestAnchorPoint:
    def test_uses_bottom_centre_of_the_box(self):
        """Точка привязки — где животное стоит, а не центр рамки."""
        detection = Detection(
            track_id=1, class_name="cow", confidence=0.9, bbox=(100, 100, 300, 400)
        )
        x, y = anchor_point(detection, 1000, 800)
        assert x == pytest.approx(0.2)
        assert y == pytest.approx(0.5)


def _detection(track_id: int, x: float, y: float) -> Detection:
    """Рамка, нижняя середина которой попадает в точку (x, y) кадра 100x100."""
    return Detection(
        track_id=track_id,
        class_name="cow",
        confidence=0.9,
        bbox=(x * 100 - 5, y * 100 - 20, x * 100 + 5, y * 100),
    )


class TestZoneTracker:
    def test_opens_a_visit_when_the_animal_enters(self):
        tracker = ZoneTracker(zones=[FEEDER])
        started, finished = tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        assert len(started) == 1
        assert started[0].zone.name == "Кормушка"
        assert finished == []

    def test_does_not_reopen_an_ongoing_visit(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        started, _ = tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=5.0)
        assert started == []

    def test_ignores_animals_outside_the_zone(self):
        tracker = ZoneTracker(zones=[FEEDER])
        started, _ = tracker.update([_detection(1, 0.05, 0.05)], 100, 100, now=0.0)
        assert started == []

    def test_closes_the_visit_after_the_grace_period(self):
        tracker = ZoneTracker(zones=[GATE])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=30.0)
        _, finished = tracker.update([], 100, 100, now=45.0)
        assert len(finished) == 1
        assert finished[0].duration_s == pytest.approx(30.0)

    def test_keeps_the_visit_open_during_a_brief_loss(self):
        """Трекер теряет объект на кадр-другой — визит не должен рваться."""
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        _, finished = tracker.update([], 100, 100, now=3.0)
        assert finished == []

    def test_drops_visits_shorter_than_the_threshold(self):
        """Просто прошло мимо — не считается кормлением."""
        tracker = ZoneTracker(zones=[FEEDER], min_visit_seconds=5.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=2.0)
        _, finished = tracker.update([], 100, 100, now=20.0)
        assert finished == []

    def test_tracks_several_animals_independently(self):
        tracker = ZoneTracker(zones=[FEEDER])
        started, _ = tracker.update(
            [_detection(1, 0.4, 0.5), _detection(2, 0.6, 0.5)], 100, 100, now=0.0
        )
        assert len(started) == 2

    def test_tracks_several_zones_independently(self):
        water = Zone(
            id="z2",
            name="Поилка",
            kind="water",
            polygon=((0.0, 0.0), (0.15, 0.0), (0.15, 0.15), (0.0, 0.15)),
        )
        tracker = ZoneTracker(zones=[FEEDER, water])
        started, _ = tracker.update(
            [_detection(1, 0.5, 0.5), _detection(2, 0.07, 0.07)], 100, 100, now=0.0
        )
        assert {v.zone.name for v in started} == {"Кормушка", "Поилка"}

    def test_flush_closes_long_enough_visits(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=40.0)
        finished = tracker.flush(now=40.0)
        assert len(finished) == 1
        assert finished[0].duration_s == pytest.approx(40.0)

    def test_flush_drops_short_visits(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        assert tracker.flush(now=1.0) == []

    def test_flush_empties_the_state(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.flush(now=40.0)
        assert tracker.flush(now=80.0) == []


class TestParseZones:
    def test_builds_zones_from_rows(self):
        zones = parse_zones(
            [{"id": "z1", "name": "Кормушка", "kind": "feeder", "polygon": [[0, 0], [1, 0], [1, 1]]}]
        )
        assert len(zones) == 1
        assert zones[0].kind == "feeder"

    def test_skips_polygons_with_too_few_points(self):
        assert parse_zones([{"id": "z1", "polygon": [[0, 0], [1, 1]]}]) == []

    def test_skips_malformed_polygons(self):
        assert parse_zones([{"id": "z1", "polygon": [["a", "b"], [1, 1], [2, 2]]}]) == []

    def test_skips_missing_polygon(self):
        assert parse_zones([{"id": "z1", "name": "Без зоны"}]) == []

    def test_defaults_the_kind(self):
        zones = parse_zones([{"id": "z1", "polygon": [[0, 0], [1, 0], [1, 1]]}])
        assert zones[0].kind == "other"


class TestZoneReload:
    def test_picks_up_a_new_zone_without_restart(self):
        tracker = ZoneTracker(zones=[])
        assert tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0) == ([], [])

        tracker.set_zones([FEEDER])
        started, _ = tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=1.0)
        assert len(started) == 1

    def test_keeps_an_open_visit_when_the_zone_survives_a_reload(self):
        tracker = ZoneTracker(zones=[GATE])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)

        same_zone_again = Zone(id="z2", name="Проход", kind="gate", polygon=SQUARE)
        assert tracker.set_zones([same_zone_again]) == []

        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=30.0)
        _, finished = tracker.update([], 100, 100, now=45.0)
        assert len(finished) == 1
        assert finished[0].duration_s == pytest.approx(30.0)

    def test_closes_visits_of_a_deleted_zone(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=40.0)

        closed = tracker.set_zones([])
        assert len(closed) == 1
        assert closed[0].duration_s == pytest.approx(40.0)

    def test_drops_short_visits_of_a_deleted_zone(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        assert tracker.set_zones([]) == []


class TestDescribeZoneChange:
    def test_nothing_changed(self):
        assert describe_zone_change([FEEDER], [FEEDER]) is None

    def test_names_the_added_zone(self):
        change = describe_zone_change([], [FEEDER])
        assert change is not None
        assert "Кормушка" in change
        assert "добавлены" in change

    def test_names_the_removed_zone(self):
        change = describe_zone_change([FEEDER], [])
        assert change is not None
        assert "удалены" in change
        assert "Кормушка" in change

    def test_reports_both_at_once(self):
        water = Zone(id="z2", name="Поилка", kind="water", polygon=SQUARE)
        change = describe_zone_change([FEEDER], [water])
        assert "добавлены" in change and "Поилка" in change
        assert "удалены" in change and "Кормушка" in change

    def test_ignores_a_renamed_zone_with_the_same_id(self):
        renamed = Zone(id="z1", name="Кормушка слева", kind="feeder", polygon=SQUARE)
        assert describe_zone_change([FEEDER], [renamed]) is None


class TestBrokenFrame:
    def test_zero_sized_frame_does_not_crash(self):
        """Битый кадр не должен ронять обработку."""
        detection = Detection(track_id=1, class_name="cow", confidence=0.9, bbox=(0, 0, 10, 10))
        assert anchor_point(detection, 0, 0) == (-1.0, -1.0)

    def test_point_from_broken_frame_hits_no_zone(self):
        assert point_in_polygon((-1.0, -1.0), SQUARE) is False

    def test_tracker_survives_a_broken_frame(self):
        tracker = ZoneTracker(zones=[FEEDER])
        started, finished = tracker.update(
            [Detection(1, "cow", 0.9, (0, 0, 10, 10))], 0, 0, now=0.0
        )
        assert started == [] and finished == []


class TestFeederGrace:
    """
    Пауза у кормушки.

    Разбор чужого рабочего решения (видео от 21.08.2026) показал, чем
    держится подсчёт времени у корма: камера смотрит сбоку через
    кормовой стол, и в кадре видна ровно голова. Пока голова опущена в
    корм — животное ест; подняло голову жевать — вышло из зоны.

    Животное поднимает голову постоянно: взяло корм, жуёт двадцать-
    тридцать секунд, опустило снова. С общей паузой в десять секунд
    получасовая кормёжка распалась бы на полсотни кусков, каждый короче
    MIN_VISIT_SECONDS, и почти всё отбросилось бы. Животное, евшее
    полчаса, выглядело бы как не евшее вовсе — а health.py объявил бы
    ему тревогу «мало корма».
    """

    def test_a_lifted_head_does_not_end_the_meal(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)

        # Голова поднята полминуты — жуёт
        _, finished = tracker.update([], 100, 100, now=30.0)
        assert finished == []

        # И снова опустилась: это та же кормёжка, а не вторая
        started, _ = tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=35.0)
        assert started == []

    def test_the_meal_is_counted_whole(self):
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        for moment in (30.0, 70.0, 110.0):
            tracker.update([], 100, 100, now=moment - 20.0)
            tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=moment)

        _, finished = tracker.update([], 100, 100, now=200.0)
        assert len(finished) == 1
        # Время считается по последнему появлению в зоне, а не по паузе:
        # засчитывать животному время, пока его в кормушке не было, нельзя
        assert finished[0].duration_s == pytest.approx(110.0)

    def test_a_real_break_still_ends_the_meal(self):
        """Пауза длиннее минуты — это уже другой подход к кормушке."""
        tracker = ZoneTracker(zones=[FEEDER])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=20.0)

        _, finished = tracker.update([], 100, 100, now=90.0)
        assert len(finished) == 1
        assert finished[0].duration_s == pytest.approx(20.0)

    def test_the_gate_keeps_the_short_pause(self):
        """
        На проходе склеивать нельзя: животное прошло, вернулось через
        полминуты — это два прохода, а не один длинный.
        """
        tracker = ZoneTracker(zones=[GATE])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=10.0)

        _, finished = tracker.update([], 100, 100, now=25.0)
        assert len(finished) == 1

    def test_water_behaves_like_the_feeder(self):
        """
        Визит должен быть достаточно длинным, чтобы его вообще
        отчитали. С коротким визитом проверка проходила бы и при
        короткой паузе: визит закрывался бы, но отбрасывался как
        слишком короткий, и `finished` всё равно оказывался пустым.
        Мутант на это и выжил.
        """
        tracker = ZoneTracker(zones=[
            Zone(id="z3", name="Поилка", kind="water", polygon=SQUARE)
        ])
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=0.0)
        tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=20.0)

        _, finished = tracker.update([], 100, 100, now=50.0)
        assert finished == []

        started, _ = tracker.update([_detection(1, 0.5, 0.5)], 100, 100, now=55.0)
        assert started == []

    def test_an_unknown_kind_falls_back_to_the_short_pause(self):
        assert grace_for("other") == LOST_GRACE_SECONDS
        assert grace_for("феншуй") == LOST_GRACE_SECONDS

    def test_the_feeder_pause_is_longer_than_the_default(self):
        # Если однажды кто-то уравняет их, кормёжка снова начнёт рваться
        assert grace_for("feeder") > LOST_GRACE_SECONDS


# ---------------------------------------------------------------------------
# Голова отдельно от туловища
# ---------------------------------------------------------------------------
# Класса «голова» у модели нет: в COCO есть корова целиком. Но модель
# сегментационная и даёт КОНТУР, а зона кормушки нарисована узкой полосой
# за решёткой — дотянуться туда можно только головой.

# Кормовой стол: узкая полоса в правой части кадра
BUNK = Zone(
    id="z9", name="Кормовой стол", kind="feeder",
    polygon=((0.70, 0.0), (1.0, 0.0), (1.0, 1.0), (0.70, 1.0)),
)
BUNK_GATE = Zone(
    id="z10", name="Та же полоса, но проход", kind="gate",
    polygon=((0.70, 0.0), (1.0, 0.0), (1.0, 1.0), (0.70, 1.0)),
)


def _cow(track_id: int, body_x: float, mask=None) -> Detection:
    """
    Животное с туловищем около `body_x` и произвольным контуром.
    Кадр везде 100x100, контур задаётся в пикселях, как отдаёт модель.
    """
    return Detection(
        track_id=track_id,
        class_name="cow",
        confidence=0.9,
        bbox=(body_x * 100 - 20, 40.0, body_x * 100 + 20, 80.0),
        mask=mask,
    )


class TestHeadInZone:
    def test_a_stretched_neck_reaches_the_bunk(self):
        """Туловище в стороне, шея вытянута к корму — животное ест."""
        cow = _cow(1, 0.45, mask=[(25, 40), (65, 45), (78, 55), (65, 75), (25, 80)])
        inside, head = in_zone(cow, BUNK, 100, 100)
        assert inside is True
        assert head is not None
        assert head[0] > 0.70

    def test_standing_next_to_the_bunk_is_not_eating(self):
        """
        Самая важная проверка во всём файле.

        Животное стоит вплотную к столу, но голову не опустило: контур
        до полосы не достаёт. Раньше решала точка под ногами, и такое
        животное засчитывалось как евшее — «время у корма» превращалось
        в «время рядом с кормушкой».
        """
        cow = _cow(1, 0.55, mask=[(35, 40), (69, 45), (69, 75), (35, 80)])
        inside, head = in_zone(cow, BUNK, 100, 100)
        assert inside is False
        assert head is None

    def test_the_foot_fallback_does_not_fire_when_there_is_a_contour(self):
        """
        Контур есть и в зону не попал — ответ «нет» окончательный.

        Проверять заодно и точку под ногами выглядит безобидной
        подстраховкой, а на деле возвращает ровно ту ошибку, ради
        которой всё делалось.
        """
        # Нижняя середина рамки заведомо ВНУТРИ полосы
        cow = Detection(
            track_id=1, class_name="cow", confidence=0.9,
            bbox=(75.0, 40.0, 85.0, 80.0),
            # А контур целиком снаружи
            mask=[(10, 40), (60, 45), (60, 75), (10, 80)],
        )
        assert point_in_polygon(anchor_point(cow, 100, 100), BUNK.polygon) is True
        inside, _ = in_zone(cow, BUNK, 100, 100)
        assert inside is False

    def test_without_a_contour_the_old_behaviour_stays(self):
        """
        Обычная модель без сегментации контура не даёт. Ронять на этом
        кормушку нельзя: при камере сбоку через стол низ рамки и так
        приходится на морду.
        """
        cow = Detection(
            track_id=1, class_name="cow", confidence=0.9,
            bbox=(75.0, 40.0, 85.0, 80.0), mask=None,
        )
        inside, head = in_zone(cow, BUNK, 100, 100)
        assert inside is True
        assert head is None

    def test_a_degenerate_contour_counts_as_no_contour(self):
        """
        Контур из двух точек — не контур: многоугольника из них не
        выходит. Такой обрывок нельзя принимать за морду.

        Туловище стоит в стороне (низ рамки вне полосы), а обрывок
        контура попал внутрь. Правильный ответ — «не ест»: обрывку веры
        нет, а запасной путь по ногам говорит «снаружи».

        Прошлая редакция теста ставила туловище прямо у полосы, и ответ
        выходил «да» при обеих ветках — мутант на это и выжил.
        """
        cow = _cow(1, 0.45, mask=[(75, 40), (85, 45)])
        assert point_in_polygon(anchor_point(cow, 100, 100), BUNK.polygon) is False

        inside, head = in_zone(cow, BUNK, 100, 100)
        assert inside is False
        assert head is None

    def test_a_degenerate_contour_still_allows_the_foot_fallback(self):
        """Обрывок контура не должен и мешать: если ноги в зоне — засчитываем."""
        cow = Detection(
            track_id=1, class_name="cow", confidence=0.9,
            bbox=(75.0, 40.0, 85.0, 80.0), mask=[(10, 10), (20, 20)],
        )
        inside, _ = in_zone(cow, BUNK, 100, 100)
        assert inside is True

    def test_the_muzzle_is_the_farthest_point_not_just_any(self):
        """
        Из точек контура, попавших в зону, берётся самая дальняя от
        середины рамки. Ухо и загривок тоже могут задеть полосу, а
        отметка должна стоять на кончике морды.
        """
        cow = _cow(1, 0.45, mask=[(25, 40), (72, 42), (95, 58), (72, 78), (25, 80)])
        _, head = in_zone(cow, BUNK, 100, 100)
        assert head == pytest.approx((0.95, 0.58))

    def test_a_passage_zone_still_goes_by_the_feet(self):
        """
        Голова решает только у кормушки и поилки. На проходе животное
        именно ПРОХОДИТ, и считать надо, где оно идёт, а не куда
        дотянулось мордой.
        """
        cow = _cow(1, 0.45, mask=[(25, 40), (65, 45), (78, 55), (65, 75), (25, 80)])
        inside, head = in_zone(cow, BUNK_GATE, 100, 100)
        assert inside is False
        assert head is None

    def test_a_broken_frame_size_does_not_crash(self):
        cow = _cow(1, 0.45, mask=[(25, 40), (78, 55), (25, 80)])
        assert head_in_zone(cow, BUNK, 0, 0) is None

    def test_the_visit_carries_the_muzzle(self):
        """Отметка нужна на кадре: при наведении камеры на ферме надо
        своими глазами увидеть, что она стоит на морде."""
        tracker = ZoneTracker(zones=[BUNK])
        cow = _cow(1, 0.45, mask=[(25, 40), (65, 45), (78, 55), (65, 75), (25, 80)])
        started, _ = tracker.update([cow], 100, 100, now=0.0)
        assert started[0].head_point is not None
        assert started[0].head_point[0] > 0.70

    def test_the_muzzle_follows_the_animal(self):
        tracker = ZoneTracker(zones=[BUNK])
        near = _cow(1, 0.45, mask=[(25, 40), (65, 45), (75, 55), (65, 75), (25, 80)])
        far = _cow(1, 0.45, mask=[(25, 40), (65, 45), (95, 55), (65, 75), (25, 80)])
        tracker.update([near], 100, 100, now=0.0)
        started, _ = tracker.update([far], 100, 100, now=1.0)
        assert started == []
        visit = next(iter(tracker._open.values()))
        assert visit.head_point == pytest.approx((0.95, 0.55))

    def test_the_body_is_still_detected_as_before(self):
        """
        Туловище никуда не делось: голова добавилась, а не заменила.
        Рамка — это то, из чего считается вес и промеры.
        """
        cow = _cow(1, 0.45, mask=[(25, 40), (78, 55), (25, 80)])
        assert cow.bbox == (25.0, 40.0, 65.0, 80.0)
        assert cow.class_name == "cow"
