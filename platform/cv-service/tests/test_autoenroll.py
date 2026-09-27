"""
Автоматическое запоминание особей.

Система видит незнакомое животное, заводит «№ 12» и со следующего раза
узнаёт его сама. Работает без человека — он только переименовывает.

Опасность здесь одна и большая: неизбежные двойники. Ошибка узнавания
живёт секунду, ошибка заведения — вечно: в базе навсегда остаётся лишняя
запись с плохим эталоном, под который потом подходит не то животное.
Поэтому больше половины тестов про отказ заводить.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

from cv_service.autoenroll import (
    AutoEnroller,
    AutoEnrollRules,
    autoenroll_enabled,
    crop_is_good_enough,
    describe_rules,
    register_animal,
    remember_view,
)


@dataclass
class FakeCrop:
    track_id: int = 1
    confidence: float = 0.9
    area: float = 100_000.0


class TestCropQuality:
    def test_a_good_crop_passes(self):
        assert crop_is_good_enough(FakeCrop(), AutoEnrollRules()) is None

    def test_an_unsure_detection_is_refused(self):
        reason = crop_is_good_enough(FakeCrop(confidence=0.4), AutoEnrollRules())
        assert reason is not None and "уверенность" in reason

    def test_a_distant_animal_is_refused(self):
        """
        Мелкая рамка — это животное далеко или обрезано краем кадра.
        Эталон по такому кадру подойдёт потом к кому угодно.
        """
        reason = crop_is_good_enough(FakeCrop(area=900.0), AutoEnrollRules())
        assert reason is not None and "мелк" in reason

    def test_the_reason_is_returned_not_just_a_no(self):
        # Иначе «система никого не заводит» в журнале выглядит поломкой
        reason = crop_is_good_enough(FakeCrop(confidence=0.1), AutoEnrollRules())
        assert isinstance(reason, str) and len(reason) > 10


class TestAutoEnroller:
    def test_the_first_meeting_only_waits(self):
        """
        Одиночный кадр слишком часто оказывается тенью, обрезанным боком
        или двумя животными, слипшимися в одну рамку.
        """
        enroller = AutoEnroller()
        allowed, why = enroller.consider(FakeCrop())

        assert allowed is False
        assert "жду подтверждения" in why

    def test_the_second_meeting_creates(self):
        enroller = AutoEnroller()
        enroller.consider(FakeCrop(track_id=5))
        allowed, _ = enroller.consider(FakeCrop(track_id=5))

        assert allowed is True
        assert enroller.created == 1

    def test_different_tracks_are_counted_apart(self):
        """Иначе два разных животных вместе набрали бы подтверждение."""
        enroller = AutoEnroller()
        enroller.consider(FakeCrop(track_id=1))
        allowed, _ = enroller.consider(FakeCrop(track_id=2))

        assert allowed is False

    def test_a_bad_crop_never_counts_toward_confirmation(self):
        """
        Иначе животное, дважды снятое плохо, всё равно завелось бы —
        и завелось бы с негодным эталоном.
        """
        enroller = AutoEnroller()
        enroller.consider(FakeCrop(track_id=3, confidence=0.2))
        allowed, _ = enroller.consider(FakeCrop(track_id=3, confidence=0.2))

        assert allowed is False
        assert enroller.created == 0

    def test_forgetting_a_track_resets_the_count(self):
        enroller = AutoEnroller()
        enroller.consider(FakeCrop(track_id=7))
        enroller.forget(7)
        allowed, _ = enroller.consider(FakeCrop(track_id=7))

        assert allowed is False

    def test_stricter_rules_can_be_demanded(self):
        strict = AutoEnrollRules(min_sightings=3)
        enroller = AutoEnroller(strict)

        results = [enroller.consider(FakeCrop(track_id=1))[0] for _ in range(3)]
        assert results == [False, False, True]


class TestRulesFromEnv:
    def test_defaults_are_sane(self, monkeypatch):
        for name in (
            "AUTO_ENROLL_MIN_CONFIDENCE",
            "AUTO_ENROLL_MIN_AREA",
            "AUTO_ENROLL_MIN_SIGHTINGS",
        ):
            monkeypatch.delenv(name, raising=False)

        rules = AutoEnrollRules.from_env()
        assert 0 < rules.min_confidence <= 1
        assert rules.min_sightings >= 1

    def test_nonsense_does_not_crash(self, monkeypatch):
        monkeypatch.setenv("AUTO_ENROLL_MIN_CONFIDENCE", "почти всегда")
        assert AutoEnrollRules.from_env().min_confidence > 0

    def test_enabled_by_default(self, monkeypatch):
        """
        Иначе система не узнаёт никого, пока человек не заведёт всех
        руками, — а это ровно то, от чего уходим.
        """
        monkeypatch.delenv("AUTO_ENROLL", raising=False)
        assert autoenroll_enabled() is True

    def test_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv("AUTO_ENROLL", "0")
        assert autoenroll_enabled() is False


class TestDatabaseCalls:
    def test_registering_passes_the_vector(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = MagicMock(
            data={"id": "a1", "label": "№ 1"}
        )

        created = register_animal(client, "farm-1", [0.1] * 4)

        assert created["label"] == "№ 1"
        args = client.rpc.call_args[0][1]
        assert args["target_farm_id"] == "farm-1"

    def test_registering_understands_a_list_response(self):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": "a1", "label": "№ 1"}]
        )
        assert register_animal(client, "farm-1", [0.1])["id"] == "a1"

    def test_remembering_a_view_targets_the_animal(self):
        client = MagicMock()
        remember_view(client, "a1", [0.2])

        assert client.rpc.call_args[0][0] == "add_auto_embedding"
        assert client.rpc.call_args[0][1]["target_animal_id"] == "a1"


class TestDescribeRules:
    def test_reads_plainly_for_the_log(self):
        line = describe_rules(AutoEnrollRules())
        assert "уверенность" in line and "подтверждений" in line
