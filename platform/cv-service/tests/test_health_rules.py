"""
Правила тревог. Этап 3 плана PLAN_POVEDENIE.md.

Здесь решается, о чём система заговорит. Цена ошибки несимметрична:
пропущенная больная корова — одна корова, а три ложные тревоги подряд —
человек перестаёт открывать раздел, и дальше пропущены все.
"""

import pytest

from cv_service.health import (
    HERD_TROUBLE_SHARE,
    LOW_RATIO,
    MIN_EMBEDDINGS_TO_JUDGE,
    AnimalDay,
    AnimalHistory,
    Finding,
    judge,
    judge_herd,
)


def days(*values, seconds=3600.0, feeder=600.0, meals=4, water=3, start=11):
    """Ряд суток с одинаковым временем в кадре и разными метрами."""
    return [
        AnimalDay(
            animal_id="a1",
            day="2026-08-%02d" % (start + i),
            meters=float(m),
            seconds_visible=seconds,
            feeder_seconds=feeder,
            feeder_visits=meals,
            water_visits=water,
        )
        for i, m in enumerate(values)
    ]


def history(
    recent,
    embeddings=12,
    usable_movement=None,
    usable_feeding=None,
    herd_share_low=0.0,
):
    all_days = [one.day for one in recent]
    return AnimalHistory(
        animal_id="a1",
        label="Зорька",
        days=recent,
        embeddings=embeddings,
        usable_movement=set(all_days if usable_movement is None else usable_movement),
        usable_feeding=set(all_days if usable_feeding is None else usable_feeding),
        herd_share_low=herd_share_low,
    )


def kinds(findings: list[Finding]) -> set[str]:
    return {one.kind for one in findings}


class TestOdinDenNeSchitaetsya:
    def test_odna_prosadka_dvizheniya_molchit(self):
        # День на день не приходится: жара, перегон, больше времени вне
        # кадра. Помечать это значит приучить не смотреть на пометки
        rows = days(600, 600, 600, 600, 200)
        assert judge(history(rows)) == []

    def test_dva_dnya_podryad_uzhe_trevoga(self):
        rows = days(600, 600, 600, 200, 200)
        assert "low_activity" in kinds(judge(history(rows)))

    def test_dva_dnya_no_ne_podryad_molchat(self):
        """
        Провал, бодрый день, провал — это не «два дня подряд». Между
        ними животное было в норме, а значит, речь о двух отдельных
        днях, каждый из которых сам по себе ничего не значит.
        """
        rows = days(600, 600, 200, 600, 200)
        assert "low_activity" not in kinds(judge(history(rows)))


class TestSochetanieVesitBolshe:
    def test_dvizhenie_i_korm_srazu_trevoga(self):
        # Мало двигалась — могла лежать в тени. Мало двигалась И мало
        # ела — это уже про животное, а не про погоду
        rows = days(600, 600, 600, 600, 200)
        rows[-1] = AnimalDay("a1", rows[-1].day, 200.0, 3600.0,
                             feeder_seconds=100.0, feeder_visits=4, water_visits=3)
        found = judge(history(rows))
        assert "low_both" in kinds(found)

    def test_sochetanie_dva_dnya_eto_srochno(self):
        rows = days(600, 600, 600, 200, 200)
        for i in (-1, -2):
            rows[i] = AnimalDay("a1", rows[i].day, 200.0, 3600.0,
                                feeder_seconds=100.0, feeder_visits=4, water_visits=3)
        found = [one for one in judge(history(rows)) if one.kind == "low_both"]
        assert found and found[0].severity == "danger"

    def test_sochetanie_ne_dubliruetsya_otdelnymi(self):
        # Иначе на одно животное придут три тревоги об одном и том же, и
        # человек будет разбирать список вместо того, чтобы идти в загон
        rows = days(600, 600, 600, 200, 200)
        for i in (-1, -2):
            rows[i] = AnimalDay("a1", rows[i].day, 200.0, 3600.0,
                                feeder_seconds=100.0, feeder_visits=4, water_visits=3)
        assert kinds(judge(history(rows))) == {"low_both"}


