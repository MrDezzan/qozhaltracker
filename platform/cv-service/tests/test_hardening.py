import time
"""
Проверки на то, что чинилось после разбора продакшен-рисков:
частота трекинга, буфер событий, привязка визита к животному,
повторные попытки опознания, перезапуск камеры, чистка памяти.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.crops import Match, BestCrop, IdentificationTracker
from cv_service.detector import Detection
from cv_service.main import (
    _forget_track,
    _identify_live,
    _run_camera_safely,
    _write_event,
    _write_visits,
    process_camera,
    run,
    track_fps,
    visit_to_event,
)
from cv_service.morphometry import MorphometryCollector
from cv_service.spool import EventSpool
from cv_service.zones import Visit, Zone

FEEDER = Zone(id="z1", name="Кормушка", kind="feeder", polygon=((0, 0), (1, 0), (1, 1), (0, 1)))


def _frame(width=640, height=480):
    rng = np.random.default_rng(seed=11)
    return rng.integers(0, 255, (height, width, 3), dtype=np.uint8)


def _capture(count: int):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.side_effect = [(True, _frame()) for _ in range(count)] + [(False, None)]
    return cap


def _detection(track_id=1):
    return Detection(track_id=track_id, class_name="cow", confidence=0.9, bbox=(10, 10, 90, 60))


# ---------------------------------------------------------------------------
# Частота трекинга
# ---------------------------------------------------------------------------


class TestTrackFps:
    def test_default_is_high_enough_to_keep_a_track(self):
        """
        Ниже нескольких кадров в секунду ByteTrack теряет животное между
        вызовами и выдаёт ему новый номер. Отсюда росло завышенное поголовье.
        """
        with patch.dict("os.environ", {}, clear=True):
            assert track_fps() >= 4.0

    def test_can_be_lowered_for_a_weak_machine(self):
        with patch.dict("os.environ", {"TRACK_FPS": "4"}, clear=True):
            assert track_fps() == 4.0

    def test_garbage_falls_back_to_the_default(self):
        with patch.dict("os.environ", {"TRACK_FPS": "быстро"}, clear=True):
            assert track_fps() >= 4.0

    def test_zero_is_not_accepted(self):
        """Ноль означал бы деление на ноль и остановку трекинга."""
        with patch.dict("os.environ", {"TRACK_FPS": "0"}, clear=True):
            assert track_fps() > 0


def _clock(step: float):
    """Часы, шагающие на фиксированную величину при каждом обращении."""
    state = {"now": 0.0}

    def tick():
        state["now"] += step
        return state["now"]

    return tick


def _run_ten_frames(detector, track_fps_value: str, frame_interval_s: float, step: float):
    with patch("cv_service.main.time.monotonic", side_effect=_clock(step)):
        with patch.dict("os.environ", {"TRACK_FPS": track_fps_value}, clear=True):
            process_camera(
                MagicMock(),
                detector,
                "farm-1",
                {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"},
                frame_interval_s=frame_interval_s,
            )


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=False)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_tracker_runs_on_every_frame_not_once_per_heavy_interval(
    mock_capture, _insert, _hb, _zones, _crops, _preview, _snap, capsys
):
    """
    Главная поломка, которую чинили: трекер вызывался с той же редкой
    частотой, что и запись в базу. Тяжёлое должно быть редким, трекинг — нет.

    Кадры идут раз в секунду. При десяти кадрах в секунду трекер обязан
    отработать на каждом, а дорогой контур с интервалом в час — ни разу.
    """
    mock_capture.return_value = _capture(10)
    detector = MagicMock()
    detector.detect_and_track.return_value = [_detection()]

    _run_ten_frames(detector, "10", frame_interval_s=3600.0, step=1.0)

    assert detector.detect_and_track.call_count == 10
    assert "обнаружено животных" not in capsys.readouterr().out


@patch("cv_service.main.snapshots_enabled", return_value=False)
@patch("cv_service.main.preview_enabled", return_value=False)
@patch("cv_service.main.crops_enabled", return_value=False)
@patch("cv_service.main.fetch_zones", return_value=[])
@patch("cv_service.main.send_heartbeat")
@patch("cv_service.main.insert_event")
@patch("cv_service.main.cv2.VideoCapture")
def test_a_weak_machine_still_tracks_at_the_configured_rate(
    mock_capture, _insert, _hb, _zones, _crops, _preview, _snap
):
    """Кадры каждые полсекунды, трекер настроен на один в секунду — через раз."""
    mock_capture.return_value = _capture(10)
    detector = MagicMock()
    detector.detect_and_track.return_value = [_detection()]

    _run_ten_frames(detector, "1", frame_interval_s=3600.0, step=0.5)

    assert detector.detect_and_track.call_count == 5


# ---------------------------------------------------------------------------
# Буфер событий
# ---------------------------------------------------------------------------


class TestEventBuffering:
    def _event(self):
        return visit_to_event(
            Visit(zone=FEEDER, track_id=1, started_at=0.0, last_seen_at=60.0),
            "farm-1",
            "cam-1",
        )

    @patch("cv_service.main.insert_event", side_effect=Exception("нет сети"))
    def test_a_lost_event_goes_to_the_buffer(self, _insert, tmp_path):
        spool = EventSpool(path=str(tmp_path / "s.db"))
        assert _write_event(MagicMock(), self._event(), spool) == 0
        assert spool.count() == 1
        spool.close()

    @patch("cv_service.main.insert_event")
    def test_a_delivered_event_is_not_buffered(self, _insert, tmp_path):
        spool = EventSpool(path=str(tmp_path / "s.db"))
        assert _write_event(MagicMock(), self._event(), spool) == 1
        assert spool.count() == 0
        spool.close()

    @patch("cv_service.main.insert_event", side_effect=Exception("нет сети"))
    def test_without_a_buffer_nothing_explodes(self, _insert):
        """Отладочный запуск без буфера должен просто пережить обрыв."""
        assert _write_event(MagicMock(), self._event(), None) == 0

    @patch("cv_service.main.insert_event", side_effect=Exception("нет сети"))
    def test_the_buffered_row_keeps_its_own_time(self, _insert, tmp_path):
        """
        Событие несёт время устройства. Иначе всё накопленное за ночь
        слиплось бы в момент отправки утром.
        """
        spool = EventSpool(path=str(tmp_path / "s.db"))
        event = self._event()
        _write_event(MagicMock(), event, spool)

        stored = spool.take()[0][1]
        assert stored["occurred_at"] == event.to_row()["occurred_at"]
        spool.close()


# ---------------------------------------------------------------------------
# Визит и животное
# ---------------------------------------------------------------------------


class TestVisitCarriesTheAnimal:
    def test_a_recognised_animal_is_attached_to_the_visit(self):
        """«Зорька ела 12 минут» вместо «кто-то ел 12 минут»."""
        event = visit_to_event(
            Visit(zone=FEEDER, track_id=4, started_at=0.0, last_seen_at=720.0),
            "farm-1",
            "cam-1",
            animal_id="a1",
        )
        assert event.animal_id == "a1"

    def test_an_unknown_animal_leaves_the_field_empty(self):
        event = visit_to_event(
            Visit(zone=FEEDER, track_id=4, started_at=0.0, last_seen_at=720.0),
            "farm-1",
            "cam-1",
        )
        assert event.animal_id is None

    @patch("cv_service.main.insert_event")
    def test_write_visits_looks_up_the_track(self, mock_insert):
        visits = [Visit(zone=FEEDER, track_id=9, started_at=0.0, last_seen_at=60.0)]

        _write_visits(
            MagicMock(), "farm-1", {"id": "cam-1", "name": "К"}, visits, {9: "a-9"}
        )

        assert mock_insert.call_args[0][1].animal_id == "a-9"

    @patch("cv_service.main.insert_event")
    def test_write_visits_without_a_mapping_still_works(self, mock_insert):
        visits = [Visit(zone=FEEDER, track_id=9, started_at=0.0, last_seen_at=60.0)]
        _write_visits(MagicMock(), "farm-1", {"id": "cam-1", "name": "К"}, visits)
        assert mock_insert.call_args[0][1].animal_id is None


# ---------------------------------------------------------------------------
# Повторные попытки опознания
# ---------------------------------------------------------------------------


class TestIdentificationRetries:
    def test_a_fresh_track_is_not_skipped(self):
        assert IdentificationTracker().skip(now=0.0) == set()

    def test_a_just_tried_track_waits(self):
        tracker = IdentificationTracker(retry_after_s=15.0)
        tracker.record_attempt(1, now=0.0)
        assert 1 in tracker.skip(now=5.0)

    def test_the_track_is_tried_again_after_the_pause(self):
        """
        Животное могло стоять боком. Раньше первая же неудача закрывала
        трек навсегда, и удачный ракурс через минуту пропадал зря.
        """
        tracker = IdentificationTracker(retry_after_s=15.0)
        tracker.record_attempt(1, now=0.0)
        assert 1 not in tracker.skip(now=20.0)

    def test_it_gives_up_eventually(self):
        tracker = IdentificationTracker(max_attempts=3, retry_after_s=0.0)
        for n in range(3):
            tracker.record_attempt(1, now=float(n))
        assert 1 in tracker.skip(now=100.0)

    def test_a_recognised_track_is_not_tried_again(self):
        tracker = IdentificationTracker()
        tracker.record_success(1)
        assert 1 in tracker.skip(now=1000.0)

    def test_forget_resets_everything(self):
        tracker = IdentificationTracker()
        tracker.record_success(1)
        tracker.forget(1)
        assert 1 not in tracker.skip(now=0.0)


@patch("cv_service.main.fetch_animal_names", return_value={"a1": "Зорька"})
@patch("cv_service.main.identify")
def test_identify_live_fills_both_name_and_id(mock_match, _names):
    """Кличку показываем на экране, идентификатор — прикрепляем к визиту."""
    mock_match.return_value = Match(animal_id="a1")
    collector = MagicMock()
    collector.ready_to_identify.return_value = [
        BestCrop(track_id=3, image=_frame(80, 80), confidence=0.9, area=1.0, last_seen_at=0.0)
    ]
    names, animals = {}, {}

    _identify_live(
        MagicMock(),
        "farm-1",
        collector,
        MagicMock(),
        IdentificationTracker(),
        names,
        animals,
        now=10.0,
    )

    assert names[3] == "Зорька"
    assert animals[3] == "a1"


@patch("cv_service.main.identify", return_value=Match())
def test_a_failed_match_does_not_poison_the_track(mock_match):
    """После промаха трек должен остаться доступным для новой попытки."""
    collector = MagicMock()
    collector.ready_to_identify.return_value = [
        BestCrop(track_id=3, image=_frame(80, 80), confidence=0.9, area=1.0, last_seen_at=0.0)
    ]
    tracker = IdentificationTracker(retry_after_s=15.0)

    _identify_live(
        MagicMock(), "farm-1", collector, MagicMock(), tracker, {}, {}, now=0.0
    )

    assert 3 in tracker.skip(now=1.0)
    assert 3 not in tracker.skip(now=30.0)


# ---------------------------------------------------------------------------
# Память
# ---------------------------------------------------------------------------


def test_finished_track_is_cleared_everywhere():
    """
    Сервис на ферме работает месяцами, а номера треков не переиспользуются.
    Без чистки словари росли бы всё это время.
    """
    names = {5: "Зорька"}
    animals = {5: "a1"}
    tracker = IdentificationTracker()
    tracker.record_success(5)
    morphometry = MorphometryCollector(min_samples=1)
    morphometry.add([_detection(5)], 640, 480)

    _forget_track(5, animals, names, tracker, morphometry)

    assert names == {} and animals == {}
    assert 5 not in tracker.skip(now=0.0)
    assert morphometry.tracked() == set()


# ---------------------------------------------------------------------------
# Перезапуск камеры
# ---------------------------------------------------------------------------


class TestCameraRestart:
    CAMERA = {"id": "cam-1", "name": "Кормушка", "source_uri": "rtsp://x"}

    @patch("cv_service.main.time.sleep")
    @patch("cv_service.main.Detector")
    @patch("cv_service.main.process_camera")
    def test_a_crashed_camera_comes_back(self, mock_process, _det, _sleep):
        """
        Раньше поток просто умирал, и камера молчала до ручного перезапуска —
        обычно до следующего приезда на ферму.
        """
        mock_process.side_effect = RuntimeError("камера недоступна")
        _run_camera_safely(MagicMock(), "farm-1", self.CAMERA, 2.0, max_restarts=3)
        assert mock_process.call_count == 3

    @patch("cv_service.main.time.sleep")
    @patch("cv_service.main.Detector")
    @patch("cv_service.main.process_camera")
    def test_the_pause_grows(self, mock_process, _det, mock_sleep):
        """Чтобы не молотить в отвалившуюся камеру каждую секунду."""
        mock_process.side_effect = RuntimeError("нет камеры")
        _run_camera_safely(MagicMock(), "farm-1", self.CAMERA, 2.0, max_restarts=3)

        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == sorted(delays)
        assert delays[-1] > delays[0]

    @patch("cv_service.main.time.sleep")
    @patch("cv_service.main.Detector")
    @patch("cv_service.main.process_camera")
    def test_a_finished_file_is_not_restarted(self, mock_process, _det, _sleep):
        """Кончившийся файл — это нормальное завершение, а не сбой."""
        mock_process.return_value = 5
        _run_camera_safely(MagicMock(), "farm-1", self.CAMERA, 2.0, max_restarts=3)
        assert mock_process.call_count == 1

    @patch("cv_service.main.time.sleep")
    @patch("cv_service.main.Detector")
    @patch("cv_service.main.process_camera")
    def test_each_restart_gets_a_fresh_detector(self, mock_process, mock_detector, _sleep):
        """Трекер держит состояние внутри модели: после сбоя оно уже мусор."""
        mock_process.side_effect = RuntimeError("сбой")
        _run_camera_safely(MagicMock(), "farm-1", self.CAMERA, 2.0, max_restarts=2)
        assert mock_detector.call_count == 2


# ---------------------------------------------------------------------------
# Живой просмотр целиком
# ---------------------------------------------------------------------------


class TestLiveViewWiring:
    """
    Опрос живого режима — фоновый поток. Создать его мало: незапущенный
    поток выглядит совершенно исправно, опрашивает базу один раз при старте
    и больше никогда. Снаружи это неотличимо от «никто не смотрит».
    """

    CAMERA = {"id": "cam-1", "name": "Кормушка", "source_uri": "test.mp4"}

    @patch("cv_service.main.start_stream_server")
    @patch("cv_service.main._run_camera_safely")
    @patch("cv_service.main.Embedder")
    @patch("cv_service.main.embeddings_enabled", return_value=False)
    @patch("cv_service.main.EventSpool")
    @patch("cv_service.main.fetch_cameras")
    @patch("cv_service.main.get_device_farm_id", return_value="farm-1")
    @patch("cv_service.main.get_client")
    def test_run_starts_the_polling_thread(
        self, _client, _farm, mock_cameras, _spool, _emb_on, _emb, _safely, _stream
    ):
        mock_cameras.return_value = [self.CAMERA]

        with patch("cv_service.main.LiveWindow") as mock_window:
            run()

        mock_window.return_value.start.assert_called_once()

    @patch("cv_service.main.snapshots_enabled", return_value=True)
    @patch("cv_service.main.preview_enabled", return_value=False)
    @patch("cv_service.main.crops_enabled", return_value=False)
    @patch("cv_service.main.fetch_zones", return_value=[])
    @patch("cv_service.main.send_heartbeat")
    @patch("cv_service.main.insert_event")
    @patch("cv_service.main.cv2.VideoCapture")
    def test_a_camera_complains_about_an_unstarted_poller(
        self, mock_capture, _insert, _hb, _zones, _crops, _preview, _snap, capsys
    ):
        """Молчаливая поломка хуже громкой: пусть говорит о себе сам."""
        mock_capture.return_value = _capture(2)
        detector = MagicMock()
        detector.detect_and_track.return_value = []

        not_started = MagicMock()
        not_started.is_alive.return_value = False

        process_camera(
            MagicMock(), detector, "farm-1", self.CAMERA, live_view=not_started
        )

        assert "не запущен" in capsys.readouterr().out


class TestGolosovaniePriSomnenii:
    """
    Спорное опознание переспрашивается по другому кадру.

    Когда второй кандидат идёт вплотную, назвать ближайшего — то же, что
    подбросить монету. Неверная кличка на кадре разрушает доверие
    быстрее, чем её отсутствие, поэтому вместо догадки берётся ещё один
    кадр того же трека.
    """

    def test_odin_golos_ne_reshaet(self):
        tracker = IdentificationTracker()
        assert tracker.vote(1, "a1") is None

    def test_dva_soglasnykh_golosa_reshayut(self):
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        assert tracker.vote(1, "a1") == "a1"

    def test_nesoglasnye_golosa_ne_reshayut(self):
        # Два кадра назвали разных — значит, модель не различает этих
        # животных, и назвать любого было бы враньём
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        assert tracker.vote(1, "a2") is None

    def test_tretiy_golos_dobiraet_bolshinstvo(self):
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        tracker.vote(1, "a2")
        assert tracker.vote(1, "a1") == "a1"

    def test_golosa_ne_smeshivayutsya_mezhdu_trekami(self):
        # Иначе две коровы рядом голосовали бы друг за друга
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        assert tracker.vote(2, "a1") is None

    def test_spornyy_trek_perepryashivaetsya_bystro(self):
        # Пятнадцать секунд, как после полной неудачи, означали бы, что
        # животное успело уйти из кадра
        tracker = IdentificationTracker(retry_after_s=15.0, doubt_retry_after_s=1.0)
        tracker.record_attempt(1, now=100.0)
        tracker.vote(1, "a1")
        assert 1 not in tracker.skip(now=101.5)

    def test_beznadyozhnyy_trek_zhdyot_dolgo(self):
        # Никто не был близок — значит, и через секунду не будет.
        # Считать вектор заново каждую секунду означало бы съесть
        # процессор на треке, с которого нечего взять
        tracker = IdentificationTracker(retry_after_s=15.0, doubt_retry_after_s=1.0)
        tracker.record_attempt(1, now=100.0)
        assert 1 in tracker.skip(now=101.5)

    def test_uspekh_ochishchaet_golosa(self):
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        tracker.record_success(1)
        assert tracker.votes(1) == 0

    def test_zabytyy_trek_ne_ostavlyaet_golosov(self):
        # Номер трека переиспользуется: чужие голоса на нём назвали бы
        # новому животному кличку старого
        tracker = IdentificationTracker()
        tracker.vote(1, "a1")
        tracker.forget(1)
        assert tracker.votes(1) == 0


class TestModelOdnaNaDveKamery:
    """
    Экземпляр модели один на все камеры, и с двумя это перестало быть
    безобидным: потоки камер независимы, обе видят животное в один и тот
    же момент и в один и тот же момент просят вектор.
    """

    def test_model_sozdayotsya_odin_raz(self):
        """
        Проверяется НАСТОЯЩИЙ `_ensure_loaded`, а не его пересказ.

        Первая версия этой проверки подменяла метод собственной копией
        с собственным замком — и проходила, даже когда замок из рабочего
        кода убирали совсем. Проверка сама себя и проверяла.

        Поэтому timm и torch подменяются на заглушки, а метод остаётся
        тот самый. Заглушка создаётся медленно нарочно: без задержки обе
        камеры успевали бы отработать по очереди и гонки не случилось бы
        никогда.
        """
        import sys
        import threading
        import types
        from cv_service.embedder import Embedder

        made = []

        def create_model(name, pretrained=False, num_classes=0):
            made.append(name)
            time.sleep(0.05)
            return types.SimpleNamespace(eval=lambda: None)

        fake_timm = types.ModuleType("timm")
        fake_timm.create_model = create_model
        fake_timm.data = types.SimpleNamespace(
            resolve_data_config=lambda *a, **k: {},
            create_transform=lambda **k: (lambda image: image),
        )

        fake_torch = types.ModuleType("torch")
        fake_torch.set_num_threads = lambda n: None

        saved = {name: sys.modules.get(name) for name in ("timm", "torch")}
        sys.modules["timm"] = fake_timm
        sys.modules["torch"] = fake_torch
        try:
            embedder = Embedder(name="проверочная")
            started = threading.Barrier(2)

            def load():
                started.wait()
                embedder._ensure_loaded()

            threads = [threading.Thread(target=load) for _ in range(2)]
            for one in threads:
                one.start()
            for one in threads:
                one.join()
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        # Без замка обе камеры не находят модель и обе начинают её
        # создавать: семьсот мегабайт дважды, а при первом запуске ещё и
        # скачивание дважды
        assert made == ["проверочная"]

    def test_model_vystavlyaetsya_posledney(self):
        """
        Порядок присваивания, а не мелочь.

        Готовность определяют по `_model`. Выставить её раньше, чем
        `_torch` и `_transform`, значит пустить соседнюю камеру в
        наполовину собранный объект — и получить падение там, где камера
        одна работала годами.
        """
        import inspect
        from cv_service.embedder import Embedder

        body = inspect.getsource(Embedder._ensure_loaded)
        assert body.index("self._torch = torch") < body.index("self._model = model")
        assert body.index("self._transform =") < body.index("self._model = model")


@patch("cv_service.main.fetch_animal_names", return_value={"a1": "Зорька"})
@patch("cv_service.main.identify")
def test_perepros_ne_daet_odnu_klichku_dvoim(mock_match, _names):
    """
    Голосование идёт мимо общей раздачи — и способно само проделать дыру
    в правиле «одна кличка — один трек».

    Два спорных трека с одним и тем же ближайшим кандидатом набирают
    голоса независимо друг от друга. Без проверки занятости оба получат
    одну кличку в одном кадре, то есть ровно то невозможное состояние,
    ради которого раздача и переписывалась.
    """
    from cv_service.main import _identify_crops

    # Оба кропа: два кандидата вплотную, спор гарантирован
    mock_match.return_value = Match(
        candidates=(("a1", 0.20), ("a2", 0.21)), ambiguous=True, candidate="a1"
    )

    tracker = IdentificationTracker()
    # По одному голосу уже есть: следующий станет вторым и решающим
    tracker.vote(1, "a1")
    tracker.vote(2, "a1")

    names, animals = {}, {}
    crops = [
        BestCrop(track_id=1, image=_frame(80, 80), confidence=0.9,
                 area=40_000.0, last_seen_at=0.0),
        BestCrop(track_id=2, image=_frame(80, 80), confidence=0.9,
                 area=40_000.0, last_seen_at=0.0),
    ]

    _identify_crops(
        MagicMock(), "farm-1", crops, MagicMock(), tracker, names, animals,
    )

    названы = [t for t, a in animals.items() if a == "a1"]
    assert len(названы) <= 1, "одна кличка досталась двум трекам"
