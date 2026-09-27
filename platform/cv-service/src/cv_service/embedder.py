from __future__ import annotations

import os
import threading

# MegaDescriptor обучен специально на повторной идентификации животных
# и в сравнительных работах обходит универсальные энкодеры вроде DINOv2.
DEFAULT_MODEL = "hf-hub:BVRA/MegaDescriptor-L-384"

# Длина вектора. Должна совпадать с vector(N) в базе — иначе КАЖДЫЙ
# эталон отбивается с «expected N dimensions, not M», и узнавание не
# работает вовсе.
#
# Здесь стояло 1024, и это было просто неверно: L-версия построена на
# Swin-L и выдаёт 1536. Ошибку не было видно, пока модель не запустилась
# по-настоящему: в тестах она подменена заглушкой, а живая весит сотни
# мегабайт. Меняя модель, это число надо менять вместе с базой.
EMBEDDING_DIM = 1536


def model_name() -> str:
    return os.environ.get("REID_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def reid_threads() -> int:
    """
    Сколько ядер отдать модели узнавания.

    По умолчанию половина, и это важнее, чем кажется. Torch по умолчанию
    забирает ВСЕ ядра, а на мини-ПК их четыре и на каждую камеру уходит
    почти одно: поиск животных идёт восемь раз в секунду. Пока считается
    вектор — две-четыре секунды, — захват кадров остаётся без процессора,
    трекер теряет животное между кадрами и выдаёт ему новый номер.
    Выглядит это как завышенное поголовье, и связать одно с другим
    нечем.

    Лучше считать вектор вдвое дольше, чем ронять трекинг: кличка
    появится позже, а поголовье останется верным.
    """
    raw = os.environ.get("REID_THREADS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, (os.cpu_count() or 2) // 2)


def embeddings_enabled() -> bool:
    """
    Векторы считаются, только если это явно включено.

    Модель тяжёлая, а кадры полезны и без неё: их можно называть руками,
    накапливая датасет. Поэтому сбор данных не зависит от наличия модели.
    """
    return os.environ.get("REID_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def dimension_mismatch(vector) -> str:
    """
    Совпадает ли длина вектора с тем, что ждёт база. Пусто — совпадает.

    Проверка нужна на первом же векторе: без неё несовпадение видно
    только по ошибке базы на каждом кадре, а выглядит это как «запись
    не работает» без всякого намёка на причину.
    """
    actual = len(vector)
    if actual == EMBEDDING_DIM:
        return ""
    return (
        f"модель выдаёт вектор длиной {actual}, а база ждёт {EMBEDDING_DIM}. "
        "Узнавание работать не будет. Либо верните прежнюю модель в "
        "REID_MODEL, либо переведите колонку animal_embeddings.embedding "
        f"на vector({actual}) миграцией"
    )


def check_available() -> str:
    """
    Можно ли вообще считать векторы. Пустая строка — можно.

    Проверяются только импорты, без загрузки весов: веса — сотни
    мегабайт, и ждать их на запуске незачем. А вот отсутствие самих
    библиотек надо поймать сразу.

    Раньше этой проверки не было, и выглядело это так: сервис бодро
    сообщал «распознавание особей включено», а дальше на каждом кадре
    печатал «No module named timm». Узнавание при этом не работало
    вовсе, и связать одно с другим было нечем.
    """
    try:
        import timm  # noqa: F401
        import torch  # noqa: F401
    except ImportError as exc:
        missing = getattr(exc, "name", "") or "timm"
        return (
            f"не установлен модуль {missing}. Узнавание, запись животных и "
            "клички на кадре работать не будут. Поставьте зависимости: "
            "cd cv-service && ./.venv/bin/pip install -r requirements.txt"
        )
    return ""


class Embedder:
    """
    Ленивая обёртка над моделью: веса грузятся при первом вызове,
    чтобы запуск сервиса не ждал скачивания сотен мегабайт.

    Экземпляр один на все камеры, и с двумя камерами это перестало быть
    безобидным. Потоки камер независимы: обе видят животное в один и тот
    же момент и в один и тот же момент просят вектор.

    Без замка на загрузке выходило две беды сразу. Обе камеры не
    находили модель и обе начинали её создавать — семьсот мегабайт
    дважды, а при первом запуске ещё и скачивание дважды. И вторая,
    хуже: `_torch` присваивается ПОСЛЕ `_model`, а проверка смотрит на
    `_model`. Вторая камера успевала пройти проверку и обратиться к
    `_torch`, которого ещё нет, — падение на ровном месте, и только
    когда камер больше одной.
    """

    def __init__(self, name: str | None = None):
        self.name = name or model_name()
        self._model = None
        self._transform = None
        self._torch = None
        self._loading = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        with self._loading:
            # Ещё раз под замком: пока мы его ждали, соседняя камера
            # могла всё загрузить
            if self._model is not None:
                return

            import timm
            import torch

            # До создания модели: после первого счёта менять число
            # потоков уже поздно, torch запоминает его при сборке графа
            torch.set_num_threads(reid_threads())

            model = timm.create_model(self.name, pretrained=True, num_classes=0)
            model.eval()

            config = timm.data.resolve_data_config({}, model=model)
            self._transform = timm.data.create_transform(**config)
            self._torch = torch
            # Модель — ПОСЛЕДНЕЙ: по ней судят о готовности, и выставить
            # её раньше остального значит пустить соседнюю камеру в
            # наполовину собранный объект
            self._model = model

    def encode(self, crop_bgr) -> list[float]:
        """
        Кадр в формате OpenCV (BGR) → нормированный вектор признаков.

        Вектор нормируется, поэтому косинусное расстояние сводится
        к скалярному произведению — так ищет и Postgres.
        """
        self._ensure_loaded()

        import cv2
        import numpy as np
        from PIL import Image

        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        tensor = self._transform(Image.fromarray(rgb)).unsqueeze(0)

        with self._torch.no_grad():
            features = self._model(tensor)

        vector = features[0].cpu().numpy().astype("float32")
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return vector.tolist()