class TestNeVideli:
    def test_sutki_bez_vstrech_eto_svoya_trevoga(self):
        """
        Не «мало двигается». Животное могло уйти, застрять, лежать вне
        обзора — и это срочнее вялости.
        """
        rows = days(600, 600, 600, 600, 0)
        rows[-1] = AnimalDay("a1", rows[-1].day, 0.0, 0.0, feeder_seconds=0.0, water_visits=0)
        assert "not_seen" in kinds(judge(history(rows)))

    def test_ne_videli_ne_stanovitsya_vyalostyu(self):
        rows = days(600, 600, 600, 600, 0)
        rows[-1] = AnimalDay("a1", rows[-1].day, 0.0, 0.0, feeder_seconds=0.0, water_visits=0)
        assert "low_activity" not in kinds(judge(history(rows)))

    def test_dvoe_sutok_eto_srochno(self):
        rows = days(600, 600, 600, 0, 0)
        for i in (-1, -2):
            rows[i] = AnimalDay("a1", rows[i].day, 0.0, 0.0, feeder_seconds=0.0, water_visits=0)
        found = [one for one in judge(history(rows)) if one.kind == "not_seen"]
        assert found and found[0].severity == "danger"

    def test_redko_vidimoe_zhivotnoe_ne_propazha(self):
        """
        Животное, которое и раньше почти не попадало в кадр, не
        «пропало» — о нём просто никогда не было данных. Тревожить
        человека тут не о чем.
        """
        rows = [
            AnimalDay("a1", "2026-08-%02d" % (11 + i), 0.0, 0.0, feeder_seconds=0.0, water_visits=0)
            for i in range(5)
        ]
        assert judge(history(rows)) == []


class TestVoda:
    def test_sutki_bez_vody_srochno(self):
        rows = days(600, 600, 600, 600, 600)
        rows[-1] = AnimalDay("a1", rows[-1].day, 600.0, 3600.0, feeder_seconds=600.0, water_visits=0)
        found = [one for one in judge(history(rows)) if one.kind == "no_water"]
        assert found and found[0].severity == "danger"

    def test_bez_istorii_pitya_molchim(self):
        # Зоны поилки может не быть вовсе. Отсутствие данных не есть
        # отсутствие питья
        rows = [
            AnimalDay("a1", "2026-08-%02d" % (11 + i), 600.0, 3600.0, feeder_seconds=600.0, water_visits=0)
            for i in range(5)
        ]
        assert "no_water" not in kinds(judge(history(rows)))


class TestZashchitaOtLozhnykh:
    def test_prosevshee_stado_snimaet_lichnye_trevogi(self):
        # Жара, перегон, смена корма. Болезни у всех разом не бывает
        rows = days(600, 600, 600, 200, 200)
        assert judge(history(rows, herd_share_low=0.5)) == []

    def test_ploho_uznavaemoe_zhivotnoe_ne_sudim(self):
        # Его нули — это нули узнавания, а не поведения
        rows = days(600, 600, 600, 200, 200)
        assert judge(history(rows, embeddings=MIN_EMBEDDINGS_TO_JUDGE - 1)) == []

    def test_negodnye_sutki_ne_podnimayut_trevogu(self):
        # Камера лежала — у всех нули. Без этой проверки двести тревог
        # разом и конец доверию
        rows = days(600, 600, 600, 200, 200)
        usable = {one.day for one in rows[:-2]}
        assert judge(history(rows, usable_movement=usable)) == []

    def test_novoe_zhivotnoe_bez_normy_molchit(self):
        rows = days(200, 200)
        assert judge(history(rows)) == []


