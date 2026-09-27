"""
Раздача кличек по всему кадру разом.

Ошибка здесь не падает с исключением и не пишется в журнал как ошибка.
Она просто ставит чужую кличку над животным, и увидеть это можно только
глазами по видео — поэтому проверок тут больше, чем кода.
"""

from __future__ import annotations

import pytest

from cv_service.identity import (
    AMBIGUOUS,
    STRONG,
    WEAK,
    Candidate,
    Seen,
    assign,
    DUP_DISTANCE,
    GOOD_AREA_PX,
    NEAR_MISS,
    QUALITY_PENALTY,
    Verdict,
    candidate_of,
    crop_quality,
    dummy_cost,
    margin_needed,
    sightings_needed,
    why_patient,
    worth_remembering,
)

ПОРОГ = 0.35
ОТРЫВ = 0.05


def увидели(track_id: int, *пары) -> Seen:
    return Seen(
        track_id=track_id,
        candidates=tuple(Candidate(имя, расстояние) for имя, расстояние in пары),
    )


def по_трекам(решения) -> dict[int, str]:
    return {v.track_id: v.animal_id for v in решения}


class TestOdnaKlichkaOdinTrek:
    """
    То, ради чего всё это написано.

    Кличка раздавалась по одному кропу за раз, и проверки «занята ли она
    другим треком в этом же кадре» не было вообще. Две коровы рядом
    могли обе стать Зорькой — невозможное состояние, которое на
    дашборде выглядит не ошибкой узнавания, а загадкой.
    """

    def test_dve_korovy_ne_stanut_odnoy(self):
        решения = assign(
            [
                увидели(1, ("зорька", 0.20), ("ночка", 0.28)),
                увидели(2, ("зорька", 0.22), ("ночка", 0.30)),
            ],
            ПОРОГ,
            ОТРЫВ,
        )
        клички = [v.animal_id for v in решения if v.animal_id]
        assert len(клички) == len(set(клички)), "одна кличка досталась двоим"

    def test_blizhayshiy_dostayotsya_tomu_komu_on_nuzhnee(self):
        """
        Жадный разбор отдал бы Зорьку первому треку — он ближе. Но тогда
        второму досталась бы Ночка за 0.50, и кадр в сумме вышел бы
        дороже. Венгерка считает кадр целиком.
        """
        решения = assign(
            [
                увидели(1, ("зорька", 0.20), ("ночка", 0.22)),
                увидели(2, ("зорька", 0.21), ("ночка", 0.50)),
            ],
            ПОРОГ,
            0.0,
        )
        assert по_трекам(решения) == {1: "ночка", 2: "зорька"}

    def test_klichka_zanyataya_drugim_trekom_nedostupna(self):
        """
        Животное, которое сейчас видно в другом треке, не может
        оказаться ещё и здесь.
        """
        решения = assign(
            [увидели(7, ("зорька", 0.10), ("ночка", 0.30))],
            ПОРОГ,
            ОТРЫВ,
            taken={"зорька": 3},
        )
        assert решения[0].animal_id == "ночка"

    def test_svoya_klichka_svoemu_treku_ne_meshaet(self):
        решения = assign(
            [увидели(3, ("зорька", 0.10))],
            ПОРОГ,
            ОТРЫВ,
            taken={"зорька": 3},
        )
        assert решения[0].animal_id == "зорька"


