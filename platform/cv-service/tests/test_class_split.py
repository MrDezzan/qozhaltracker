"""
Разделение находок на скот и охрану.

Самое опасное место всего модуля охраны. Стоит человеку просочиться в
общий поток — и он войдёт в поголовье, его стояние у кормушки запишется
как кормление, его силуэт уйдёт в обучающую выборку для веса, а его лицо
попадёт в базу векторов признаков животных.

Ошибка при этом ТИХАЯ: логи идут, кадры уходят, система выглядит рабочей,
а цифры врут. Поэтому здесь по тесту на каждого потребителя поимённо.
"""


import pytest

from cv_service import detector
from cv_service.detector import (
    LIVESTOCK,
    LIVESTOCK_CLASS_NAMES,
    SECURITY,
    SECURITY_CLASS_NAMES,
    Detection,
    class_group,
    security_enabled,
    split_by_group,
)
from cv_service.headcount import HeadcountAggregator
from cv_service.morphometry import MorphometryCollector
from cv_service.zones import Zone, ZoneTracker


def cow(track_id=1, bbox=(100, 100, 200, 200)) -> Detection:
    return Detection(track_id=track_id, class_name="cow", confidence=0.9, bbox=bbox)


def person(track_id=2, bbox=(100, 100, 200, 200)) -> Detection:
    return Detection(track_id=track_id, class_name="person", confidence=0.9, bbox=bbox)


class TestGrouping:
    def test_livestock_and_security_do_not_overlap(self):
        """
        Пересечение означало бы, что один и тот же класс попадает и в
        поголовье, и в охрану. Проверяем это отдельно: списки правятся
        руками, и однажды кто-то допишет туда лишнее.
        """
        assert LIVESTOCK_CLASS_NAMES & SECURITY_CLASS_NAMES == frozenset()

    def test_a_person_is_security(self):
        assert class_group("person") == SECURITY

    def test_a_vehicle_is_security(self):
        assert class_group("car") == SECURITY
        assert class_group("truck") == SECURITY

    def test_a_cow_is_livestock(self):
        assert class_group("cow") == LIVESTOCK

    def test_an_unknown_class_counts_as_livestock(self):
        """
        Умышленно. Наборы скота настраиваются под ферму — на верблюжьей
        появится свой класс. Отнести незнакомое к охране означало бы
        поднимать тревогу на верблюда.
        """
        assert class_group("camel") == LIVESTOCK

    def test_the_group_is_derived_not_stored(self):
        assert cow().group == LIVESTOCK
        assert person().group == SECURITY

    def test_splits_into_two_lists(self):
        livestock, security = split_by_group([cow(1), person(2), cow(3)])
        assert [d.track_id for d in livestock] == [1, 3]
        assert [d.track_id for d in security] == [2]

    def test_nothing_is_lost_or_duplicated(self):
        found = [cow(1), person(2), cow(3), person(4)]
        livestock, security = split_by_group(found)
        assert len(livestock) + len(security) == len(found)


class TestSecurityOff:
    def test_disabled_by_default(self, monkeypatch):
        """
        Не из осторожности к коду, а по закону: снимать людей нельзя, пока
        на ферме не оформлены приказ, ознакомление под роспись и таблички.
        """
        monkeypatch.delenv("SECURITY_ENABLED", raising=False)
        assert security_enabled() is False

    def test_enabled_explicitly(self, monkeypatch):
        monkeypatch.setenv("SECURITY_ENABLED", "1")
        assert security_enabled() is True


class TestConsumersNeverSeePeople:
    """
    По тесту на каждого потребителя из цикла обработки. Список здесь
    должен совпадать со списком в `process_camera`; если там появится
    новый потребитель, ему место и тут.
    """

    def test_headcount_does_not_count_people(self):
        """Иначе скотник на утренней раздаче добавляется к поголовью."""
        aggregator = HeadcountAggregator(interval_s=1.0)
        livestock, _ = split_by_group([cow(1), person(2), person(3)])

        aggregator.add(livestock, now=0.0)
        summary = aggregator.take()

        assert summary["unique_count"] == 1
        assert "person" not in summary["by_class"]

    def test_zones_do_not_record_people_as_feeding(self):
        """Иначе стояние скотника у кормушки запишется как кормление."""
        feeder = Zone(
            id="z1",
            name="Кормушка",
            kind="feeder",
            polygon=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        tracker = ZoneTracker(zones=[feeder])
        livestock, _ = split_by_group([cow(1), person(2)])

        active, _ = tracker.update(livestock, 1000, 1000, now=0.0)
        assert len(active) == 1

    def test_body_measurement_ignores_people(self):
        """
        Иначе человеческий силуэт попадёт в подгонку формулы веса, и
        оценка съедет для всего стада разом.
        """
        collector = MorphometryCollector()
        livestock, _ = split_by_group([
            cow(1, bbox=(100, 100, 300, 200)),
            person(2, bbox=(100, 100, 140, 300)),
        ])

        for detection in livestock:
            collector.add([detection], 1000, 1000)

        assert 2 not in collector.tracked()

    def test_the_security_list_carries_only_people_and_vehicles(self):
        _, security = split_by_group([cow(1), person(2), cow(3)])
        assert all(d.class_name in SECURITY_CLASS_NAMES for d in security)


class TestEmptyInput:
    def test_no_detections_gives_two_empty_lists(self):
        livestock, security = split_by_group([])
        assert livestock == []
        assert security == []

    def test_only_people_leaves_livestock_empty(self):
        livestock, security = split_by_group([person(1), person(2)])
        assert livestock == []
        assert len(security) == 2


@pytest.fixture
def profile_restored():
    """
    Профиль модуля глобален, и тест, который его меняет, обязан вернуть
    всё назад. Без этого следующий тест в том же запуске получает чужие
    настройки — и падает не там, где ошибка.

    Этот приём стоит первым в списке аргументов теста не для красоты:
    фикстуры разбираются в обратном порядке, и стой он после monkeypatch,
    профиль перечитывался бы с ЕЩЁ НЕ ВОССТАНОВЛЕННЫМ окружением — то
    есть ровно с тем, от чего мы пытаемся избавиться.
    """
    yield
    detector.reload_profile()


class TestCountPeopleWinsOverTrackedClasses:
    """
    COUNT_PEOPLE добавляет человека к любому списку классов.

    Ловушка, на которую напоролись вживую: в `.env` явно перечислен скот
    (`TRACKED_CLASSES=cow,sheep,horse`), человек в этот список не входит,
    а из охраны он в этом режиме уже убран. Итог — включённый режим людей
    не находит вообще никого, и молча.
    """

    def test_yavnyy_spisok_ne_teryaet_cheloveka(self, profile_restored, monkeypatch):
        monkeypatch.setenv("TRACKED_CLASSES", "cow,sheep,horse")
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        detector.reload_profile()

        tracked = detector.get_tracked_class_names()
        assert "person" in tracked
        assert "cow" in tracked

    def test_bez_rezhima_chelovek_v_spisok_ne_popadaet(self, profile_restored, monkeypatch):
        monkeypatch.setenv("TRACKED_CLASSES", "cow,sheep,horse")
        monkeypatch.delenv("COUNT_PEOPLE", raising=False)
        detector.reload_profile()

        assert "person" not in detector.get_tracked_class_names()

    def test_pustoy_spisok_beryot_profil(self, profile_restored, monkeypatch):
        monkeypatch.delenv("TRACKED_CLASSES", raising=False)
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        detector.reload_profile()

        assert "person" in detector.get_tracked_class_names()
