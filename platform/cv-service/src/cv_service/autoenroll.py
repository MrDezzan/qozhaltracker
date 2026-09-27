"""
Система сама запоминает животное при первой встрече.

Увидела незнакомую особь — завела запись «№ 12» и запомнила её вектор.
Со следующего раза узнаёт сама и пишет номер над животным на кадре.
Человек потом переименовывает «№ 12» в «Зорьку», когда дойдут руки;
до этого система работает без него.

Отличие от прежней очереди «ждут имени» принципиальное. Раньше кадры
копились и НИЧЕГО не работало, пока человек их не разберёт. Теперь всё
работает сразу, а участие человека только улучшает картину.

Цена, которую надо назвать вслух: автоматическое заведение неизбежно
плодит двойников. Животное, впервые снятое сзади в темноте, а второй
раз сбоку днём, станет двумя записями. Поэтому здесь строгий отбор
кадров, а в интерфейсе — слияние.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def autoenroll_enabled() -> bool:
    """
    По умолчанию включено: без этого система не узнаёт никого, пока
    человек не заведёт всех руками.
    """
    return os.environ.get("AUTO_ENROLL", "1").strip().lower() in {"1", "true", "yes"}


# Требования к кадру, по которому заводится НОВАЯ особь.
#
# Намеренно строже, чем к кадру для обычного узнавания. Ошибка узнавания
# живёт секунду — не узнали и не узнали. Ошибка заведения живёт вечно:
# в базе навсегда остаётся лишняя запись с плохим эталоном, под который
# потом подходит не то животное.
DEFAULT_MIN_CONFIDENCE = 0.75
DEFAULT_MIN_AREA_PX = 40_000        # примерно 200×200
DEFAULT_MIN_SIGHTINGS = 2


@dataclass
class AutoEnrollRules:
    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    min_area_px: float = DEFAULT_MIN_AREA_PX
    # Сколько раз подряд надо увидеть незнакомца, прежде чем заводить.
    #
    # Единственная защита от того, чтобы каждая тень и каждый обрезанный
    # краем кадра бок становились новой «особью». Первую встречу просто
    # запоминаем и ждём подтверждения.
    min_sightings: int = DEFAULT_MIN_SIGHTINGS

    @classmethod
    def from_env(cls) -> "AutoEnrollRules":
        return cls(
            min_confidence=_number("AUTO_ENROLL_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE),
            min_area_px=_number("AUTO_ENROLL_MIN_AREA", DEFAULT_MIN_AREA_PX),
            min_sightings=int(_number("AUTO_ENROLL_MIN_SIGHTINGS", DEFAULT_MIN_SIGHTINGS)),
        )


def _number(name: str, fallback: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else fallback
    except ValueError:
        return fallback


def crop_is_good_enough(crop, rules: AutoEnrollRules) -> str | None:
    """
    Годится ли кадр, чтобы завести по нему новую особь.

    Возвращает причину отказа или None. Причина возвращается, а не
    просто False, чтобы в журнале было видно, почему система молчит, —
    иначе «не заводит никого» выглядит как поломка.
    """
    if crop.confidence < rules.min_confidence:
        return f"уверенность {crop.confidence:.0%} ниже {rules.min_confidence:.0%}"
    if crop.area < rules.min_area_px:
        return f"животное мелкое в кадре ({int(crop.area)} точек)"
    return None


class AutoEnroller:
    """
    Решает, заводить ли новую особь, и помнит незнакомцев между визитами.

    Первую встречу с незнакомцем не заводим, а запоминаем. Заводим со
    второй: одиночный кадр слишком часто оказывается тенью, обрезанным
    боком или двумя животными, слипшимися в одну рамку.
    """

    def __init__(self, rules: AutoEnrollRules | None = None):
        self.rules = rules or AutoEnrollRules()
        # Номер трека → сколько раз этот незнакомец уже приходил.
        # Трек живёт в пределах одного визита, поэтому счётчик растёт
        # по числу удачных кадров внутри визита
        self._seen: dict[int, int] = {}
        self.created = 0
        self.skipped = 0

    def consider(self, crop, nearest: float | None = None) -> tuple[bool, str]:
        """
        Заводить ли особь по этому кадру.

        `nearest` — расстояние до ближайшего заведённого животного, даже
        если оно не прошло порог. Именно оно отличает настоящего
        незнакомца от знакомого, снятого непривычно: 0.40 при пороге
        0.35 — это почти всегда своя же корова сзади или в темноте, и
        новая запись по такому кадру рождает двойника.

        Возвращает решение и объяснение для журнала.
        """
        from cv_service.crops import match_threshold
        from cv_service.identity import sightings_needed, why_patient

        reason = crop_is_good_enough(crop, self.rules)
        if reason is not None:
            self.skipped += 1
            return False, reason

        count = self._seen.get(crop.track_id, 0) + 1
        self._seen[crop.track_id] = count

        порог = match_threshold()
        надо = sightings_needed(nearest, порог, self.rules.min_sightings)

        if count < надо:
            осторожно = why_patient(nearest, порог)
            хвост = f"; {осторожно}" if осторожно else ""
            return False, f"жду подтверждения ({count}/{надо}){хвост}"

        self.created += 1
        return True, "новая особь"

    def forget(self, track_id: int) -> None:
        self._seen.pop(track_id, None)


def register_animal(client, farm_id: str, embedding: list[float], view: str = "camera"):
    """Заводит особь в базе одним вызовом. Возвращает строку или None."""
    response = client.rpc(
        "register_seen_animal",
        {
            "target_farm_id": farm_id,
            "new_embedding": embedding,
            "new_view": view,
        },
    ).execute()

    data = response.data
    if isinstance(data, list):
        return data[0] if data else None
    return data


def remember_view(client, animal_id: str, embedding: list[float], view: str = "camera") -> None:
    """
    Добавляет ещё один ракурс к уже известной особи.

    Именно это со временем делает узнавание надёжным: одна корова,
    снятая с десяти сторон, узнаётся почти всегда, а снятая один раз —
    только с той же стороны.
    """
    client.rpc(
        "add_auto_embedding",
        {
            "target_animal_id": animal_id,
            "new_embedding": embedding,
            "new_view": view,
        },
    ).execute()


def describe_rules(rules: AutoEnrollRules) -> str:
    """Строка для журнала при запуске."""
    return (
        f"уверенность от {rules.min_confidence:.0%}, "
        f"размер от {int(rules.min_area_px)} точек, "
        f"подтверждений {rules.min_sightings}"
    )