class TestOtryvSchitaetsyaPoKadru:
    """
    Отрыв — это насколько дороже обошёлся бы кадр без этой пары, а не
    разница между первым и вторым кандидатом.
    """

    def test_sosed_snimaet_spor(self):
        """
        Для трека B «Зорька 0.30 против Ночки 0.32» выглядит спором. По
        кадру спора нет: Зорька нужна треку A, у которого без неё всё
        дорожает на 0.28.
        """
        решения = assign(
            [
                увидели(1, ("зорька", 0.20), ("ночка", 0.50)),
                увидели(2, ("зорька", 0.30), ("ночка", 0.32)),
            ],
            ПОРОГ,
            ОТРЫВ,
        )
        assert по_трекам(решения) == {1: "зорька", 2: "ночка"}
        assert all(v.quality == STRONG for v in решения)

    def test_ravnye_kandidaty_ostayutsya_sporom(self):
        """
        А вот тут спор настоящий: поменяй клички местами — кадр стоит
        столько же. Это подбрасывание монеты, и называть нельзя.
        """
        решения = assign(
            [
                увидели(1, ("зорька", 0.20), ("ночка", 0.21)),
                увидели(2, ("зорька", 0.21), ("ночка", 0.20)),
            ],
            ПОРОГ,
            ОТРЫВ,
        )
        assert all(v.quality == AMBIGUOUS for v in решения)
        assert all(not v.animal_id for v in решения)

    @pytest.mark.parametrize("расстояние", [0.10, 0.33])
    def test_odinokiy_kandidat_prinimaetsya(self, расстояние):
        """
        Сравнивать не с кем — значит отрыва нет вовсе, и это не повод
        молчать.

        Два вопроса не надо путать. «Совпадение ли это» решает ПОРОГ.
        «Тот ли это из нескольких» решает ОТРЫВ. Требовать отрыв там, где
        кандидат один, значит втихую ужесточить порог на величину отрыва
        и потерять верные совпадения впритык к нему — а на ферме, где
        заведено одно животное, вообще не узнать никого.
        """
        решения = assign([увидели(1, ("зорька", расстояние))], ПОРОГ, ОТРЫВ)
        assert решения[0].quality == STRONG
        assert решения[0].margin == float("inf"), "сравнивать было не с чем"

    def test_dalyokiy_kandidat_ne_schitaetsya_sopernikom(self):
        """
        Кандидат за порогом — не «с чем сравнивать», а никто.

        Если пустить его в раздачу, отрыв станет конечным и правдоподобным
        (до далёкого ведь и правда далеко), и разница между «сравнивать
        не с кем» и «соперник есть, но слабый» исчезнет — а это разные
        вещи, и вторая должна уметь стать спором.
        """
        решения = assign(
            [увидели(1, ("зорька", 0.10), ("ночка", 0.90))], ПОРОГ, ОТРЫВ
        )
        assert решения[0].animal_id == "зорька"
        assert решения[0].margin == float("inf")

    def test_otryv_ne_otritsatelnyy(self):
        решения = assign(
            [увидели(1, ("зорька", 0.10), ("ночка", 0.20))], ПОРОГ, ОТРЫВ
        )
        assert решения[0].margin is not None
        assert решения[0].margin > 0


class TestNeznakomyeIPustota:
    def test_daleko_znachit_neznakomyy(self):
        решения = assign([увидели(1, ("зорька", 0.90))], ПОРОГ, ОТРЫВ)
        assert решения[0].quality == WEAK
        assert решения[0].animal_id == ""

    def test_pustoy_kadr(self):
        assert assign([], ПОРОГ, ОТРЫВ) == []

    def test_trek_bez_kandidatov(self):
        решения = assign([увидели(5)], ПОРОГ, ОТРЫВ)
        assert решения[0].quality == WEAK
        assert решения[0].track_id == 5

    def test_neznakomyh_mozhet_byt_neskolko(self):
        """
        Колонок «новый» столько же, сколько треков.

        Одной на всех не хватило бы: незнакомых животных в кадре бывает
        сколько угодно, и второму пришлось бы достаться хоть кто-нибудь.
        Проверяется вместе со знакомым в том же кадре — иначе разбор
        обрывается раньше, чем дойдёт до раздачи, и правило остаётся
        непроверенным.
        """
        решения = assign(
            [
                увидели(1, ("зорька", 0.10)),
                увидели(2, ("ночка", 0.90)),
                увидели(3, ("ночка", 0.95)),
            ],
            ПОРОГ,
            ОТРЫВ,
        )
        по_треку = {v.track_id: v for v in решения}
        assert по_треку[1].animal_id == "зорька"
        assert по_треку[2].quality == WEAK
        assert по_треку[3].quality == WEAK

    def test_resheniy_stolko_zhe_skolko_trekov(self):
        """
        Иначе трек молча выпадает: его никто не назвал, но и в журнал
        он не попал.
        """
        наблюдения = [
            увидели(1, ("зорька", 0.10)),
            увидели(2),
            увидели(3, ("ночка", 0.90)),
        ]
        решения = assign(наблюдения, ПОРОГ, ОТРЫВ)
        assert [v.track_id for v in решения] == [1, 2, 3]


