"""
Определение ракурса по форме рамки и направлению движения.

Проверяется на выдуманных траекториях: камеры и модели тут нет и не
надо. Каждый тест — это ответ на вопрос «что система увидит, если
животное сделает вот так».
"""

import pytest

from cv_service import views


def side_bbox(x: float, y: float = 600.0, length: float = 400.0, height: float = 200.0):
    """Животное сбоку: рамка вытянута вдоль."""
    return (x, y - height, x + length, y)


def head_on_bbox(x: float = 800.0, y: float = 600.0, size: float = 200.0):
    """Животное в лоб: рамка почти квадратная."""
    return (x, y - size, x + size * 1.1, y)


def walk(estimator, frames, track_id=1):
    """Прогоняет последовательность (время, рамка) и отдаёт последний ответ."""
    answer = None
    for at, bbox in frames:
        answer = estimator.observe(track_id, bbox, at)
    return answer


class TestFlanks:
    def test_dvizhenie_vpravo_odin_bok(self):
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, side_bbox(300 + t * 60)) for t in range(12)]
        assert walk(estimator, frames) == views.SIDE_A

    def test_dvizhenie_vlevo_drugoy_bok(self):
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, side_bbox(1000 - t * 60)) for t in range(12)]
        assert walk(estimator, frames) == views.SIDE_B

    def test_boka_razlichayutsya(self):
        """
        Главное, ради чего всё затевалось: два прохода в разные стороны
        должны дать РАЗНЫЕ ракурсы. Иначе запись соберёт один и тот же
        бок дважды, а человек будет уверен, что записал оба.
        """
        right = views.ViewEstimator()
        left = views.ViewEstimator()
        assert walk(right, [(t * 0.2, side_bbox(300 + t * 60)) for t in range(12)]) != walk(
            left, [(t * 0.2, side_bbox(1000 - t * 60)) for t in range(12)]
        )

    def test_stoyashchee_bokom_ne_zaschityvaetsya(self):
        # Вытянутое, но неподвижное: бок это или тень на стене — по
        # одной форме сказать нельзя
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, side_bbox(500)) for t in range(12)]
        assert walk(estimator, frames) is None


class TestFrontAndRear:
    def test_priblizhaetsya_eto_pered(self):
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, head_on_bbox(size=150 + t * 18)) for t in range(12)]
        assert walk(estimator, frames) == views.FRONT

    def test_udalyaetsya_eto_zad(self):
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, head_on_bbox(size=360 - t * 18)) for t in range(12)]
        assert walk(estimator, frames) == views.REAR

    def test_stoyashchee_v_lob_ne_zaschityvaetsya(self):
        estimator = views.ViewEstimator()
        frames = [(t * 0.2, head_on_bbox(size=200)) for t in range(12)]
        assert walk(estimator, frames) is None


class TestDeadZone:
    def test_vpoloborota_ne_otnositsya_nikuda(self):
        """
        Мёртвая зона между порогами. Животное вполоборота — не бок и не
        перед; назвать его любым из двух значило бы записать эталон под
        неверной пометкой, а пометка потом участвует в узнавании.

        Животное здесь И едет вбок, И растёт — то есть годится под оба
        правила сразу. Без мёртвой зоны любое из них дало бы уверенный
        ответ. Первая версия этого теста брала неподвижное животное
        неизменного размера и потому зеленела сама собой: убери мёртвую
        зону — и она всё равно проходила.
        """
        estimator = views.ViewEstimator()
        frames = []
        for t in range(12):
            # Отношение держим 1.5 — ровно между COMPACT_RATIO (1.3) и
            # SIDE_RATIO (1.8), — а размер и положение меняем
            height = 200.0 + t * 14
            width = height * 1.5
            x = 300.0 + t * 60
            frames.append((t * 0.2, (x, 600.0 - height, x + width, 600.0)))

        assert walk(estimator, frames) is None


class TestHold:
    def test_odin_kadr_nichego_ne_znachit(self):
        # Животное мотнуло головой, трекер дёрнул рамку — это не ракурс
        estimator = views.ViewEstimator()
        assert estimator.observe(1, side_bbox(300), 0.0) is None
        assert estimator.observe(1, side_bbox(400), 0.3) is None

    def test_rakurs_obyavlyaetsya_ne_ranshe_poltory_sekund(self):
        estimator = views.ViewEstimator()
        answers = []
        for t in range(12):
            answers.append(estimator.observe(1, side_bbox(300 + t * 60), t * 0.2))

        # До полутора секунд — молчание
        assert all(a is None for a in answers[:7])
        assert answers[-1] == views.SIDE_A

    def test_razvorot_otbiraet_uzhe_obyavlennyy_rakurs(self):
        """
        Ракурс был подтверждён, животное развернулось — подтверждение
        обязано пропасть, а не тянуться по инерции.

        Проверяется именно ПОСЛЕ подтверждения: если проверять до, тест
        зеленел бы сам собой — там ещё нечему пропадать.
        """
        estimator = views.ViewEstimator()
        for t in range(12):
            confirmed = estimator.observe(1, side_bbox(300 + t * 60), t * 0.2)
        assert confirmed == views.SIDE_A, "ракурс должен был подтвердиться"

        # Пошло обратно
        x = 300 + 11 * 60
        for step in range(1, 5):
            answer = estimator.observe(1, side_bbox(x - step * 60), 2.2 + step * 0.2)
        assert answer is None, "после разворота прежний ракурс держаться не должен"


