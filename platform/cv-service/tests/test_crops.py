from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.crops import (
    CROP_BUCKET,
    DEFAULT_MATCH_THRESHOLD,
    identify,
    match_known_animal,
    BestCrop,
    CropCollector,
    crop_path,
    crops_enabled,
    encode_crop,
    insert_seen,
)
from cv_service.detector import Detection


def _frame(width=640, height=480):
    rng = np.random.default_rng(seed=3)
    return rng.integers(0, 255, (height, width, 3), dtype=np.uint8)


def _detection(track_id: int, box, confidence=0.9) -> Detection:
    return Detection(track_id=track_id, class_name="cow", confidence=confidence, bbox=box)


class TestCropsEnabled:
    def test_enabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            assert crops_enabled() is True

    def test_can_be_turned_off(self):
        with patch.dict("os.environ", {"COLLECT_CROPS": "0"}, clear=True):
            assert crops_enabled() is False


class TestCropCollector:
    def test_keeps_one_crop_per_track(self):
        collector = CropCollector()
        collector.add(_frame(), [_detection(1, (10, 10, 200, 300))], now=0.0)
        collector.add(_frame(), [_detection(1, (12, 12, 202, 302))], now=1.0)
        assert len(collector.flush()) == 1

    def test_prefers_the_bigger_clearer_crop(self):
        collector = CropCollector()
        collector.add(_frame(), [_detection(1, (10, 10, 100, 100), 0.5)], now=0.0)
        collector.add(_frame(), [_detection(1, (10, 10, 400, 400), 0.9)], now=1.0)
        best = collector.flush()[0]
        assert best.confidence == 0.9
        assert best.area > 100 * 100

    def test_ignores_tiny_boxes(self):
        """Мелкая рамка — животное далеко, для распознавания бесполезно."""
        collector = CropCollector()
        collector.add(_frame(), [_detection(1, (10, 10, 40, 40))], now=0.0)
        assert collector.flush() == []

    def test_clamps_boxes_to_the_frame(self):
        collector = CropCollector()
        collector.add(_frame(320, 240), [_detection(1, (-50, -50, 1000, 1000))], now=0.0)
        crop = collector.flush()[0]
        assert crop.image.shape[0] <= 240
        assert crop.image.shape[1] <= 320

    def test_tracks_several_animals(self):
        collector = CropCollector()
        collector.add(
            _frame(),
            [_detection(1, (10, 10, 200, 300)), _detection(2, (300, 10, 500, 300))],
            now=0.0,
        )
        assert len(collector.flush()) == 2

    def test_finishes_a_track_after_the_timeout(self):
        collector = CropCollector(track_timeout_s=20)
        collector.add(_frame(), [_detection(1, (10, 10, 200, 300))], now=0.0)
        assert collector.take_finished(now=10.0) == []
        assert len(collector.take_finished(now=25.0)) == 1

    def test_a_finished_track_is_not_returned_twice(self):
        collector = CropCollector(track_timeout_s=20)
        collector.add(_frame(), [_detection(1, (10, 10, 200, 300))], now=0.0)
        collector.take_finished(now=25.0)
        assert collector.take_finished(now=30.0) == []

    def test_still_visible_track_stays(self):
        collector = CropCollector(track_timeout_s=20)
        collector.add(_frame(), [_detection(1, (10, 10, 200, 300))], now=0.0)
        collector.add(_frame(), [_detection(1, (10, 10, 200, 300))], now=19.0)
        assert collector.take_finished(now=25.0) == []


def test_encode_crop_returns_jpeg():
    data = encode_crop(_frame(200, 200))
    assert data[:2] == b"\xff\xd8"


def test_encode_crop_raises_on_failure():
    with patch("cv_service.crops.cv2.imencode", return_value=(False, None)):
        with pytest.raises(RuntimeError, match="закодировать"):
            encode_crop(_frame(200, 200))


def test_crop_path_is_unique_and_starts_with_the_farm():
    """Первый сегмент пути определяет права доступа."""
    first = crop_path("farm-1", "cam-1", 7, 1000.0)
    second = crop_path("farm-1", "cam-1", 7, 1001.0)
    assert first.startswith("farm-1/")
    assert first != second


