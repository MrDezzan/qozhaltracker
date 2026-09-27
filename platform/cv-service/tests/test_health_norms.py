"""
Нормы: своя и стадная. Этап 2 плана PLAN_POVEDENIE.md.

Метры и секунды у корма сами по себе почти ничего не значат: камера
видит кусок загона, остальное не учтено. Значат две вещи — сравнение
животного с самим собой в прошлые дни и сравнение с соседями сегодня.
"""

import pytest

from cv_service.health import (
    MIN_DAYS_FOR_BASELINE,
    MIN_SECONDS_VISIBLE,
    AnimalDay,
    herd_median,
    own_baseline,
    ratio,
)


def day(d="2026-08-18", meters=100.0, seconds=3600.0, feeder=600.0, water=3):
    return AnimalDay(
        animal_id="a1",
        day=d,
        meters=meters,
        seconds_visible=seconds,
        feeder_seconds=feeder,
        water_visits=water,
    )


class TestSvoyaNorma:
    def test_mediana_a_ne_srednee(self):
        """
        Один день, когда животное простояло у камеры весь день, сдвинул
        бы среднее так, что все остальные дни стали бы «ниже нормы».
        """
        days = [day(meters=m) for m in (100.0, 110.0, 105.0, 5000.0)]
        assert own_baseline(days, "meters") == 107.5

    def test_dvukh_dney_dlya_normy_malo(self):
        # По двум дням «норма» — это просто один из них, и любое
        # отклонение от неё случайно.
        #
        # Двойка написана числом, а не через MIN_DAYS_FOR_BASELINE - 1:
        # константа в обеих частях проверки означала бы, что число
        # сравнивают само с собой, и порог можно менять как угодно
        assert own_baseline([day(meters=100.0), day(meters=100.0)], "meters") is None

    def test_odnogo_dnya_tem_bolee_malo(self):
        assert own_baseline([day(meters=100.0)], "meters") is None

    def test_rovno_tri_dnya_uzhe_norma(self):
        days = [day(meters=m) for m in (100.0, 200.0, 300.0)]
        assert own_baseline(days, "meters") == 200.0

    def test_pustoy_spisok(self):
        assert own_baseline([], "meters") is None

    def test_norma_po_kormu_schitaetsya_tak_zhe(self):
        days = [day(feeder=f) for f in (600.0, 900.0, 1200.0)]
        assert own_baseline(days, "feeder_seconds") == 900.0


class TestStadnayaNorma:
    def test_mediana_po_stadu(self):
        rows = [day(meters=m) for m in (100.0, 200.0, 300.0)]
        assert herd_median(rows, "meters") == 200.0

    def test_odno_zhivotnoe_ne_stado(self):
        """
        Сравнивать животное с самим собой под видом стада нельзя:
        отношение всегда выйдет единицей, и просадка всего загона
        никогда не будет замечена.
        """
        assert herd_median([day()], "meters") is None

    def test_pustoe_stado(self):
        assert herd_median([], "meters") is None


class TestOtnoshenie:
    def test_schitaet_dolyu(self):
        assert ratio(50.0, 100.0) == 0.5

    def test_norma_nol_ne_lomaet(self):
        # Делить на ноль нельзя, а «в ноль раз меньше» — не число.
        # Такое животное просто не судим
        assert ratio(50.0, 0.0) is None

    def test_normy_net_otnosheniya_net(self):
        assert ratio(50.0, None) is None

    def test_nol_pri_zhivoy_norme_eto_nol_a_ne_molchanie(self):
        # Ноль метров при норме в шестьсот — самый сильный сигнал,
        # который вообще бывает. Превратить его в None значило бы
        # промолчать ровно там, где надо кричать
        assert ratio(0.0, 600.0) == 0.0


class TestVremyaVKadre:
    """
    Главная ловушка плана. Больная лежит в углу — метров ноль, секунд
    много. Не узнали — ноль и того, и другого. Различает их именно
    время в кадре.
    """

    def test_malo_vremeni_v_kadre_ne_dayot_suditb(self):
        assert not day(seconds=MIN_SECONDS_VISIBLE - 1).can_judge_movement

    def test_dostatochno_vremeni_dayot(self):
        assert day(seconds=MIN_SECONDS_VISIBLE).can_judge_movement

    def test_lezhachaya_korova_sudima(self):
        # Ноль метров при полном часе в кадре — это про животное
        assert day(meters=0.0, seconds=3600.0).can_judge_movement

    def test_neuznannaya_korova_ne_sudima(self):
        # Те же ноль метров, но её просто не видели
        assert not day(meters=0.0, seconds=0.0).can_judge_movement


class TestNormaStroitsyaTolkoPoGodnym:
    def test_negodnye_sutki_ne_zanizhayut_normu(self):
        """
        День, когда камера лежала, не должен ни поднимать тревогу, ни
        занижать норму, с которой сравнивают следующие дни. Иначе одна
        поломка портит неделю вперёд.
        """
        good = [day(d="2026-08-1%d" % i, meters=600.0) for i in (1, 2, 3)]
        broken = day(d="2026-08-14", meters=0.0, seconds=0.0)

        usable = {"2026-08-11", "2026-08-12", "2026-08-13"}
        kept = [one for one in good + [broken] if one.day in usable]

        assert own_baseline(kept, "meters") == 600.0

    def test_odin_slomannyy_den_mediana_perezhivayet(self):
        # Медиана затем и выбрана: один провал из четырёх её не двигает.
        # Отбор годных суток нужен не ради этого случая
        days = [day(meters=600.0) for _ in range(3)] + [day(meters=0.0)]
        assert own_baseline(days, "meters") == 600.0

    def test_polnedeli_polomki_normu_uzhe_portyat(self):
        """
        Вот ради чего отбор.

        Камера, лежавшая три дня из шести, утягивает медиану к нулю. С
        такой нормой ЛЮБОЙ следующий день окажется «выше обычного», и
        по-настоящему больное животное система назовёт бодрым.
        """
        days = [day(meters=600.0) for _ in range(3)] + [
            day(meters=0.0) for _ in range(3)
        ]
        assert own_baseline(days, "meters") < 600.0