class TestVysokayaAktivnost:
    def test_bodraya_korova_ne_bolna(self):
        """
        В охоте активность наоборот растёт. Выдавать это за нездоровье
        нельзя — иначе система будет звать ветврача к здоровой корове
        ровно в тот день, когда её надо осеменять.
        """
        rows = days(600, 600, 600, 1800, 1800)
        assert kinds(judge(history(rows))) <= {"heat"}


class TestStado:
    def test_prosadka_stada_odna_trevoga_na_fermu(self):
        # Чинить надо загон, а не корову
        low = judge_herd(share_low=HERD_TROUBLE_SHARE, animals=30)
        assert low is not None and low.kind == "herd_low"

    def test_obychnyy_den_molchit(self):
        assert judge_herd(share_low=0.1, animals=30) is None

    def test_maloe_stado_ne_sudim(self):
        # На трёх головах «треть стада» — это одна корова, и она как раз
        # может быть больна
        assert judge_herd(share_low=1.0, animals=3) is None


class TestChisla:
    def test_v_trevoge_est_chem_proverit(self):
        """
        Вердикт без чисел нечем проверить, и первое же несогласие
        человека с системой кончается тем, что он ей не верит.
        """
        rows = days(600, 600, 600, 200, 200)
        found = judge(history(rows))[0]
        assert found.value == 200.0
        assert found.baseline == 600.0
        assert "Зорька" in found.title


class TestGranitsyPorogov:
    """
    Проверки, без которых пороги можно двигать как угодно.

    Прежние тесты брали 200 при норме 600 — это треть, она ниже любого
    разумного порога. Такой тест подтверждает, что система замечает
    провал, но ничего не говорит о том, ГДЕ проходит граница. Порог,
    который нельзя сломать тестом, не проверен.
    """

    def test_obychnyy_razbros_ne_trevoga(self):
        # 500 из 600 — это 83 %. Столько даёт обычный день: животное
        # больше времени провело вне кадра, было жарче, дольше стояло.
        # Помечать такое значит приучить не смотреть на пометки
        rows = days(600, 600, 600, 500, 500)
        assert judge(history(rows)) == []

    def test_chut_nizhe_poroga_uzhe_trevoga(self):
        # 0.66 нормы — ниже двух третей
        rows = days(600, 600, 600, 396, 396)
        assert "low_activity" in kinds(judge(history(rows)))

    def test_rovno_na_poroge_molchim(self):
        # Ровно две трети — ещё не «мало». Граница должна быть с одной
        # стороны определённой, иначе она не граница
        rows = days(600, 600, 600, 402, 402)
        assert judge(history(rows)) == []

    def test_nebolshoe_ozhivlenie_ne_okhota(self):
        # Полторы нормы — порог охоты. Двадцать процентов сверху бывают
        # просто от прохладного дня, и звать осеменатора по ним нельзя
        rows = days(600, 600, 600, 720, 720)
        assert judge(history(rows)) == []

    def test_vdvoe_bodree_uzhe_okhota(self):
        rows = days(600, 600, 600, 1200, 1200)
        assert "heat" in kinds(judge(history(rows)))


class TestZaslonkaUznavaniyaChislom:
    """
    Прежний тест брал `MIN_EMBEDDINGS_TO_JUDGE - 1`, то есть двигался
    вместе с порогом: поставь порог в ноль, и тест подставит минус
    единицу и снова пройдёт. Числа здесь написаны прямо.
    """

    def test_tri_etalona_malo(self):
        rows = days(600, 600, 600, 200, 200)
        assert judge(history(rows, embeddings=3)) == []

    def test_chetyre_etalona_uzhe_sudim(self):
        rows = days(600, 600, 600, 200, 200)
        assert judge(history(rows, embeddings=4)) != []

    def test_bez_etalonov_vovse_molchim(self):
        rows = days(600, 600, 600, 200, 200)
        assert judge(history(rows, embeddings=0)) == []


