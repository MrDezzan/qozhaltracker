from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.training import (
    COUNT_JUMP_MIN,
    DEFAULT_DAILY_CAP,
    DEFAULT_INTERVAL_S,
    ROUTINE_EVERY,
    TRAINING_BUCKET,
    collect_until,
    collecting,
    count_jumped,
    daily_cap,
    describe,
    encode_training_frame,
    has_doubt,
    interval_s,
    is_crowded,
    pick_reason,
    training_path,
    upload_training_frame,
)


def det(confidence=0.9, bbox=(0, 0, 100, 100), class_name="cow"):
    return SimpleNamespace(confidence=confidence, bbox=bbox, class_name=class_name)


# ---------------------------------------------------------------------------
# Самоотключение
# ---------------------------------------------------------------------------
# Главная защита от забытого включённым сбора. За месяц одна камера при
# кадре в тридцать секунд даёт под сто тысяч файлов.


class TestSelfShutdown:
    def test_off_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            assert collecting(date(2026, 8, 21)) is False

    def test_on_before_the_date(self):
        with patch.dict("os.environ", {"TRAINING_COLLECT_UNTIL": "2026-09-05"}):
            assert collecting(date(2026, 8, 21)) is True

    def test_on_during_the_last_day(self):
        """Дата включительно: сбор до 5 сентября значит, что 5-е ещё собираем."""
        with patch.dict("os.environ", {"TRAINING_COLLECT_UNTIL": "2026-09-05"}):
            assert collecting(date(2026, 9, 5)) is True

    def test_off_the_day_after(self):
        with patch.dict("os.environ", {"TRAINING_COLLECT_UNTIL": "2026-09-05"}):
            assert collecting(date(2026, 9, 6)) is False

    def test_garbage_date_means_off_not_forever(self):
        """
        Опечатка в дате обязана выключить сбор, а не включить навсегда.

        Обратное поведение обнаружилось бы через месяц по счёту за
        хранилище — худший способ узнать об ошибке в настройке.
        """
        for garbage in ("завтра", "05.09.2026", "2026-13-45", "1"):
            with patch.dict("os.environ", {"TRAINING_COLLECT_UNTIL": garbage}):
                assert collect_until() is None, garbage
                assert collecting(date(2026, 8, 21)) is False, garbage


class TestDailyCap:
    def test_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert daily_cap() == DEFAULT_DAILY_CAP

    def test_override(self):
        with patch.dict("os.environ", {"TRAINING_DAILY_CAP": "50"}):
            assert daily_cap() == 50

    def test_zero_falls_back_instead_of_disabling(self):
        """
        Ноль здесь — почти наверняка опечатка, а не «не собирать».
        Выключают сбор датой, и молча уронить его до нуля значит две
        недели ждать кадров, которых не будет.
        """
        with patch.dict("os.environ", {"TRAINING_DAILY_CAP": "0"}):
            assert daily_cap() == DEFAULT_DAILY_CAP

    def test_garbage_falls_back(self):
        with patch.dict("os.environ", {"TRAINING_DAILY_CAP": "много"}):
            assert daily_cap() == DEFAULT_DAILY_CAP


class TestInterval:
    def test_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert interval_s() == DEFAULT_INTERVAL_S

    def test_override(self):
        with patch.dict("os.environ", {"TRAINING_INTERVAL_S": "10"}):
            assert interval_s() == 10.0

    def test_garbage_falls_back(self):
        with patch.dict("os.environ", {"TRAINING_INTERVAL_S": "часто"}):
            assert interval_s() == DEFAULT_INTERVAL_S


# ---------------------------------------------------------------------------
# Сомнение модели
# ---------------------------------------------------------------------------


class TestDoubt:
    def test_confident_detection_is_not_doubt(self):
        assert has_doubt([det(confidence=0.95)]) is False

    def test_middle_confidence_is_doubt(self):
        assert has_doubt([det(confidence=0.45)]) is True

    def test_very_low_is_not_doubt(self):
        """Ниже полосы модель уверена, что это НЕ животное. Такие
        обнаружения до нас обычно и не доходят."""
        assert has_doubt([det(confidence=0.1)]) is False

    def test_lower_edge_counts(self):
        assert has_doubt([det(confidence=0.30)]) is True

    def test_upper_edge_counts(self):
        assert has_doubt([det(confidence=0.60)]) is True

    def test_just_above_the_band_does_not(self):
        assert has_doubt([det(confidence=0.61)]) is False

    def test_one_doubtful_among_confident_is_enough(self):
        assert has_doubt([det(confidence=0.99), det(confidence=0.4)]) is True


