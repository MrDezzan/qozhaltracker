import pytest

from cv_service import activity
from cv_service.detector import Detection


def at(x, y, track_id=1, cls="cow"):
    """Животное, стоящее точкой опоры в (x, y)."""
    return Detection(track_id=track_id, class_name=cls, confidence=0.9,
                     bbox=(x - 100.0, y - 200.0, x + 100.0, y))


# Половина сантиметра на пиксель: метр — это двести пикселей
SCALE = 0.5
STEP = activity.MIN_INTERVAL_S


class TestFootPoint:
    def test_beryot_seredinu_nizhney_grani(self):
        # Не центр рамки: он уезжает вверх, когда животное поднимает
        # голову, и добавляет метры на ровном месте
        point = activity.foot_point(Detection(1, "cow", 0.9, (100.0, 200.0, 300.0, 600.0)))
        assert point == (200.0, 600.0)


class TestPath:
    def test_schitaet_proydennoe(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.add([at(400, 500)], STEP)       # 400 px = 200 см = 2 м
        meters, steps, _ = tracker.take(1)
        assert meters == 2.0
        assert steps == 1

    def test_drozhanie_ramki_ne_stanovitsya_kilometrami(self):
        # Главная ловушка. Пара пикселей дрожи на кадр за сутки даёт
        # «корова прошла шесть километров», простояв день в углу
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        now = 0.0
        tracker.add([at(0, 500)], now)
        for i in range(1, 200):
            now += STEP
            tracker.add([at(2 if i % 2 else 0, 500)], now)
        meters, steps, _ = tracker.take(1)
        assert meters == 0.0
        assert steps == 0

    def test_podmena_treka_ne_dayot_ryvka(self):
        # Трекер перенёс номер на другое животное: точка опоры прыгнула
        # через полкадра. Это не двадцать метров пути
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.add([at(4000, 500)], STEP)
        meters, steps, _ = tracker.take(1)
        assert meters == 0.0
        assert steps == 0

    def test_uhod_iz_kadra_ne_schitaetsya_pryamoy(self):
        # Между «где было» и «где появилось» животное шло вне кадра.
        # Прямая между точками — не его путь
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.add([at(400, 500)], activity.MAX_GAP_S + 1)
        meters, _, _ = tracker.take(1)
        assert meters == 0.0

    def test_posle_pereryva_schet_prodolzhaetsya(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.add([at(400, 500)], activity.MAX_GAP_S + 1)   # разрыв, не считаем
        tracker.add([at(800, 500)], activity.MAX_GAP_S + 1 + STEP)
        meters, steps, _ = tracker.take(1)
        assert meters == 2.0
        assert steps == 1

    def test_sosednie_kadry_ne_sravnivayutsya(self):
        # Между двумя соседними кадрами животное не успевает сдвинуться
        # заметнее дрожания рамки
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.add([at(400, 500)], STEP / 4)
        meters, _, _ = tracker.take(1)
        assert meters == 0.0

    def test_masshtab_kamery_menyaet_metry(self):
        близко = activity.ActivityTracker(cm_per_pixel=1.0)
        далеко = activity.ActivityTracker(cm_per_pixel=0.25)
        for tracker in (близко, далеко):
            tracker.add([at(0, 500)], 0.0)
            tracker.add([at(400, 500)], STEP)
        assert близко.take(1)[0] == 4.0
        assert далеко.take(1)[0] == 1.0

    def test_lyudi_ne_uchityvayutsya(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500, cls="person")], 0.0)
        tracker.add([at(400, 500, cls="person")], STEP)
        assert tracker.take(1) is None

    def test_neskolko_zhivotnykh_ne_smeshivayutsya(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500, 1), at(0, 900, 2)], 0.0)
        tracker.add([at(400, 500, 1), at(0, 900, 2)], STEP)
        assert tracker.take(1)[0] == 2.0
        assert tracker.take(2)[0] == 0.0

    def test_vremya_v_kadre(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 100.0)
        tracker.add([at(400, 500)], 100.0 + STEP)
        _, _, seconds = tracker.take(1)
        assert seconds == pytest.approx(STEP)

    def test_zabytyy_trek_ne_otdayotsya(self):
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        tracker.forget(1)
        assert tracker.take(1) is None

    def test_vzyatyy_trek_ne_otdayotsya_dvazhdy(self):
        # Иначе один визит попал бы в суточную сводку дважды
        tracker = activity.ActivityTracker(cm_per_pixel=SCALE)
        tracker.add([at(0, 500)], 0.0)
        assert tracker.take(1) is not None
        assert tracker.take(1) is None


class TestDescribe:
    def test_stroka_dlya_zhurnala(self):
        text = activity.describe(150.0, 600.0)
        assert "150" in text and "10" in text