class TestNegodnyeSutkiPoObeim:
    def test_obe_kamery_lezhali_molchim(self):
        """
        Прежний тест закрывал только движение и оставлял корм годным —
        а значит, проверял не ту заслонку: до неё дело не доходило.

        Здесь обе камеры мертвы в последние сутки, и данные выглядят
        тревожно: ноль метров, ноль у корма, ноль воды. Ровно тот
        случай, ради которого заслонка и стоит: без неё это двести
        тревог разом.
        """
        rows = days(600, 600, 600, 600, 600)
        rows[-1] = AnimalDay("a1", rows[-1].day, 0.0, 3600.0, feeder_seconds=0.0, water_visits=0)

        dead = {one.day for one in rows[:-1]}
        assert judge(history(rows, usable_movement=dead, usable_feeding=dead)) == []

    def test_zhivaya_odna_kamera_sudit_svoyo(self):
        # Камера над кормовым столом упала, проходная работает. Про корм
        # молчим, про движение говорим: это разные камеры и разные
        # основания
        rows = days(600, 600, 600, 200, 200)
        rows[-1] = AnimalDay("a1", rows[-1].day, 200.0, 3600.0, feeder_seconds=0.0, water_visits=3)
        rows[-2] = AnimalDay("a1", rows[-2].day, 200.0, 3600.0, feeder_seconds=0.0, water_visits=3)

        feed_dead = {one.day for one in rows[:-2]}
        found = kinds(judge(history(rows, usable_feeding=feed_dead)))
        assert found == {"low_activity"}


class TestNePodhodilKKormu:
    """
    «Не подходил к корму вовсе» — отдельная тревога.

    Это не «меньше обычного», а ноль при известной норме, и говорить об
    этом надо сразу, не дожидаясь второго дня. Ближе к правилу про воду,
    чем к правилу про количество корма.

    Ради этого правила и заводился счётчик подходов: время у корма ловит
    другое. Животное может простоять у кормушки долго, подойдя однажды,
    и наоборот — суетливо подходить помногу и почти не есть.
    """

    def test_ni_razu_pri_norme(self):
        rows = days(600, 600, 600, 600, 600, meals=4)
        rows[-1] = AnimalDay(
            "a1", rows[-1].day, 600.0, 3600.0,
            feeder_seconds=600.0, feeder_visits=0, water_visits=3,
        )
        assert "few_meals" in kinds(judge(history(rows)))

    def test_pri_norme_v_odin_podhod_molchim(self):
        """
        При норме в один подход ноль — это с равным успехом и пропущенный
        приём пищи, и один незамеченный визит. Тревожить нельзя.
        """
        rows = days(600, 600, 600, 600, 600, meals=1)
        rows[-1] = AnimalDay(
            "a1", rows[-1].day, 600.0, 3600.0,
            feeder_seconds=600.0, feeder_visits=0, water_visits=3,
        )
        assert "few_meals" not in kinds(judge(history(rows)))

    def test_bez_normy_molchim(self):
        """
        Камера над кормом жила только вчера: годных суток для нормы
        меньше трёх, нормы нет. Ноль подходов тогда ничего не значит.

        Проверка на `None` здесь не формальность: без неё сравнение
        None с числом роняет разбор всей фермы, а не одного животного.
        """
        rows = days(600, 600, 600, 600, 600, meals=0)
        alive = {rows[-1].day, rows[-2].day}
        assert "few_meals" not in kinds(
            judge(history(rows, usable_feeding=alive))
        )

    def test_ne_dubliruetsya_s_dvumya_priznakami(self):
        """
        Мало двигалась И ноль подходов к корму. Раньше сюда приходила
        сдвоенная тревога «мало ест и мало двигается» — но про корм уже
        сказано срочнее и точнее.
        """
        rows = days(600, 600, 600, 200, 200, meals=4)
        for i in (-1, -2):
            rows[i] = AnimalDay(
                "a1", rows[i].day, 200.0, 3600.0,
                feeder_seconds=0.0, feeder_visits=0, water_visits=3,
            )
        found = kinds(judge(history(rows)))
        assert "few_meals" in found
        assert "low_both" not in found

    def test_ne_dubliruetsya_s_malo_korma(self):
        """
        Ноль подходов означает и ноль времени у корма. Две тревоги об
        одном и том же в один день только мешают разбирать список.
        """
        rows = days(600, 600, 600, 600, 600, meals=4)
        for i in (-1, -2):
            rows[i] = AnimalDay(
                "a1", rows[i].day, 600.0, 3600.0,
                feeder_seconds=0.0, feeder_visits=0, water_visits=3,
            )
        found = kinds(judge(history(rows)))
        assert "few_meals" in found
        assert "low_feeding" not in found

    def test_vtoroy_den_srochnee(self):
        rows = days(600, 600, 600, 600, 600, meals=4)
        for i in (-1, -2):
            rows[i] = AnimalDay(
                "a1", rows[i].day, 600.0, 3600.0,
                feeder_seconds=600.0, feeder_visits=0, water_visits=3,
            )
        finding = next(f for f in judge(history(rows)) if f.kind == "few_meals")
        assert finding.severity == "danger"

    def test_odin_den_eshchyo_ne_srochno(self):
        rows = days(600, 600, 600, 600, 600, meals=4)
        rows[-1] = AnimalDay(
            "a1", rows[-1].day, 600.0, 3600.0,
            feeder_seconds=600.0, feeder_visits=0, water_visits=3,
        )
        finding = next(f for f in judge(history(rows)) if f.kind == "few_meals")
        assert finding.severity == "warning"

    def test_odno_zhivotnoe_bez_stada_poluchaet_trevogu(self):
        """
        Пилот идёт на ОДНОЙ лошади, и стада для сравнения нет вовсе.
        Норма берётся по её же прошлым дням, поэтому правило работает.

        Если однажды норму привяжут к медиане стада, этот тест упадёт —
        и правильно сделает.
        """
        rows = days(600, 600, 600, 600, 600, meals=4)
        rows[-1] = AnimalDay(
            "a1", rows[-1].day, 600.0, 3600.0,
            feeder_seconds=600.0, feeder_visits=0, water_visits=3,
        )
        only_one = history(rows)
        assert only_one.herd_share_low == 0.0
        assert "few_meals" in kinds(judge(only_one))