# ---------------------------------------------------------------------------
# Теснота
# ---------------------------------------------------------------------------


class TestCrowding:
    def test_apart_is_not_crowded(self):
        assert is_crowded([
            det(bbox=(0, 0, 100, 100)),
            det(bbox=(500, 500, 600, 600)),
        ]) is False

    def test_touching_corners_is_not_crowded(self):
        assert is_crowded([
            det(bbox=(0, 0, 100, 100)),
            det(bbox=(100, 100, 200, 200)),
        ]) is False

    def test_heavy_overlap_is_crowded(self):
        assert is_crowded([
            det(bbox=(0, 0, 100, 100)),
            det(bbox=(20, 20, 120, 120)),
        ]) is True

    def test_small_animal_swallowed_by_a_big_one(self):
        """
        Пересечение считается от МЕНЬШЕЙ рамки, а не от объединения.

        Телёнок, перекрытый коровой почти целиком, — самый опасный
        случай для подсчёта. От суммы площадей это дало бы малую долю,
        и кадр не попал бы в отбор.
        """
        assert is_crowded([
            det(bbox=(0, 0, 400, 400)),
            det(bbox=(10, 10, 60, 60)),
        ]) is True

    def test_single_animal_is_never_crowded(self):
        assert is_crowded([det()]) is False

    def test_empty_is_never_crowded(self):
        assert is_crowded([]) is False

    def test_zero_sized_box_does_not_crash(self):
        """Вырожденная рамка приходит от модели редко, но приходит."""
        assert is_crowded([
            det(bbox=(50, 50, 50, 50)),
            det(bbox=(0, 0, 100, 100)),
        ]) is False


# ---------------------------------------------------------------------------
# Скачок счётчика
# ---------------------------------------------------------------------------
# Прямо определяет, будет ли завышаться поголовье в отчёте.


class TestCountJump:
    def test_no_previous_count_is_not_a_jump(self):
        assert count_jumped(10, None) is False

    def test_same_count_is_not_a_jump(self):
        assert count_jumped(10, 10) is False

    def test_one_animal_difference_is_never_a_jump(self):
        """
        На маленьком стаде доля срабатывает от любого движения: с одного
        животного на два — это сто процентов. Абсолютный минимум держит
        такие случаи вне отбора.
        """
        assert COUNT_JUMP_MIN == 2
        assert count_jumped(2, 1) is False

    def test_big_relative_change_is_a_jump(self):
        assert count_jumped(20, 12) is True

    def test_collapse_to_zero_is_a_jump(self):
        """Модель потеряла всех разом — это её сбой, а не пустой загон."""
        assert count_jumped(0, 8) is True

    def test_small_change_in_a_big_herd_is_not_a_jump(self):
        """
        Из сорока животных двое всегда кого-то заслоняют. Без доли такой
        кадр отбирался бы постоянно и выбрал бы весь суточный потолок.
        """
        assert count_jumped(40, 38) is False

    def test_quarter_change_is_the_threshold(self):
        assert count_jumped(8, 6) is True

    def test_share_is_taken_from_the_bigger_count(self):
        """
        Доля считается от БОЛЬШЕГО из двух счётов, и это не безразлично.

        Было двадцать, стало двадцать шесть: от большего это 23% и не
        скачок, от меньшего — 30% и скачок. Верно первое. Животные
        входят в кадр и выходят из него постоянно, и отбирать такие
        кадры значит выбрать весь суточный потолок движением стада,
        а не ошибками модели.
        """
        assert count_jumped(26, 20) is False
        assert count_jumped(20, 26) is False


# ---------------------------------------------------------------------------
# Итоговый отбор
# ---------------------------------------------------------------------------


