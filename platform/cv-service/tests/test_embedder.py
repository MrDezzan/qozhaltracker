import pathlib
from cv_service import embedder
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cv_service.embedder import DEFAULT_MODEL, EMBEDDING_DIM, Embedder, embeddings_enabled, model_name


class TestConfig:
    def test_default_model_is_the_animal_specific_one(self):
        with patch.dict("os.environ", {}, clear=True):
            assert model_name() == DEFAULT_MODEL
            assert "MegaDescriptor" in DEFAULT_MODEL

    def test_model_can_be_overridden(self):
        with patch.dict("os.environ", {"REID_MODEL": "hf-hub:other/model"}, clear=True):
            assert model_name() == "hf-hub:other/model"

    def test_blank_override_falls_back(self):
        with patch.dict("os.environ", {"REID_MODEL": "  "}, clear=True):
            assert model_name() == DEFAULT_MODEL

    def test_disabled_by_default(self):
        """Модель тяжёлая, а кадры полезны и без неё."""
        with patch.dict("os.environ", {}, clear=True):
            assert embeddings_enabled() is False

    def test_enabled_explicitly(self):
        with patch.dict("os.environ", {"REID_ENABLED": "1"}, clear=True):
            assert embeddings_enabled() is True


def test_embedding_dim_matches_the_migration():
    """
    Длина вектора в коде и в базе должна совпадать.

    Раньше здесь стояло голое `assert EMBEDDING_DIM == 1024` — и тест
    исправно проходил, пока база отбивала каждый эталон: обе стороны
    были неверны одинаково. Проверять число против самого себя
    бессмысленно, поэтому теперь оно читается из последней миграции,
    которая задаёт тип колонки.

    Настоящую длину знает только живая модель — её весов в тестах нет.
    Эту сверку делает `dimension_mismatch` на первом же кадре.
    """
    import re

    migrations = sorted(
        (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations").glob(
            "*.sql"
        )
    )
    sizes = [
        int(match.group(1))
        for path in migrations
        for match in re.finditer(
            r"alter column embedding type vector\((\d+)\)", path.read_text()
        )
    ]
    assert sizes, "ни одна миграция не задаёт тип колонки embedding"
    assert EMBEDDING_DIM == sizes[-1]


def test_encode_returns_a_unit_length_vector():
    embedder = Embedder(name="fake")
    embedder._model = MagicMock(return_value=[np.array([3.0, 4.0], dtype="float32")])
    embedder._transform = MagicMock(
        return_value=MagicMock(unsqueeze=MagicMock(return_value="tensor"))
    )

    fake_torch = MagicMock()
    fake_torch.no_grad.return_value.__enter__ = MagicMock()
    fake_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)
    embedder._torch = fake_torch

    features = MagicMock()
    features.__getitem__ = lambda _self, _i: MagicMock(
        cpu=MagicMock(
            return_value=MagicMock(
                numpy=MagicMock(
                    return_value=np.array([3.0, 4.0], dtype="float32")
                )
            )
        )
    )
    embedder._model = MagicMock(return_value=features)

    vector = embedder.encode(np.zeros((64, 64, 3), dtype=np.uint8))

    # 3-4-5: нормированный вектор даёт 0.6 и 0.8
    assert vector == pytest.approx([0.6, 0.8], abs=1e-6)


def test_encode_does_not_load_the_model_until_called():
    embedder = Embedder(name="fake")
    assert embedder._model is None


class TestCheckAvailable:
    """
    Проверка, которой не было, и из-за этого сервис врал при запуске:
    сообщал «распознавание включено» и падал на каждом кадре с
    «No module named timm».
    """

    def test_govorit_chto_stavit(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_timm(name, *args, **kwargs):
            if name == "timm":
                raise ImportError("No module named 'timm'", name="timm")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_timm)

        problem = embedder.check_available()
        assert "timm" in problem
        # Сообщение должно говорить, что делать, а не только что сломано
        assert "pip install" in problem

    def test_pri_ustanovlennykh_modulyakh_molchit(self, monkeypatch):
        import sys
        import types

        monkeypatch.setitem(sys.modules, "timm", types.ModuleType("timm"))
        monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
        assert embedder.check_available() == ""


class TestDimensionMismatch:
    """
    Ошибка, которая тянулась с самого начала: колонка заведена на 1024,
    а модель выдаёт 1536. База отбивала каждый эталон, и в журнале это
    выглядело как «запись не работает» без причины.
    """

    def test_sovpadenie_molchit(self):
        assert embedder.dimension_mismatch([0.0] * embedder.EMBEDDING_DIM) == ""

    def test_nesovpadenie_nazyvaet_oba_chisla(self):
        problem = embedder.dimension_mismatch([0.0] * 1024)
        assert "1024" in problem
        assert str(embedder.EMBEDDING_DIM) in problem

    def test_govorit_chto_delat(self):
        problem = embedder.dimension_mismatch([0.0] * 512)
        assert "REID_MODEL" in problem or "миграц" in problem