class TestOtkazDorozheChuzhogo:
    def test_otkaz_stoit_rovno_porog(self):
        """
        Всё, что дальше порога, по определению не совпадение. Поэтому
        отказ стоит ровно порог: венгерка выберет его сама, без
        отдельной проверки после.
        """
        assert dummy_cost(ПОРОГ) == ПОРОГ

    def test_za_porogom_sovpadeniya_net(self):
        впритык = assign([увидели(1, ("зорька", 0.349))], ПОРОГ, ОТРЫВ)
        assert впритык[0].animal_id == "зорька", "0.349 — это ещё совпадение"

        за_порогом = assign([увидели(1, ("зорька", 0.351))], ПОРОГ, ОТРЫВ)
        assert за_порогом[0].animal_id == ""
        assert за_порогом[0].quality == WEAK


class TestBlizhayshiyDlyaPereprosa:
    """
    Спорный трек не выбрасывается: он запоминает ближайшего и
    спрашивает ещё раз по другому кадру.
    """

    def test_pri_spore_vozvrashchaetsya_blizhayshiy(self):
        наблюдение = увидели(1, ("зорька", 0.20), ("ночка", 0.21))
        решения = assign([наблюдение, увидели(2, ("зорька", 0.21), ("ночка", 0.20))], ПОРОГ, ОТРЫВ)
        assert candidate_of(решения[0], наблюдение) == "зорька"

    def test_pri_uverennosti_vozvrashchaetsya_on_zhe(self):
        наблюдение = увидели(1, ("зорька", 0.10))
        решения = assign([наблюдение], ПОРОГ, ОТРЫВ)
        assert candidate_of(решения[0], наблюдение) == "зорька"

    def test_kogda_nikogo_net(self):
        наблюдение = увидели(1)
        решения = assign([наблюдение], ПОРОГ, ОТРЫВ)
        assert candidate_of(решения[0], наблюдение) == ""


class TestUstoychivost:
    @pytest.mark.parametrize("сколько", [1, 3, 8, 20])
    def test_mnogo_trekov_ne_lomayut(self, сколько):
        наблюдения = [
            увидели(i, (f"жив{i}", 0.10), (f"жив{(i + 1) % сколько}", 0.30))
            for i in range(сколько)
        ]
        решения = assign(наблюдения, ПОРОГ, ОТРЫВ)
        клички = [v.animal_id for v in решения if v.animal_id]
        assert len(клички) == len(set(клички))
        assert len(решения) == сколько

    def test_poryadok_nablyudeniy_ne_menyaet_itog(self):
        """
        Кадр — это множество, а не список. Если ответ зависит от того,
        в каком порядке трекер вернул детекции, он зависит от случая.
        """
        наблюдения = [
            увидели(1, ("зорька", 0.20), ("ночка", 0.50)),
            увидели(2, ("зорька", 0.30), ("ночка", 0.32)),
        ]
        прямо = по_трекам(assign(наблюдения, ПОРОГ, ОТРЫВ))
        наоборот = по_трекам(assign(list(reversed(наблюдения)), ПОРОГ, ОТРЫВ))
        assert прямо == наоборот