class TestGap:
    def test_posle_propazhi_rakurs_nado_podtverzhdat_zanovo(self):
        """
        Животное скрылось за столбом и появилось дальше. Пока его не
        было, оно могло развернуться — и первый же кадр после пропажи не
        имеет права считаться продолжением прежнего наблюдения.

        Без сброса выходит так: ракурс был подтверждён до пропажи, после
        неё направление внешне то же, отсчёт выдержки тянется со старого
        времени — и система объявляет ракурс МГНОВЕННО, по одному кадру,
        да ещё опираясь на перемещение, которого не видела.

        Тест ловит именно это, поэтому направление до и после пропажи
        одинаковое. Первая версия брала разные направления — и зеленела
        сама собой: отсчёт там сбрасывался из-за смены направления, а не
        из-за пропажи.
        """
        estimator = views.ViewEstimator()

        confirmed = None
        for step in range(12):
            confirmed = estimator.observe(1, side_bbox(300 + step * 60), step * 0.2)
        assert confirmed == views.SIDE_A, "ракурс должен был подтвердиться до пропажи"

        # Пропало на секунду и возникло сильно правее, идя в ту же сторону
        first_after = estimator.observe(1, side_bbox(2000), 3.2)
        assert first_after is None, (
            "первый кадр после пропажи не может подтверждать ракурс"
        )

    def test_posle_razryva_otschyot_nachinaetsya_zanovo(self):
        """
        Между уходом и возвращением животное могло развернуться. Склеив
        точки через разрыв, система объявила бы ракурс, которого никто
        не показывал.

        Проверяем не только первый кадр после разрыва (он был бы None и
        просто потому, что точка одна), но и целую секунду движения:
        подтверждения не должно быть, пока не наберутся свои полторы.
        """
        estimator = views.ViewEstimator()
        for t in range(12):
            confirmed = estimator.observe(1, side_bbox(300 + t * 60), t * 0.2)
        assert confirmed == views.SIDE_A

        # Пропало на десять секунд и вернулось, идя в ту же сторону
        base = 12.0
        answers = []
        for step in range(6):
            answers.append(
                estimator.observe(1, side_bbox(300 + step * 60), base + step * 0.2)
            )

        # Первая секунда после возвращения — молчание, отсчёт с нуля
        assert all(a is None for a in answers[:5])


class TestSeveralAnimals:
    def test_treki_ne_smeshivayutsya(self):
        # Двое идут навстречу друг другу. Общее направление было бы
        # бессмыслицей
        estimator = views.ViewEstimator()
        for t in range(12):
            estimator.observe(1, side_bbox(300 + t * 60), t * 0.2)
            estimator.observe(2, side_bbox(1400 - t * 60, y=900.0), t * 0.2)

        assert estimator.observe(1, side_bbox(1020), 2.4) == views.SIDE_A
        assert estimator.observe(2, side_bbox(680, y=900.0), 2.4) == views.SIDE_B

    def test_zabytyy_trek_ne_zanimaet_pamyat(self):
        estimator = views.ViewEstimator()
        estimator.observe(7, side_bbox(300), 0.0)
        assert 7 in estimator.tracked()
        estimator.forget(7)
        assert 7 not in estimator.tracked()


class TestGuessEdges:
    def test_nulevaya_vysota_ne_ronyaet(self):
        point = views._Point(at=0.0, x=0.0, y=0.0, width=100.0, height=0.0)
        later = views._Point(at=1.0, x=100.0, y=0.0, width=100.0, height=0.0)
        assert views.guess(point, later) is None

    def test_odinakovoe_vremya_ne_ronyaet(self):
        point = views._Point(at=1.0, x=0.0, y=0.0, width=400.0, height=200.0)
        assert views.guess(point, point) is None


class TestOrderForCamera:
    def test_sboku_boka_pervymi(self):
        # Бока определяются надёжнее и дают больше для узнавания. Бросят
        # запись на середине — останется самое ценное
        order = views.order_for("side")
        assert order[:2] == (views.SIDE_A, views.SIDE_B)

    def test_u_kormushki_pered_pervym(self):
        order = views.order_for("side", has_feeder_zone=True)
        assert order[0] == views.FRONT

    def test_sverkhu_rakursov_ne_prosim(self):
        # Оттуда всегда одна и та же спина. Просить бок значило бы
        # заставить человека крутить животное впустую
        assert views.order_for("overhead") == ()
        assert views.order_for("overhead", has_feeder_zone=True) == ()

    def test_vse_chetyre_rakursa_prisutstvuyut(self):
        for order in (views.order_for("side"), views.order_for("side", True)):
            assert set(order) == set(views.ALL_VIEWS)


class TestFeederView:
    def test_stoit_u_kormushki_eto_pered(self):
        assert views.feeder_view(inside_feeder=True, moving=False) == views.FRONT

    def test_idyot_znachit_dopushchenie_snimaetsya(self):
        # Подходя и отходя, животное показывает бока — их определяет
        # обычный способ, а допущение про морду больше не нужно
        assert views.feeder_view(inside_feeder=True, moving=True) is None

    def test_vne_zony_nichego_ne_vyvodim(self):
        assert views.feeder_view(inside_feeder=False, moving=False) is None


class TestTitles:
    def test_u_kazhdogo_rakursa_est_chelovecheskoe_nazvanie(self):
        for view in views.ALL_VIEWS:
            assert views.VIEW_TITLES[view]

    def test_nazvaniya_ne_govoryat_pro_levo_i_pravo(self):
        # Который бок левый, зависит от того, как повешена камера.
        # Система не должна утверждать то, чего не знает
        joined = " ".join(views.VIEW_TITLES.values()).lower()
        assert "лев" not in joined
        assert "прав" not in joined