class TestPickReason:
    def test_empty_frame_is_never_saved(self):
        """
        Камера над пустым загоном ночью иначе выбрала бы весь суточный
        потолок кадрами, на которых нечего размечать.
        """
        assert pick_reason([], previous_count=0, index=0) is None

    def test_empty_frame_is_not_saved_even_on_the_routine_turn(self):
        assert pick_reason([], previous_count=None, index=ROUTINE_EVERY * 3) is None

    def test_empty_frame_is_not_saved_even_after_a_collapse(self):
        """Счётчик рухнул с восьми до нуля — это скачок, но размечать
        на пустом кадре нечего."""
        assert pick_reason([], previous_count=8, index=1) is None

    def test_crowding_wins_over_doubt(self):
        """
        Порядок проверок задаёт причину в базе, а по ней потом отбирают
        кадры в разметку. Слипшиеся животные портят и подсчёт, и обмер
        силуэта — это тяжелее, чем неуверенность модели.
        """
        crowded_and_doubtful = [
            det(confidence=0.4, bbox=(0, 0, 100, 100)),
            det(confidence=0.4, bbox=(20, 20, 120, 120)),
        ]
        assert pick_reason(crowded_and_doubtful, previous_count=2, index=1) == "crowded"

    def test_count_jump_wins_over_doubt(self):
        apart = [
            det(confidence=0.4, bbox=(0, 0, 100, 100)),
            det(confidence=0.4, bbox=(500, 500, 600, 600)),
            det(confidence=0.4, bbox=(900, 900, 1000, 1000)),
        ]
        assert pick_reason(apart, previous_count=8, index=1) == "count_jump"

    def test_doubt_alone(self):
        assert pick_reason([det(confidence=0.4)], previous_count=1, index=1) == "low_confidence"

    def test_ordinary_frame_on_the_routine_turn(self):
        assert pick_reason([det(confidence=0.95)], previous_count=1, index=0) == "routine"

    def test_ordinary_frame_off_the_routine_turn_is_skipped(self):
        assert pick_reason([det(confidence=0.95)], previous_count=1, index=1) is None

    def test_routine_turn_comes_round_again(self):
        assert pick_reason(
            [det(confidence=0.95)], previous_count=1, index=ROUTINE_EVERY
        ) == "routine"

    def test_ordinary_frames_are_still_collected(self):
        """
        Четверть датасета — обычные дневные кадры. Без них модель
        разучится работать в лёгких условиях, и это заметят на первой же
        солнечной неделе.
        """
        confident = [det(confidence=0.95)]
        collected = sum(
            1 for i in range(100)
            if pick_reason(confident, previous_count=1, index=i) is not None
        )
        assert collected > 0


# ---------------------------------------------------------------------------
# Путь и кодирование
# ---------------------------------------------------------------------------


class TestPath:
    def test_starts_with_the_farm(self):
        path = training_path("ферма-1", "камера-2", datetime(2026, 8, 21, 14, 30, tzinfo=timezone.utc))
        assert path.startswith("ферма-1/")

    def test_holds_the_camera_and_the_day(self):
        path = training_path("f", "c", datetime(2026, 8, 21, 14, 30, tzinfo=timezone.utc))
        assert path.startswith("f/c/2026-08-21/")

    def test_paths_differ_within_the_same_second(self):
        """
        Постоянный путь — ровно та ошибка, из-за которой снимки
        предпросмотра не годятся для обучения: файл перезаписывается, и
        накопить съёмку невозможно.
        """
        first = training_path("f", "c", datetime(2026, 8, 21, 14, 30, 5, 100000, tzinfo=timezone.utc))
        second = training_path("f", "c", datetime(2026, 8, 21, 14, 30, 5, 900000, tzinfo=timezone.utc))
        assert first != second

    def test_day_is_a_separate_segment(self):
        """
        Датасет делят на обучение и проверку ПО ДНЯМ. При случайном
        делении почти у каждого кадра обучающей части есть близнец в
        проверочной, модель показывает 98% и не работает на новой ферме.
        """
        path = training_path("f", "c", datetime(2026, 8, 21, tzinfo=timezone.utc))
        assert path.split("/")[2] == "2026-08-21"