class TestChtoStoitZapominat:
    """
    Узнали животное — стоит ли класть этот кадр в эталоны.

    Раньше клался КАЖДЫЙ, и это две беды сразу.

    Эталонов у животного двенадцать, вытеснялся самый старый. Корова,
    десять раз подряд снятая с одного ракурса, вытесняла сама себя:
    оставались десять почти одинаковых спин, а профиль, снятый когда-то
    сбоку, уходил. Узнавание сбоку пропадало — и это выглядит как
    «сначала работало, потом перестало».

    И запоминалось то, что узналось с переспроса, то есть с сомнением.
    Ошибка узнавания живёт секунду, ошибка в эталоне — вечно.
    """

    def уверенно(self, distance=0.20):
        return Verdict(
            track_id=1,
            animal_id="зорька",
            quality=STRONG,
            distance=distance,
            margin=0.30,
        )

    def test_novyy_rakurs_zapominaem(self):
        стоит, почему = worth_remembering(self.уверенно(0.25))
        assert стоит is True
        assert "ракурс" in почему

    def test_tot_zhe_rakurs_ne_zapominaem(self):
        """
        Двенадцать почти одинаковых спин вытесняют единственный профиль.
        """
        стоит, почему = worth_remembering(self.уверенно(0.02))
        assert стоит is False
        assert "уже есть" in почему

    def test_sporno_ne_zapominaem(self):
        решение = Verdict(track_id=1, quality=AMBIGUOUS, distance=0.20)
        стоит, _ = worth_remembering(решение)
        assert стоит is False

    def test_ne_uznali_ne_zapominaem(self):
        стоит, _ = worth_remembering(Verdict(track_id=1, quality=WEAK))
        assert стоит is False

    def test_pereprosom_ne_zapominaem(self):
        """
        Два кадра сошлись — этого хватает, чтобы показать кличку. Для
        эталона нет: показанная кличка живёт секунду, эталон навсегда.
        """
        стоит, почему = worth_remembering(self.уверенно(), voted=True)
        assert стоит is False
        assert "переспрос" in почему

    def test_plokhoy_kadr_ne_zapominaem(self):
        стоит, почему = worth_remembering(self.уверенно(), crop_ok=False)
        assert стоит is False
        assert "плох" in почему

    def test_prichina_est_vsegda(self):
        """
        «Эталон не добавлен» без объяснения выглядит поломкой, а отказ
        тут — обычное дело и случается чаще согласия.
        """
        случаи = [
            worth_remembering(self.уверенно()),
            worth_remembering(self.уверенно(0.01)),
            worth_remembering(self.уверенно(), voted=True),
            worth_remembering(self.уверенно(), crop_ok=False),
            worth_remembering(Verdict(track_id=1, quality=WEAK)),
        ]
        assert all(почему for _, почему in случаи)

    def test_porog_dublikata_menshe_poroga_uznavaniya(self):
        """
        Иначе «тот же ракурс» поглотил бы вообще все совпадения, и
        эталоны перестали бы пополняться совсем.
        """
        assert 0 < DUP_DISTANCE < ПОРОГ


class TestKogdaZavoditNovuyu:
    """
    Полоса «почти узнали» за порогом.

    Расстояние 0.40 при пороге 0.35 — это не незнакомое животное. Это
    чаще всего ЗНАКОМОЕ, снятое непривычно: сзади, в темноте, наполовину
    за столбом. Новая запись по такому кадру — двойник, а двойник хуже
    пропуска: кандидатов больше, отрыв меньше, и система постепенно
    перестаёт узнавать вообще кого-либо.
    """

    БАЗА = 2

    def test_nezakomets_zavoditsya_kak_ranshe(self):
        assert sightings_needed(0.80, ПОРОГ, self.БАЗА) == self.БАЗА

    def test_pochti_uznali_trebuet_bolshe(self):
        assert sightings_needed(0.40, ПОРОГ, self.БАЗА) > self.БАЗА

    def test_granitsy_polosy(self):
        """
        Ниже порога животное уже узнано — заводить нечего. Выше полосы
        это честный незнакомец, и тянуть с ним незачем.
        """
        assert sightings_needed(ПОРОГ - 0.01, ПОРОГ, self.БАЗА) == self.БАЗА
        assert sightings_needed(ПОРОГ + 0.001, ПОРОГ, self.БАЗА) > self.БАЗА
        assert sightings_needed(ПОРОГ + NEAR_MISS, ПОРОГ, self.БАЗА) > self.БАЗА
        assert sightings_needed(ПОРОГ + NEAR_MISS + 0.001, ПОРОГ, self.БАЗА) == self.БАЗА

    def test_bez_izmereniya_ostayomsya_pri_svoyom(self):
        """
        Расстояния нет — значит база не ответила. Ужесточать правила по
        отсутствующим данным нельзя: так система перестанет заводить
        животных вовсе, и никто не поймёт почему.
        """
        assert sightings_needed(None, ПОРОГ, self.БАЗА) == self.БАЗА

    def test_v_zhurnale_est_prichina(self):
        assert why_patient(0.40, ПОРОГ) != ""
        assert why_patient(0.80, ПОРОГ) == ""
        assert why_patient(None, ПОРОГ) == ""