class TestInsertSeen:
    """
    Встреча узнанного животного.

    Раньше здесь сохранялся каждый трек: кадр в хранилище, вектор в базе,
    строка «ждёт имени». Очередь этих строк никто не разбирал, а эталоны
    из неё были догадками — человек опознавал животное на глаз по мутному
    кадру со спины, и ошибка закреплялась навсегда.
    """

    def _client(self):
        client = MagicMock()
        client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "s1"}]
        )
        return client

    def _crop(self):
        return BestCrop(
            track_id=4, image=_frame(80, 80), confidence=0.82, area=1.0, last_seen_at=0.0
        )

    def test_records_which_animal_was_seen(self):
        client = self._client()
        insert_seen(client, "farm-1", "cam-1", "a1", self._crop())

        row = client.table.return_value.insert.call_args[0][0]
        assert row["animal_id"] == "a1"
        assert row["track_id"] == 4
        assert row["confidence"] == 0.82

    def test_does_not_store_a_vector(self):
        """
        Эталоны берутся только из фото, загруженных человеком осознанно.
        Вектор со случайного кадра снова сделал бы догадку эталоном.
        """
        client = self._client()
        insert_seen(client, "farm-1", "cam-1", "a1", self._crop())

        assert "embedding" not in client.table.return_value.insert.call_args[0][0]

    def test_does_not_upload_a_picture(self):
        client = self._client()
        insert_seen(client, "farm-1", "cam-1", "a1", self._crop())

        client.storage.from_.assert_not_called()


class TestMatchKnownAnimal:
    def _client(self, rows):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = MagicMock(data=rows)
        return client

    def test_returns_the_closest_named_animal(self):
        """Это и решает проблему «одно животное считается разными»."""
        client = self._client([{"animal_id": "a1", "label": "Зорька", "distance": 0.12}])
        assert match_known_animal(client, "farm-1", [0.1, 0.2]) == "a1"

    def test_returns_nothing_when_no_one_is_close_enough(self):
        assert match_known_animal(self._client([]), "farm-1", [0.1]) is None

    def test_handles_an_empty_response(self):
        assert match_known_animal(self._client(None), "farm-1", [0.1]) is None

    def test_passes_the_farm_and_threshold(self):
        client = self._client([])
        match_known_animal(client, "farm-1", [0.1, 0.2])
        # Первый вызов — рабочий. Второй, если он был, это добор чисел
        # для журнала, и порог там намеренно другой
        args = client.rpc.call_args_list[0][0][1]
        assert args["target_farm_id"] == "farm-1"
        assert args["match_threshold"] == DEFAULT_MATCH_THRESHOLD

    def test_threshold_can_be_tightened(self):
        client = self._client([])
        match_known_animal(client, "farm-1", [0.1], threshold=0.2)
        assert client.rpc.call_args_list[0][0][1]["match_threshold"] == 0.2




class TestIdentifyDistinguishesUnknownFromAmbiguous:
    """
    Разница, которая стоила работоспособности всего узнавания.

    Раньше «никого рядом нет» и «похожих сразу несколько» возвращали
    одно и то же — None. Автозаведение принимало второе за первое и
    заводило ещё одну запись того же животного. Кандидатов становилось
    больше, отрыв между ними меньше, и через несколько заходов система
    переставала узнавать вообще кого-либо.
    """

    def _client(self, rows):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rows)
        return client

    def test_uverennoe_sovpadenie(self):
        match = identify(
            self._client([{"animal_id": "a1", "distance": 0.1, "margin": 0.3}]),
            "farm-1",
            [0.1],
        )
        assert match.animal_id == "a1"
        assert not match.ambiguous
        assert match.anyone_close

    def test_nikogo_ryadom(self):
        match = identify(self._client([]), "farm-1", [0.1])
        assert match.animal_id is None
        assert not match.ambiguous
        # Только здесь можно заводить новую запись
        assert not match.anyone_close

    def test_pokhozhikh_neskolko(self):
        match = identify(
            self._client([{"animal_id": "a1", "distance": 0.1, "margin": 0.001}]),
            "farm-1",
            [0.1],
        )
        assert match.animal_id is None, "называть одного из двух — гадание"
        assert match.ambiguous
        assert match.anyone_close, "новую запись заводить нельзя"

    def test_odno_zhivotnoe_na_ferme_uznayotsya(self):
        # Сравнивать не с кем, отрыв пуст — это не двусмысленность
        match = identify(
            self._client([{"animal_id": "a1", "distance": 0.1, "margin": None}]),
            "farm-1",
            [0.1],
        )
        assert match.animal_id == "a1"
        assert not match.ambiguous

    def test_staraya_obyortka_otdayot_tolko_klichku(self):
        client = self._client([{"animal_id": "a1", "distance": 0.1, "margin": 0.3}])
        assert match_known_animal(client, "farm-1", [0.1]) == "a1"


