"""
Кого считает система: скот.

Раньше здесь было два режима — ферма и стенд с людьми. Стенд себя не
оправдал: переключатель, который почти не трогают, требовал оговорок на
каждом экране и создавал целый класс ошибок вида «данные собраны в одном
режиме, а прочитаны в другом».

Модуль остался, потому что эти числа нужны в четырёх местах сразу —
детектору, обмеру, оценке веса и охране, — и держать их в одном месте
лучше, чем разносить по файлам.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SubjectProfile:
    """Что считаем, что охраняем и какие веса считаем правдоподобными."""

    # Классы модели, которые считаются животными: их считают, меряют,
    # узнают. Всё остальное из набора охраны идёт отдельной веткой
    subject_classes: frozenset[str]
    security_classes: frozenset[str]
    # Границы правдоподобия веса. Оценка вне них отбрасывается: пустая
    # клетка честнее коровы весом четыре килограмма
    min_weight_kg: float
    max_weight_kg: float
    # Отношение длины к ширине силуэта. За этими границами это либо не
    # животное, либо две слипшиеся в одну маску особи
    min_aspect: float
    max_aspect: float
    # С каких камер можно снимать силуэт. Сбоку площадь проекции зависит
    # от того, как животное повернулось, и с массой не связана
    measure_placements: frozenset[str]


LIVESTOCK_PROFILE = SubjectProfile(
    # COCO не знает ни козы, ни верблюда. cow ловит крупный рогатый и яков,
    # sheep — овец и коз вперемешку, horse — лошадей, ослов, мулов
    subject_classes=frozenset({"cow", "sheep", "horse"}),
    security_classes=frozenset({"person", "car", "truck", "bus", "motorcycle"}),
    min_weight_kg=20.0,
    max_weight_kg=1500.0,
    min_aspect=1.2,
    max_aspect=4.0,
    measure_placements=frozenset({"overhead"}),
)


def count_people() -> bool:
    """
    Считать ли людей наравне с животными.

    Нужно, пока фермы нет: проверить узнавание, вес и движение можно
    только на себе. Включается одной строкой в `.env`, по умолчанию
    выключено.

    Что при этом меняется, кроме списка классов:

      - охрана перестаёт работать. Человек не может быть одновременно
        подопечным и посторонним; если бы он остался и там, и там,
        тревога поднималась бы на каждого, кого система считает;
      - в поголовье попадают люди. Числа этого запуска к ферме
        отношения не имеют, и путать их с настоящими нельзя.

    Поэтому обе вещи сервис говорит вслух при запуске.
    """
    return os.environ.get("COUNT_PEOPLE", "0").strip().lower() in {"1", "true", "yes"}


def with_people(profile: SubjectProfile) -> SubjectProfile:
    """Тот же профиль, но человек — подопечный, а не посторонний."""
    return replace(
        profile,
        subject_classes=profile.subject_classes | {"person"},
        security_classes=profile.security_classes - {"person"},
        # Человек в полный рост сбоку вытянут сильнее любой коровы, и
        # прежняя верхняя граница отбрасывала бы половину его замеров
        max_aspect=max(profile.max_aspect, 5.5),
        # Мерить человека сбоку даже правильнее: рост от поворота не
        # меняется, а вид сверху его укорачивает
        measure_placements=profile.measure_placements | {"side"},
    )


def resolve() -> SubjectProfile:
    """Профиль, с которым работает этот запуск."""
    return with_people(LIVESTOCK_PROFILE) if count_people() else LIVESTOCK_PROFILE


def describe(profile: SubjectProfile) -> str:
    """Строка для журнала при запуске."""
    if "person" in profile.subject_classes:
        return (
            "СЧИТАЕМ ЛЮДЕЙ наравне с животными (COUNT_PEOPLE=1). "
            "Охрана при этом не работает, а поголовье включает людей — "
            "числа этого запуска не годятся для фермы"
        )
    return "считаем скот"


def weight_is_plausible(profile: SubjectProfile, kg: float | None) -> bool:
    """
    Похожа ли оценка на правду.

    Формула подбирается по контрольным взвешиваниям, и испорченная
    формула даёт правдоподобные с виду, но неверные числа. Границы ловят
    такое сразу.
    """
    if kg is None:
        return False
    return profile.min_weight_kg <= kg <= profile.max_weight_kg