class TestEncoding:
    def test_produces_a_jpeg(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        payload = encode_training_frame(frame)
        assert payload[:2] == b"\xff\xd8"

    def test_does_not_shrink_the_frame(self):
        """
        Предпросмотр жмётся до 960 пикселей — для телефона это верно.
        Здесь наоборот: животное в дальнем углу загона занимает мало
        пикселей, и выбрасывать их значит собирать датасет, на котором
        не научиться тому, ради чего всё затевалось.
        """
        import cv2

        frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        decoded = cv2.imdecode(
            np.frombuffer(encode_training_frame(frame), np.uint8), cv2.IMREAD_COLOR
        )
        assert decoded.shape[:2] == (1080, 1920)


class TestDescribe:
    def test_counts_animals(self):
        assert describe([det(), det(), det()])["count"] == 3

    def test_reports_the_weakest_detection(self):
        summary = describe([det(confidence=0.9), det(confidence=0.42), det(confidence=0.8)])
        assert summary["min_confidence"] == pytest.approx(0.42)

    def test_groups_by_class(self):
        summary = describe([det(class_name="cow"), det(class_name="cow"), det(class_name="person")])
        assert summary["classes"] == {"cow": 2, "person": 1}

    def test_empty_frame_has_no_weakest(self):
        summary = describe([])
        assert summary["count"] == 0
        assert summary["min_confidence"] is None

    def test_boxes_are_a_share_of_the_frame_not_pixels(self):
        """
        Экран показывает кадр в любом размере — от телефона до монитора.
        В пикселях рамки пришлось бы пересчитывать на каждом, и ошибка
        в пересчёте выглядела бы как ошибка модели.
        """
        summary = describe([det(bbox=(192, 108, 384, 324))], width=1920, height=1080)
        box = summary["boxes"][0]
        assert box["x"] == pytest.approx(0.1)
        assert box["y"] == pytest.approx(0.1)
        assert box["w"] == pytest.approx(0.1)
        assert box["h"] == pytest.approx(0.2)

    def test_boxes_carry_the_confidence(self):
        summary = describe([det(confidence=0.42)], width=100, height=100)
        assert summary["boxes"][0]["c"] == pytest.approx(0.42)

    def test_no_boxes_without_frame_size(self):
        """
        Без размеров кадра доли посчитать не из чего. Пустой список
        честнее выдуманных координат: экран нарисует рамки не там, и
        админ отбракует правильный кадр.
        """
        assert describe([det()])["boxes"] == []


# ---------------------------------------------------------------------------
# Отправка
# ---------------------------------------------------------------------------


class TestUpload:
    def _client(self, rpc_result):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rpc_result)
        return client

    def test_uploads_then_records(self):
        client = self._client("новый-id")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        path = upload_training_frame(client, "f", "c", frame, "routine", [det()])

        assert path is not None
        client.storage.from_.assert_called_with(TRAINING_BUCKET)
        assert client.rpc.call_args[0][0] == "add_training_frame"

    def test_passes_the_reason_through(self):
        client = self._client("id")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        upload_training_frame(client, "f", "c", frame, "crowded", [det()])

        assert client.rpc.call_args[0][1]["p_reason"] == "crowded"

    def test_returns_nothing_when_the_cap_is_reached(self):
        client = self._client(None)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        assert upload_training_frame(client, "f", "c", frame, "routine", [det()]) is None

    def test_removes_the_orphan_when_the_cap_is_reached(self):
        """
        Файл кладётся раньше строки в базе. Если потолок выбран, файл
        останется в хранилище невидимым ниоткуда: он не попадёт ни в
        один датасет и не будет убран никогда.
        """
        client = self._client(None)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        upload_training_frame(client, "f", "c", frame, "routine", [det()])

        client.storage.from_.return_value.remove.assert_called_once()

    def test_keeps_the_file_when_the_row_was_written(self):
        client = self._client("id")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        upload_training_frame(client, "f", "c", frame, "routine", [det()])

        client.storage.from_.return_value.remove.assert_not_called()

    def test_survives_a_failed_cleanup(self):
        """
        Не смогли убрать мусорный файл — неприятно, но ронять из-за
        этого обработку видео нельзя.
        """
        client = self._client(None)
        client.storage.from_.return_value.remove.side_effect = RuntimeError("нет доступа")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        assert upload_training_frame(client, "f", "c", frame, "routine", [det()]) is None
