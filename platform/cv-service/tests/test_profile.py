"""Один набор классов и границ на всю систему."""

from cv_service import profile as profile_module
from cv_service.profile import LIVESTOCK_PROFILE, weight_is_plausible


class TestClasses:
    def test_chelovek_ne_zhivotnoe(self):
        assert "person" not in LIVESTOCK_PROFILE.subject_classes
        assert "person" in LIVESTOCK_PROFILE.security_classes

    def test_tekhnika_v_okhrane(self):
        assert "car" in LIVESTOCK_PROFILE.security_classes


class TestWeightBounds:
    def test_pravdopodobnyy_ves_prokhodit(self):
        assert weight_is_plausible(LIVESTOCK_PROFILE, 450.0)

    def test_korova_vesom_chetyre_kilogramma_otbrasyvaetsya(self):
        # Пустая клетка честнее заведомо неверного числа
        assert not weight_is_plausible(LIVESTOCK_PROFILE, 4.0)

    def test_dve_tonny_otbrasyvayutsya(self):
        assert not weight_is_plausible(LIVESTOCK_PROFILE, 2000.0)

    def test_otsutstvie_otsenki_ne_ronyaet(self):
        assert not weight_is_plausible(LIVESTOCK_PROFILE, None)


class TestMeasurePlacements:
    def test_meryaem_tolko_sverkhu(self):
        # Площадь коровы сбоку зависит от того, как она повернулась,
        # и с массой не связана
        assert LIVESTOCK_PROFILE.measure_placements == frozenset({"overhead"})


class TestCountPeople:
    """Временный режим: считать людей, пока нет фермы."""

    def test_po_umolchaniyu_vyklyucheno(self, monkeypatch):
        monkeypatch.delenv("COUNT_PEOPLE", raising=False)
        assert not profile_module.count_people()
        assert "person" not in profile_module.resolve().subject_classes

    def test_vklyuchaetsya_odnoy_strokoy(self, monkeypatch):
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert "person" in profile_module.resolve().subject_classes

    def test_chelovek_ne_ostayotsya_v_okhrane(self, monkeypatch):
        # Иначе он был бы одновременно подопечным и посторонним, и
        # тревога поднималась бы на каждого, кого система считает
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert "person" not in profile_module.resolve().security_classes

    def test_tekhnika_ostayotsya_v_okhrane(self, monkeypatch):
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert "car" in profile_module.resolve().security_classes

    def test_proportsii_shire(self, monkeypatch):
        # Человек в полный рост сбоку вытянут сильнее любой коровы
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert profile_module.resolve().max_aspect > LIVESTOCK_PROFILE.max_aspect

    def test_mozhno_meryat_sboku(self, monkeypatch):
        # Рост от поворота не меняется, а вид сверху человека укорачивает
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert "side" in profile_module.resolve().measure_placements

    def test_granitsy_vesa_dopuskayut_cheloveka(self, monkeypatch):
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        assert weight_is_plausible(profile_module.resolve(), 75.0)

    def test_rezhim_govorit_o_sebe_vsluh(self, monkeypatch):
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        text = profile_module.describe(profile_module.resolve())
        assert "ЛЮДЕЙ" in text
        assert "не годятся" in text

    def test_ishodnyy_profil_ne_menyaetsya(self, monkeypatch):
        # Профиль скота — общая константа модуля. Правка его на месте
        # означала бы, что один запуск с людьми портит все остальные
        monkeypatch.setenv("COUNT_PEOPLE", "1")
        profile_module.resolve()
        assert "person" not in LIVESTOCK_PROFILE.subject_classes