class TestExplainForLog:
    """
    «Животное не узнано» само по себе не объясняет ничего: то ли эталон
    далёк на волосок, то ли модель вообще не видит сходства. Первое
    лечится порогом, второе — сменой модели, и перепутать их дорого.
    """

    def _client(self, rows, wide=None):
        client = MagicMock()
        answers = [SimpleNamespace(data=rows)]
        if wide is not None:
            answers.append(SimpleNamespace(data=wide))
        client.rpc.return_value.execute.side_effect = answers
        return client

    def test_kogda_porog_ne_proyden_rasstoyanie_vsyo_ravno_izvestno(self):
        # Ради этого и делается второй запрос: иначе в журнале пусто
        client = self._client([], wide=[{"animal_id": "a1", "distance": 0.42}])
        match = identify(client, "farm-1", [0.1])

        assert match.animal_id is None
        assert match.distance == 0.42
        assert "0.42" in match.explain(0.35)

    def test_sovsem_pustaya_baza_govorit_pryamo(self):
        client = self._client([], wide=[])
        match = identify(client, "farm-1", [0.1])
        assert "похожих нет вовсе" in match.explain(0.35)

    def test_uverennoe_sovpadenie_pokazyvaet_oba_chisla(self):
        client = self._client([{"animal_id": "a1", "distance": 0.12, "margin": 0.3}])
        text = identify(client, "farm-1", [0.1]).explain(0.35)
        assert "0.120" in text and "0.300" in text

    def test_dvusmyslennost_nazvana(self):
        client = self._client([{"animal_id": "a1", "distance": 0.12, "margin": 0.01}])
        text = identify(client, "farm-1", [0.1]).explain(0.35)
        assert "отрыв мал" in text


class TestKameraUchastvuetVPoiske:
    """
    Кадр надо сравнивать прежде всего с эталонами СВОЕЙ камеры.

    Сверху видна спина, сбоку профиль. Профиль отличается от спины
    сильнее, чем спина одного животного от спины другого, — и чужой
    эталон «правильного» ракурса может оказаться ближе своего.
    """

    def _client(self, rows):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rows)
        return client

    def test_kamera_uhodit_v_zapros(self):
        client = self._client([{"animal_id": "a1", "distance": 0.1}])
        identify(client, "farm-1", [0.1], camera_id="cam-верх")
        assert client.rpc.call_args_list[0][0][1]["target_camera_id"] == "cam-верх"

    def test_bez_kamery_argument_pustoy(self):
        # Не выдумываем камеру: пустое значение отключает надбавку, а
        # выдуманное дало бы её не тем эталонам
        client = self._client([{"animal_id": "a1", "distance": 0.1}])
        identify(client, "farm-1", [0.1])
        assert client.rpc.call_args_list[0][0][1]["target_camera_id"] is None

    def test_staraya_baza_bez_argumenta_ne_lomaet_uznavanie(self):
        # Отказ выбрать функцию из-за лишнего аргумента не должен
        # выглядеть как «никого не нашли»: это разные вещи, и лечатся
        # они по-разному
        client = MagicMock()
        answers = [
            Exception("Could not choose the best candidate function"),
            SimpleNamespace(data=[{"animal_id": "a1", "distance": 0.1}]),
        ]

        def rpc(_name, _payload):
            answer = answers.pop(0)
            call = MagicMock()
            if isinstance(answer, Exception):
                call.execute.side_effect = answer
            else:
                call.execute.return_value = answer
            return call

        client.rpc.side_effect = rpc
        assert identify(client, "farm-1", [0.1], camera_id="cam").animal_id == "a1"

    def test_setevaya_oshibka_ne_glotaetsya(self):
        # Если дело не в аргументах, а в сети или доступе, ошибка должна
        # дойти до вызывающего. Молчаливое «не узнано» отправило бы
        # разбираться не туда
        client = MagicMock()
        client.rpc.return_value.execute.side_effect = RuntimeError("сеть недоступна")
        with pytest.raises(RuntimeError):
            identify(client, "farm-1", [0.1], camera_id="cam")


class TestSpornyyKadrOstavlyaetKandidata:
    def _client(self, rows):
        client = MagicMock()
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rows)
        return client

    def test_pri_malom_otryve_kandidat_izvesten(self):
        # Без этого переспрашивать было бы не о чем: голосовать не за кого
        match = identify(
            self._client([{"animal_id": "a1", "distance": 0.20, "margin": 0.01}]),
            "farm-1",
            [0.1],
        )
        assert match.ambiguous
        assert match.animal_id is None
        assert match.candidate == "a1"

    def test_pri_uverennom_otryve_kandidat_on_zhe_otvet(self):
        match = identify(
            self._client([{"animal_id": "a1", "distance": 0.10, "margin": 0.30}]),
            "farm-1",
            [0.1],
        )
        assert match.animal_id == "a1"
        assert match.candidate == "a1"