class TestPodschyotPodhodov:
    def test_chitaetsya_iz_stroki_bazy(self):
        from cv_service.health import _to_day

        day = _to_day({
            "animal_id": "a1", "day": "2026-08-20", "meters": 100,
            "seconds_visible": 3600, "feeder_seconds": 600,
            "feeder_visits": 5, "water_visits": 3,
        })
        assert day.feeder_visits == 5

    def test_staraya_stroka_bez_polya_ne_ronyaet(self):
        """База может ответить без нового столбца, пока миграция не принята."""
        from cv_service.health import _to_day

        day = _to_day({
            "animal_id": "a1", "day": "2026-08-20", "meters": 100,
            "seconds_visible": 3600, "feeder_seconds": 600, "water_visits": 3,
        })
        assert day.feeder_visits == 0

    def test_kazhdoe_neobyazatelnoe_pole_tolko_imenovannoe(self):
        """
        Проверяется КАЖДОЕ поле по отдельности, а не факт падения вызова.
        Достаточно одного kw_only, чтобы позиционный вызов упал, — и
        тогда проверка проходила бы, даже потеряй остальные защиту.
        Мутант на это и выжил.

        Зачем защита: добавление поля в середину однажды уже сдвинуло
        чужие значения. Счётчик воды молча обнулился, типы совпадали,
        и увидеть это можно было только по странной тревоге.
        """
        import dataclasses

        optional = {
            f.name: f.kw_only
            for f in dataclasses.fields(AnimalDay)
            if f.default is not dataclasses.MISSING
        }
        assert optional == {
            "feeder_seconds": True,
            "feeder_visits": True,
            "water_visits": True,
        }
