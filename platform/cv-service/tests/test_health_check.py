"""
Сборка проверки здоровья. Этап 5 плана PLAN_POVEDENIE.md.

Здесь строки из базы превращаются в истории животных, а истории — в
тревоги. Правила уже проверены отдельно; тут проверяется, что до них
доходят верные данные.
"""

from cv_service.health import (
    AnimalDay,
    CameraDay,
    build_histories,
    can_judge,
    herd_share_low,
    run_check,
)


def cam(camera="cam", day="2026-08-18", hours=24.0, feeder=True):
    return {
        "camera_id": camera,
        "day": day,
        "alive_hours": hours,
        "has_feeder": feeder,
    }


def row(animal="a1", day="2026-08-18", meters=600.0, seconds=3600.0,
        feeder=600.0, water=3):
    return {
        "animal_id": animal,
        "day": day,
        "meters": meters,
        "seconds_visible": seconds,
        "feeder_seconds": feeder,
        "water_visits": water,
    }


def named(animal="a1", label="Зорька", embeddings=12):
    return {"animal_id": animal, "label": label, "embeddings": embeddings}


class TestSborka:
    def test_dni_idut_po_vozrastaniyu(self):
        """
        Порядок решает всё: последний день — тот, о котором судят, а
        предыдущие идут в норму. Перепутанный порядок означал бы, что
        норму строят по будущему, а судят по прошлому.
        """
        rows = [row(day="2026-08-18"), row(day="2026-08-16"), row(day="2026-08-17")]
        built = build_histories(rows, [named()], [cam()])
        assert [one.day for one in built[0].days] == [
            "2026-08-16", "2026-08-17", "2026-08-18"
        ]

    def test_kazhdomu_zhivotnomu_svoi_dni(self):
        rows = [row(animal="a1"), row(animal="a2")]
        built = build_histories(
            rows, [named("a1"), named("a2", "Ночка")], [cam()]
        )
        assert {one.animal_id for one in built} == {"a1", "a2"}
        assert all(len(one.days) == 1 for one in built)

    def test_klichka_i_etalony_popadayut_v_istoriyu(self):
        built = build_histories([row()], [named(embeddings=7)], [cam()])
        assert built[0].label == "Зорька"
        assert built[0].embeddings == 7

    def test_zhivotnoe_bez_strok_ne_teryaetsya(self):
        # База отдаёт полную сетку, но если строк почему-то нет —
        # животное должно остаться с пустой историей, а не пропасть
        built = build_histories([], [named()], [cam()])
        assert len(built) == 1 and built[0].days == []

    def test_godnost_sutok_prikladyvaetsya(self):
        built = build_histories([row()], [named()], [cam(hours=2.0)])
        assert built[0].usable_movement == set()

    def test_stroka_bez_zhivotnogo_ne_ronyaet(self):
        # Животное удалили, пока шла проверка
        built = build_histories([row(animal="призрак")], [named("a1")], [cam()])
        assert len(built) == 1 and built[0].days == []


class TestDolyaStada:
    def test_schitaet_dolyu_prosevshikh(self):
        assert herd_share_low(low=5, total=15) == 1.0 / 3.0

    def test_pustoe_stado_ne_delit_na_nol(self):
        assert herd_share_low(low=0, total=0) == 0.0


class TestProverkaTselikom:
    def _farm(self, meters_last=600.0, feeder_last=600.0):
        dates = ["2026-08-%02d" % d for d in (14, 15, 16, 17, 18)]
        rows = [row(day=d) for d in dates[:-1]]
        rows.append(row(day=dates[-1], meters=meters_last, feeder=feeder_last))
        # Второе животное здоровое: без него стадо из одного, и доля
        # просевших выходит стопроцентной при любой болезни
        rows += [row(animal="a2", day=d) for d in dates]
        return rows, [named(), named("a2", "Ночка")], [cam(day=d) for d in dates]

    def test_zdorovoe_stado_nichego_ne_dayot(self):
        rows, animals, cams = self._farm()
        assert run_check(rows, animals, cams) == []

    def test_bolnaya_korova_nakhoditsya(self):
        rows, animals, cams = self._farm(meters_last=100.0, feeder_last=50.0)
        found = run_check(rows, animals, cams)
        assert [one.kind for one in found] == ["low_both"]
        assert found[0].animal_id == "a1"

    def test_prosevshee_stado_dayot_odnu_trevogu_na_fermu(self):
        """
        Половина стада ниже нормы — это загон, а не болезнь у каждой по
        очереди. Личных тревог быть не должно ни одной.
        """
        dates = ["2026-08-%02d" % d for d in (14, 15, 16, 17, 18)]
        rows = []
        animals = []
        for i in range(6):
            name = "a%d" % i
            animals.append(named(name, "Корова %d" % i))
            for d in dates[:-1]:
                rows.append(row(animal=name, day=d))
            # Половина стада просела в последний день
            last = 100.0 if i < 3 else 600.0
            rows.append(row(animal=name, day=dates[-1], meters=last, feeder=last))

        found = run_check(rows, animals, [cam(day=d) for d in dates])
        assert [one.kind for one in found] == ["herd_low"]

    def test_pustaya_ferma_ne_ronyaet(self):
        assert run_check([], [], []) == []