class TestPlokhoyKadrDokazyvaetBolshe:
    """
    Кадр бывает разный, а порог отрыва до сих пор был один на все.

    Смазанная мелкая корова даёт шумный вектор: расстояния до эталонов
    у него все примерно одинаковые и все примерно случайные. Отрыв 0.06
    на чётком крупном кадре — это разница между животными, тот же отрыв
    на смазанном — разница между двумя шумами.

    Отбрасывать плохие кадры целиком нельзя: животное могло всю дорогу
    идти быстро, и тогда чётких кадров нет вовсе, а узнать его надо.
    Поэтому плохой кадр не отбрасывается, а обязан доказывать больше.
    """

    def test_ideal_trebuet_obychnogo(self):
        assert margin_needed(ОТРЫВ, 1.0) == ОТРЫВ

    def test_nikakoy_trebuet_vdvoe(self):
        assert margin_needed(ОТРЫВ, 0.0) == ОТРЫВ * QUALITY_PENALTY

    def test_trebovanie_rastyot_plavno(self):
        """
        Ступеньки быть не должно: кадр чуть хуже — требование чуть выше.
        Иначе одно и то же животное то узнаётся, то нет, и объяснить
        это невозможно.
        """
        подряд = [margin_needed(ОТРЫВ, q / 10) for q in range(11)]
        assert подряд == sorted(подряд, reverse=True)

    def test_kachestvo_v_predelakh_ot_nulya_do_edinitsy(self):
        """Мусор на входе не должен превращаться в отрицательный порог."""
        assert margin_needed(ОТРЫВ, 5.0) == ОТРЫВ
        assert margin_needed(ОТРЫВ, -3.0) == ОТРЫВ * QUALITY_PENALTY

    def test_smazannyy_kadr_ne_nazyvaet_sporno(self):
        """
        Тот же кадр, то же расстояние — но на плохом снимке система
        молчит, а на хорошем называет.
        """
        пара = (("зорька", 0.20), ("ночка", 0.26))
        хороший = assign(
            [Seen(1, tuple(Candidate(*p) for p in пара), quality=1.0)],
            ПОРОГ,
            ОТРЫВ,
        )
        плохой = assign(
            [Seen(1, tuple(Candidate(*p) for p in пара), quality=0.0)],
            ПОРОГ,
            ОТРЫВ,
        )
        assert хороший[0].animal_id == "зорька"
        assert плохой[0].quality == AMBIGUOUS

    def test_kachestvo_kadra_schitaetsya_iz_tryokh(self):
        """
        Каждый множитель может обнулить остальные: далёкое животное не
        спасёт резкость, смазанное — размер, а неуверенная детекция
        может оказаться и не животным.
        """
        полное = crop_quality(GOOD_AREA_PX, 1.0, 1.0)
        assert полное == 1.0
        assert crop_quality(0.0, 1.0, 1.0) == 0.0
        assert crop_quality(GOOD_AREA_PX, 0.0, 1.0) == 0.0
        assert crop_quality(GOOD_AREA_PX, 1.0, 0.0) == 0.0

    def test_ochen_krupnyy_kadr_ne_luchshe_prosto_krupnogo(self):
        assert crop_quality(GOOD_AREA_PX * 100, 1.0, 1.0) == 1.0
