"""
Годность суток. Этап 1 плана PLAN_POVEDENIE.md.

Стоит первым не потому, что важнее корма, а потому, что без него любая
следующая проверка врёт хором: камера сутки не работала — у всех
животных нули — двести тревог разом.

Молчание здесь означает «не знаем», а не «всё хорошо». Разница видна в
том, что негодные сутки не участвуют НИ в проверке, НИ в норме: день,
когда камера лежала, не должен ни поднимать тревогу, ни занижать норму,
с которой сравнивают следующие дни.
"""

from cv_service.health import (
    MIN_ALIVE_HOURS,
    CameraDay,
    day_source,
    usable_days,
)


def alive(camera="cam", day="2026-08-18", hours=24.0, feeder=False):
    return CameraDay(camera_id=camera, day=day, alive_hours=hours, has_feeder=feeder)


class TestOdnaKamera:
    def test_sutki_polnoy_raboty_godyatsya(self):
        assert "2026-08-18" in usable_days([alive()]).movement

    def test_sutki_prostoya_ne_godyatsya(self):
        assert usable_days([alive(hours=0.0)]).movement == set()

    def test_granitsa_vklyuchitelno(self):
        # Ровно порог — годится. Иначе сутки, где камеру перезагрузили
        # ровно на границе, выпадали бы без всякой причины
        assert usable_days([alive(hours=MIN_ALIVE_HOURS)]).movement

    def test_chut_nizhe_granitsy_ne_goditsya(self):
        assert not usable_days([alive(hours=MIN_ALIVE_HOURS - 0.1)]).movement


class TestNeskolkoKamer:
    def test_zhivoy_odnoy_dostatochno_dlya_dvizheniya(self):
        # Путь считается со всех камер: одна лежала, вторая работала —
        # животное всё равно видели
        days = usable_days([
            alive(camera="верх", hours=0.0),
            alive(camera="бок", hours=24.0),
        ])
        assert "2026-08-18" in days.movement

    def test_bez_zhivykh_kamer_sutki_ne_goditsya(self):
        days = usable_days([
            alive(camera="верх", hours=1.0),
            alive(camera="бок", hours=2.0),
        ])
        assert days.movement == set()

    def test_chasy_raznykh_kamer_ne_skladyvayutsya(self):
        """
        Ловушка, которую легко не заметить.

        Две камеры по семь часов — это не четырнадцать часов наблюдения.
        Они работали ОДНОВРЕМЕННО и обе молчали одни и те же семнадцать
        часов. Сложение объявило бы такие сутки годными, и всё стадо,
        не попавшее в кадр ночью, оказалось бы вялым.
        """
        seven = MIN_ALIVE_HOURS - 5.0
        days = usable_days([
            alive(camera="верх", hours=seven),
            alive(camera="бок", hours=seven),
        ])
        assert days.movement == set()


class TestKormOtdelno:
    """
    Корм считается только с камер, где размечена кормушка. Живая камера
    над проходом ничего не говорит о том, ела ли корова.
    """

    def test_bez_kamery_s_kormushkoy_korm_ne_sudim(self):
        days = usable_days([alive(camera="проход", feeder=False)])
        assert days.movement
        assert days.feeding == set()

    def test_zhivaya_kamera_s_kormushkoy_daet_sutki(self):
        days = usable_days([alive(camera="стол", feeder=True)])
        assert days.feeding

    def test_lezhachaya_kamera_s_kormushkoy_ne_daet(self):
        # Здесь и была бы худшая ложная тревога: камера над кормовым
        # столом упала, и всё стадо «перестало есть»
        days = usable_days([
            alive(camera="проход", hours=24.0, feeder=False),
            alive(camera="стол", hours=0.0, feeder=True),
        ])
        assert days.movement
        assert days.feeding == set()


class TestRaznyeDni:
    def test_kazhdye_sutki_sudyatsya_otdelno(self):
        days = usable_days([
            alive(day="2026-08-16", hours=24.0),
            alive(day="2026-08-17", hours=0.0),
            alive(day="2026-08-18", hours=24.0),
        ])
        assert days.movement == {"2026-08-16", "2026-08-18"}

    def test_pustoy_spisok_nichego_ne_daet(self):
        days = usable_days([])
        assert days.movement == set()
        assert days.feeding == set()


class TestOtkudaVzyalis:
    """
    Человеку надо уметь ответить, почему система молчит про животное.
    «Не знаем» без причины — та же тишина, из-за которой раньше стоял
    счётчик записи.
    """

    def test_godnye_sutki_obyasnyayutsya(self):
        assert "камер" in day_source([alive()], "2026-08-18").lower()

    def test_negodnye_sutki_nazyvayut_prichinu(self):
        text = day_source([alive(hours=2.0)], "2026-08-18")
        assert "2" in text and "12" in text

    def test_sutki_bez_kamer_vovse(self):
        assert day_source([], "2026-08-18")
