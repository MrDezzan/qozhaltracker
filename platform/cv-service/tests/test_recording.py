import pytest

from cv_service import recording
from cv_service.detector import Detection


def subject(track_id=1, bbox=(400.0, 300.0, 800.0, 700.0), conf=0.9, cls="cow"):
    return Detection(track_id=track_id, class_name=cls, confidence=conf, bbox=bbox)


W, H = 1920, 1080


class TestPickSingleSubject:
    def test_beryot_odinokoe_zhivotnoe(self):
        assert recording.pick_single_subject([subject()], W, H) is not None

    def test_dvoe_v_kadre_ne_pishutsya(self):
        # Главная защита всего режима. Двое рядом — и половина эталонов
        # достанется соседу, причём молча: счётчик покажет успех
        pair = [subject(1), subject(2, bbox=(900.0, 300.0, 1300.0, 700.0))]
        assert recording.pick_single_subject(pair, W, H) is None

    def test_chelovek_ryadom_ne_meshaet(self):
        # Человек не подопечный ни в каком смысле: он ведёт животное и
        # обязан быть в кадре. Считать его вторым животным нельзя
        with_handler = [subject(), Detection(2, "person", 0.9, (100.0, 200.0, 300.0, 900.0))]
        assert recording.pick_single_subject(with_handler, W, H) is not None

    def test_u_kraya_ne_pishem(self):
        # Срезанный силуэт даёт вектор, под который потом подходит кто угодно
        at_edge = subject(bbox=(5.0, 300.0, 405.0, 700.0))
        assert recording.pick_single_subject([at_edge], W, H) is None

    def test_daleko_ne_pishem(self):
        small = subject(bbox=(800.0, 400.0, 900.0, 500.0))
        assert recording.pick_single_subject([small], W, H) is None

    def test_neuverennoe_ne_pishem(self):
        assert recording.pick_single_subject([subject(conf=0.3)], W, H) is None

    def test_pustoy_kadr(self):
        assert recording.pick_single_subject([], W, H) is None


class TestNewAngle:
    def test_pervyy_kadr_beryotsya_vsegda(self):
        assert recording.is_new_angle([1.0, 0.0, 0.0], [])

    def test_tot_zhe_kadr_ne_beryotsya(self):
        # Иначе двенадцать эталонов набираются за две секунды неподвижного
        # стояния, животное «записано», а узнаётся только в одной позе
        same = [1.0, 0.0, 0.0]
        assert not recording.is_new_angle(same, [same])

    def test_drugoy_rakurs_beryotsya(self):
        assert recording.is_new_angle([0.0, 1.0, 0.0], [[1.0, 0.0, 0.0]])

    def test_pokhozhiy_no_ne_tot_zhe(self):
        # Небольшое шевеление — тот же ракурс. Порог должен его отсечь
        assert not recording.is_new_angle([1.0, 0.02, 0.0], [[1.0, 0.0, 0.0]])

    def test_sravnivaetsya_so_vsemi_zapisannymi(self):
        collected = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        assert not recording.is_new_angle([0.0, 1.0, 0.001], collected)
        assert recording.is_new_angle([0.0, 0.0, 1.0], collected)


class TestCosineDistance:
    def test_odinakovye_dayut_nol(self):
        assert recording.cosine_distance([1.0, 2.0], [1.0, 2.0]) == pytest.approx(0.0, abs=1e-9)

    def test_dlina_ne_vliyaet(self):
        # Вектор той же формы, но длиннее — это тот же ракурс
        assert recording.cosine_distance([1.0, 0.0], [5.0, 0.0]) == pytest.approx(0.0, abs=1e-9)

    def test_nulevoy_vektor_ne_lomaet(self):
        assert recording.cosine_distance([0.0, 0.0], [1.0, 0.0]) == 1.0


class TestProgress:
    def test_ne_chashche_zadannogo(self):
        progress = recording.RecordingProgress(session_id="s")
        assert progress.accepts(0.0)
        progress.remember([1.0], 10.0)
        assert not progress.accepts(10.1)
        assert progress.accepts(10.0 + recording.MIN_INTERVAL_S)


class TestParseSession:
    def test_razbiraet_stroku(self):
        session = recording.parse_session(
            {"id": "s1", "animal_id": "a1", "label": "Зорька", "captured": 3, "needed": 12}
        )
        assert session is not None
        assert session.label == "Зорька"
        assert session.captured == 3

    def test_pustaya_stroka(self):
        assert recording.parse_session(None) is None

    def test_bityi_ryad_ne_ronyaet(self):
        assert recording.parse_session({"id": "s1"}) is None