class TestMaloeStadoNeGlushit:
    """
    Ловушка, найденная тестом сборки.

    На ферме из двух голов одна больная — это «половина стада». Личные
    тревоги гасились как общая просадка, а стадная не поднималась,
    потому что стадо мало. Система умолкала ровно там, где должна была
    говорить.
    """

    def _farm(self, heads):
        dates = ["2026-08-%02d" % d for d in (14, 15, 16, 17, 18)]
        rows, animals = [], []
        for i in range(heads):
            name = "a%d" % i
            animals.append(named(name, "Корова %d" % i))
            for d in dates[:-1]:
                rows.append(row(animal=name, day=d))
            # Заболела только первая
            last = 100.0 if i == 0 else 600.0
            rows.append(row(animal=name, day=dates[-1], meters=last, feeder=last))
        return rows, animals, [cam(day=d) for d in dates]

    def test_odna_iz_dvukh_vsyo_ravno_nakhoditsya(self):
        found = run_check(*self._farm(2))
        assert [one.kind for one in found] == ["low_both"]

    def test_odna_iz_chetyryokh_nakhoditsya(self):
        # Четверть — уже ниже трети, но стадо всё ещё меньше порога
        found = run_check(*self._farm(4))
        assert [one.kind for one in found] == ["low_both"]

    def test_na_bolshom_stade_odna_bolnaya_ne_prosadka_stada(self):
        found = run_check(*self._farm(10))
        assert [one.kind for one in found] == ["low_both"]


class TestSudimTolkoPoKonchivshimsyaSutkam:
    """
    Две поломки, найденные враждебным ревью 5 сентября 2026. Обе давали
    ноль упавших тестов и при этом ломали продукт целиком.
    """

    def test_can_judge_pri_zhivykh_sutkakh(self):
        assert can_judge([cam(day="2026-08-17"), cam(day="2026-08-18")]) is True

    def test_can_judge_kogda_kamera_rabotala_malo(self):
        """
        Камера жила три часа — судить не по чему. Именно так выглядит
        ночь: вчерашние сутки ушли за горизонт, а сегодняшних база уже
        не отдаёт.
        """
        assert can_judge([cam(day="2026-08-18", hours=3.0)]) is False

    def test_can_judge_bez_kamer_voobshche(self):
        assert can_judge([]) is False

    def test_nechego_sudit_ne_znachit_vsyo_khorosho(self):
        """
        Главное различие. Пустой список находок возвращается и когда всё
        хорошо, и когда судить не по чему, а последствия у них
        противоположные: в первом случае открытые тревоги надо закрыть,
        во втором нельзя трогать.

        Раньше различия не было, apply_health_findings звался с пустым
        списком в обоих случаях и закрывал всё открытое. Проверка идёт
        раз в час, то есть за ночь это происходило около тринадцати раз,
        и поднятая вечером тревога «не видели двое суток» к утру
        исчезала.
        """
        dead = [cam(day="2026-08-%02d" % d, hours=2.0) for d in (16, 17, 18)]
        rows = [row(day="2026-08-%02d" % d) for d in (16, 17, 18)]

        assert run_check(rows, [named()], dead) == []
        assert can_judge(dead) is False

    def test_zdorovaya_korova_v_nepolnyy_den_ne_bolnaya(self):
        """
        Сутки, которые ещё идут, база больше не отдаёт (миграция 0044),
        поэтому в сетке их нет. Проверяем следствие: корова, у которой
        последний ЗАКОНЧИВШИЙСЯ день в норме, тревог не даёт.

        До правки сетка доходила до сегодняшней даты, последний день был
        неполным, и около часа дня здоровая корова, прошедшая полдня
        половину нормы, получала «повод позвать ветврача».
        """
        dates = ["2026-08-%02d" % d for d in (15, 16, 17, 18)]
        rows = [row(day=d, meters=600.0, feeder=600.0) for d in dates]
        found = run_check(rows, [named()], [cam(day=d) for d in dates])
        assert found == []

    def test_polovina_normy_v_poslednie_sutki_vsyo_zhe_nakhoditsya(self):
        """
        Обратная сторона: обрезав сетку, легко случайно выключить
        проверку совсем. Те же данные, но последний день правда просел —
        тревога обязана быть.
        """
        dates = ["2026-08-%02d" % d for d in (15, 16, 17, 18)]
        rows = [row(day=d, meters=600.0, feeder=600.0) for d in dates[:-1]]
        rows.append(row(day=dates[-1], meters=330.0, feeder=1650.0 / 60))
        found = run_check(rows, [named()], [cam(day=d) for d in dates])
        assert [one.kind for one in found] == ["low_both"]


class TestKrugProverkiNeTrogaetTrevogiVpustuyu:
    """
    `_check_health` целиком: от строк базы до решения, трогать ли
    тревоги. Раньше это место не было покрыто ничем, и обе поломки
    жили именно здесь.
    """

    def _run(self, camera_rows, monkeypatch, found=None):
        from cv_service import main as m

        calls = []
        monkeypatch.setattr(
            m, "fetch_health_input",
            lambda client, farm: ([row()], [named()], camera_rows),
        )
        monkeypatch.setattr(m, "run_check", lambda *a: found or [])
        monkeypatch.setattr(
            m, "apply_health_findings",
            lambda client, farm, f: (calls.append(f), (0, 7))[1],
        )
        m._check_health(object(), "farm-1")
        return calls

    def test_sudit_ne_po_chemu_trevogi_ne_trogaem(self, monkeypatch):
        """
        Ночью годных суток нет. Открытые тревоги обязаны дожить до утра.
        """
        dead = [cam(day="2026-08-18", hours=2.0)]
        assert self._run(dead, monkeypatch) == []

    def test_posmotreli_i_chisto_otkrytoe_zakryvaem(self, monkeypatch):
        """
        Обратная сторона: когда судить было по чему и не нашли ничего,
        закрыть открытое надо. Иначе тревога висела бы вечно.
        """
        alive = [cam(day="2026-08-18", hours=24.0)]
        assert self._run(alive, monkeypatch) == [[]]