class TestRezkostVyboreKadra:
    """
    Смазанный кадр не только даёт негодный вектор — он стоит тех же
    двух секунд счёта. Резкость участвует в выборе лучшего кадра, но
    не отсекает: животное могло всю дорогу идти быстро, и тогда все
    кадры смазаны, а опознать его всё равно надо.
    """

    def _sharp(self, side=200):
        # Шахматка: перепадов яркости много
        image = np.zeros((side, side, 3), dtype=np.uint8)
        image[::4] = 255
        image[:, ::4] = 255
        return image

    def _blurred(self, side=200):
        # Ровная заливка: перепадов нет вовсе
        return np.full((side, side, 3), 128, dtype=np.uint8)

    def test_chyotkiy_rezche_smazannogo(self):
        from cv_service.crops import sharpness

        assert sharpness(self._sharp()) > sharpness(self._blurred())

    def test_odno_soderzhimoe_v_raznom_razmere_odna_rezkost(self):
        """
        Главное свойство замера: он про чёткость, а не про размер.

        Мелкая фактура — шерсть, солома — на крупном кадре видна, а на
        мелком усредняется. Без приведения к общей ширине то же самое
        животное вблизи набирает в десятки раз больше, чем вдали, и
        «резкость» превращается в «размер», который и так учтён.

        Ровная заливка для этой проверки не годится: у неё перепадов нет
        ни при каком размере, и приведение на неё не влияет. Нужна
        именно фактура.
        """
        import cv2
        from cv_service.crops import sharpness

        rng = np.random.default_rng(7)
        big = rng.integers(0, 255, (600, 600, 3), dtype=np.uint8)
        small = cv2.resize(big, (120, 120), interpolation=cv2.INTER_AREA)

        ratio = sharpness(big) / max(1.0, sharpness(small))
        # С приведением отношение около единицы, без него — за двадцать
        assert 0.3 < ratio < 3.0

    def test_smazannoe_proigryvaet_chyotkomu_nezavisimo_ot_razmera(self):
        import cv2
        from cv_service.crops import sharpness

        rng = np.random.default_rng(7)
        big = rng.integers(0, 255, (600, 600, 3), dtype=np.uint8)
        blurred_big = cv2.GaussianBlur(big, (21, 21), 8)
        sharp_small = cv2.resize(big, (120, 120), interpolation=cv2.INTER_AREA)

        assert sharpness(blurred_big) < sharpness(sharp_small)

    def test_bityy_kadr_ne_ronyaet(self):
        from cv_service.crops import sharpness

        assert sharpness(np.zeros((0, 0, 3), dtype=np.uint8)) >= 0.0

    def test_pri_ravnom_razmere_pobezhdaet_chyotkiy(self):
        from cv_service.crops import crop_score, SHARP_ENOUGH

        blurry = crop_score(area=90_000, confidence=0.9, sharp=SHARP_ENOUGH / 10)
        sharp = crop_score(area=90_000, confidence=0.9, sharp=SHARP_ENOUGH)
        assert sharp > blurry

    def test_krupnyy_vsyo_zhe_vazhnee_melkogo(self):
        # Резкость — поправка, а не главный признак. Мелкое пятно вдалеке
        # даёт вектор ни о чём, каким бы чётким оно ни было
        from cv_service.crops import crop_score, SHARP_ENOUGH

        big = crop_score(area=400_000, confidence=0.9, sharp=SHARP_ENOUGH / 2)
        small = crop_score(area=40_000, confidence=0.9, sharp=SHARP_ENOUGH)
        assert big > small

    def test_sverkhrezkiy_ne_pereveshivaet_bez_konca(self):
        # Потолок обязателен: без него кадр с шумом или дождём набирал бы
        # огромную «резкость» и вытеснял нормальные
        from cv_service.crops import crop_score, SHARP_ENOUGH

        normal = crop_score(area=100_000, confidence=0.9, sharp=SHARP_ENOUGH)
        noisy = crop_score(area=100_000, confidence=0.9, sharp=SHARP_ENOUGH * 50)
        assert noisy == normal


class TestSbrosKadraDlyaPereprosa:
    def test_sbros_ne_nachinaet_trek_zanovo(self):
        # Иначе после каждого спорного опознания пришлось бы снова ждать
        # три секунды, а животное к тому времени уходит
        collector = CropCollector(identify_after_s=3.0)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        detection = Detection(1, "cow", 0.9, (100.0, 100.0, 500.0, 500.0))

        collector.add(frame, [detection], now=0.0)
        collector.refresh(1)
        collector.add(frame, [detection], now=0.1)

        assert collector.ready_to_identify(set(), now=3.5)

    def test_posle_sbrosa_beryotsya_novyy_kadr(self):
        # Без сброса второй заход считал бы вектор по тому же самому
        # кадру и получил бы тот же спорный ответ
        collector = CropCollector()
        bright = np.full((720, 1280, 3), 200, dtype=np.uint8)
        dark = np.zeros((720, 1280, 3), dtype=np.uint8)
        detection = Detection(1, "cow", 0.9, (100.0, 100.0, 500.0, 500.0))

        collector.add(bright, [detection], now=0.0)
        collector.refresh(1)
        collector.add(dark, [detection], now=0.1)

        taken = collector.flush()
        assert len(taken) == 1
        assert int(taken[0].image.mean()) == 0