class TestWatcher:
    def test_oshibka_seti_ne_teryaet_tekushchiy_seans(self):
        # Иначе на каждом обрыве связи запись бы обрывалась, а человек в
        # это время ведёт животное мимо камеры и ничего не знает
        rows = [{"id": "s1", "animal_id": "a1", "label": "Зорька", "captured": 1, "needed": 12}]

        def fetch():
            if rows:
                return rows[0]
            raise RuntimeError("сеть недоступна")

        watcher = recording.RecordingWatcher(fetch)
        assert watcher.refresh() is not None
        rows.clear()
        assert watcher.refresh() is not None

    def test_zakonchennaya_zapis_ischezaet(self):
        answers = [{"id": "s1", "animal_id": "a1", "label": "Зорька", "captured": 1, "needed": 12}, None]
        watcher = recording.RecordingWatcher(lambda: answers.pop(0))
        assert watcher.refresh() is not None
        assert watcher.refresh() is None


class TestDescribe:
    def test_bez_seansa(self):
        assert "не идёт" in recording.describe(None)

    def test_s_seansom_vidno_skolko(self):
        session = recording.RecordingSession(
            "s", "a", "Зорька", captured=3, needed=12, per_camera=6, mine=2
        )
        text = recording.describe(session)
        assert "Зорька" in text and "2" in text and "6" in text


class TestWhyNot:
    """
    Причина отказа — то, что человек у камеры видит вместо молчащего
    счётчика. Молчание здесь хуже любой из этих строк.
    """

    def test_godnyy_kadr_bez_prichiny(self):
        assert recording.why_not([subject()], W, H) == ""

    def test_pustoy_kadr(self):
        assert "не вижу" in recording.why_not([], W, H)

    def test_dvoe_v_kadre(self):
        pair = [subject(1), subject(2, bbox=(900.0, 300.0, 1300.0, 700.0))]
        assert "одно" in recording.why_not(pair, W, H)

    def test_daleko(self):
        small = subject(bbox=(800.0, 400.0, 900.0, 500.0))
        assert "ближе" in recording.why_not([small], W, H)

    def test_neuverenno(self):
        assert "света" in recording.why_not([subject(conf=0.3)], W, H)

    def test_u_bokovogo_kraya(self):
        at_edge = subject(bbox=(5.0, 300.0, 405.0, 700.0))
        assert "края" in recording.why_not([at_edge], W, H)


class TestVerticalCropIsAllowed:
    """
    Кадр, срезанный сверху или снизу, годится — и это главное, что
    чинилось. Человек перед ноутбуком почти всегда обрезан по нижнему
    краю, коровы под потолочной камерой — тоже. Прежняя проверка отбивала
    все четыре стороны, счётчик стоял на нуле, и причина нигде не
    появлялась.
    """

    def test_srezan_snizu_beryotsya(self):
        cut = subject(bbox=(700.0, 300.0, 1100.0, float(H)))
        assert recording.pick_single_subject([cut], W, H) is not None

    def test_srezan_sverkhu_beryotsya(self):
        cut = subject(bbox=(700.0, 0.0, 1100.0, 500.0))
        assert recording.pick_single_subject([cut], W, H) is not None

    def test_srezan_sboku_ne_beryotsya(self):
        # Сбоку кадр режет вдоль: теряется голова или круп, а именно они
        # отличают одну особь от другой
        cut = subject(bbox=(0.0, 300.0, 400.0, 700.0))
        assert recording.pick_single_subject([cut], W, H) is None


class TestHintOnlyOnChange:
    def test_odna_i_ta_zhe_prichina_ne_povtoryaetsya(self):
        # Иначе в базу писалось бы одно и то же по десять раз в секунду
        progress = recording.RecordingProgress(session_id="s")
        assert progress.hint_changed("далеко")
        assert not progress.hint_changed("далеко")
        assert progress.hint_changed("")


class TestOtherCamera:
    """
    Запись начата на одной камере, человек стоит перед другой. Раньше
    устройство молчало: сессии по своей камере нет — значит, ничего не
    происходит. Человек при этом ждал у камеры, что счётчик пойдёт.
    """

    def test_chuzhaya_kamera_ne_stanovitsya_seansom(self):
        row = {"__other_camera__": True, "label": "Зорька"}
        assert recording.is_other_camera(row)
        assert recording.parse_session(row) is None

    def test_svoya_kamera_razbiraetsya_kak_obychno(self):
        row = {"id": "s1", "animal_id": "a1", "label": "Зорька", "captured": 2, "needed": 12}
        assert not recording.is_other_camera(row)
        assert recording.parse_session(row) is not None

    def test_preduprezhdenie_odno_na_seans(self, capsys):
        # Иначе строка печаталась бы каждые две секунды и забила бы журнал
        watcher = recording.RecordingWatcher(
            lambda: {"__other_camera__": True, "label": "Зорька"}
        )
        watcher.refresh()
        watcher.refresh()
        assert capsys.readouterr().out.count("без этой камеры") == 1


class TestPeriodicReport:
    def test_otchyot_ne_chashche_zadannogo(self):
        progress = recording.RecordingProgress(session_id="s")
        assert progress.due_to_report(100.0)
        assert not progress.due_to_report(105.0)
        assert progress.due_to_report(111.0)


class TestTargetAboveNeeded:
    """
    Человеку показывается needed, набирается target. Разница нужна,
    чтобы узнавание было надёжнее в разных положениях, но человек не
    ждал у камеры лишние полминуты ради того, что ему безразлично.
    """

    def test_target_razbiraetsya(self):
        session = recording.parse_session(
            {"id": "s", "animal_id": "a", "label": "Зорька",
             "captured": 3, "needed": 12, "target": 20}
        )
        assert session.needed == 12
        assert session.target == 20

    def test_bez_target_beryotsya_razumnoe(self):
        # Старая база без колонки не должна ронять устройство
        session = recording.parse_session(
            {"id": "s", "animal_id": "a", "label": "Зорька",
             "captured": 3, "needed": 12}
        )
        assert session.target >= session.needed

    def test_v_zhurnale_vidno_svoyo_i_obshchee(self):
        # При двух камерах общего числа мало: оно растёт, даже когда эта
        # камера уже замолчала, набрав свою квоту. Своё число — то, что
        # объясняет молчание
        session = recording.RecordingSession(
            "s", "a", "Зорька", captured=9, needed=12, target=20,
            per_camera=12, mine=4,
        )
        text = recording.describe(session)
        assert "4" in text and "12" in text and "9" in text


class TestAwaitingView:
    def test_zhdyomyy_rakurs_razbiraetsya(self):
        session = recording.parse_session(
            {"id": "s", "animal_id": "a", "label": "Зорька", "captured": 3,
             "needed": 12, "target": 20, "awaiting_view": "side_b"}
        )
        assert session.awaiting_view == "side_b"

    def test_bez_rakursov_pole_pustoe(self):
        # Камера сверху: ракурсов не различает, ждать нечего
        session = recording.parse_session(
            {"id": "s", "animal_id": "a", "label": "Зорька", "captured": 3,
             "needed": 12, "target": 20}
        )
        assert session.awaiting_view is None

    def test_v_zhurnale_vidno_chego_zhdyom(self):
        session = recording.RecordingSession(
            "s", "a", "Зорька", 3, 12, 20, awaiting_view="front"
        )
        assert "front" in recording.describe(session)


class TestQuotaPoKameram:
    """
    Каждая камера набирает своё и молчит.

    Без квоты одна камера, стоящая удачнее, набрала бы весь сеанс сама, а
    вторая осталась бы ни с чем — то есть ровно та беда, ради которой
    запись и сделали общей на несколько камер.
    """

    def test_svoyo_chislo_beryotsya_iz_razbivki(self):
        session = recording.parse_session(
            {
                "id": "s", "animal_id": "a", "label": "Зорька",
                "captured": 9, "needed": 12, "per_camera": 12,
                "captured_by": {"верх": 5, "бок": 4},
            },
            camera_id="бок",
        )
        assert session.mine == 4
        assert session.captured == 9

    def test_chuzhaya_kamera_ne_zaschityvaetsya_sebe(self):
        session = recording.parse_session(
            {
                "id": "s", "animal_id": "a", "label": "Зорька",
                "captured": 9, "needed": 12, "per_camera": 12,
                "captured_by": {"верх": 9},
            },
            camera_id="бок",
        )
        assert session.mine == 0
        assert not session.quota_full

    def test_kvota_nabrana_kogda_svoyo_dostignuto(self):
        session = recording.RecordingSession(
            "s", "a", "Зорька", captured=20, needed=12, per_camera=12, mine=12
        )
        assert session.quota_full

    def test_obshchee_chislo_ne_zakryvaet_kvotu(self):
        # Ловушка: всего набрано больше нужного, но всё — чужой камерой.
        # Считать свою квоту набранной означало бы не записать эту камеру
        # вовсе, а именно она потом будет узнавать
        session = recording.RecordingSession(
            "s", "a", "Зорька", captured=24, needed=12, per_camera=12, mine=3
        )
        assert not session.quota_full

    def test_staraya_baza_bez_razbivki_schitaet_vsyo_svoim(self):
        # Одна камера на сеанс — значит, всё набранное её
        session = recording.parse_session(
            {"id": "s", "animal_id": "a", "label": "Зорька",
             "captured": 7, "needed": 12},
            camera_id="бок",
        )
        assert session.mine == 7
