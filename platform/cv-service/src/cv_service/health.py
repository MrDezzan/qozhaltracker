"""
Нестандартное поведение животного: не ест, не двигается, пропало.

План целиком — `docs/PLAN_POVEDENIE.md`. Здесь живут решения, и только
они: данные приходят готовыми строками из базы, а тревоги пишет она же.
Разделение нарочное — так каждое правило можно проверить тестом, не
поднимая ни камеры, ни Postgres.

Устройство зовёт это раз в час. Не дашборд: открытая вкладка не должна
быть условием того, что болезнь заметили.
"""

from __future__ import annotations

import statistics
import threading
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Годность суток
# ---------------------------------------------------------------------------

# Сколько часов из суток камера должна была работать, чтобы по этим
# суткам вообще можно было о чём-то судить.
#
# Двенадцать — половина. Камера, проработавшая утро и упавшая к обеду,
# видела животное в самое деятельное время, и её данные чего-то стоят.
# Проработавшая два часа — не видела ничего.
#
# Число взято по здравому смыслу и должно быть проверено на настоящих
# сутках работы фермы. Оно вынесено сюда именно затем, чтобы его можно
# было поправить в одном месте.
MIN_ALIVE_HOURS = 12.0


@dataclass(frozen=True)
class CameraDay:
    """Сколько часов камера была жива в эти сутки."""

    camera_id: str
    day: str
    alive_hours: float
    # Размечена ли на этой камере кормушка. Корм считается только с
    # таких: живая камера над проходом ничего не говорит о том, ела ли
    # корова
    has_feeder: bool = False


@dataclass(frozen=True)
class UsableDays:
    """
    Какие сутки годятся для суждения — отдельно по каждому признаку.

    Раздельно, потому что признаки приходят с разных камер. Упавшая
    камера над кормовым столом не мешает считать путь, но делает
    бессмысленным разговор о кормлении.
    """

    movement: set[str] = field(default_factory=set)
    feeding: set[str] = field(default_factory=set)


def usable_days(camera_days: list[CameraDay]) -> UsableDays:
    """
    Сутки, по которым можно судить. Всё остальное — «не знаем».

    Часы РАЗНЫХ камер не складываются, и это главное здесь. Две камеры
    по семь часов — не четырнадцать часов наблюдения: они работали
    одновременно и обе молчали одни и те же семнадцать часов. Сложение
    объявило бы такие сутки годными, и всё стадо, не попавшее в кадр
    ночью, оказалось бы вялым.

    Поэтому берётся ЛУЧШАЯ камера, а не сумма.

    Текущих, ещё не кончившихся суток здесь не бывает: сетку дней
    обрезает база, миграция 0044. Судим только по тому, что кончилось.
    """
    movement: set[str] = set()
    feeding: set[str] = set()

    for row in camera_days:
        if row.alive_hours < MIN_ALIVE_HOURS:
            continue
        movement.add(row.day)
        if row.has_feeder:
            feeding.add(row.day)

    return UsableDays(movement=movement, feeding=feeding)


def day_source(camera_days: list[CameraDay], day: str) -> str:
    """
    Почему эти сутки годятся или нет — человеческими словами.

    Молчание без причины читается как поломка. На этом уже обжигались:
    счётчик записи стоял на нуле, и почему — нигде не было написано.
    """
    same_day = [row for row in camera_days if row.day == day]
    if not same_day:
        return "камеры в этот день не отчитывались вовсе"

    best = max(same_day, key=lambda row: row.alive_hours)
    if best.alive_hours >= MIN_ALIVE_HOURS:
        return (
            f"камер в работе: {len(same_day)}, лучшая была жива "
            f"{best.alive_hours:.0f} ч из 24"
        )

    return (
        f"камера работала {best.alive_hours:.0f} ч из 24 — меньше "
        f"{MIN_ALIVE_HOURS:.0f}, судить по таким суткам нельзя"
    )


# ---------------------------------------------------------------------------
# Нормы
# ---------------------------------------------------------------------------

# Меньше этого числа дней собственная норма ничего не значит.
#
# По двум дням «норма» — это просто один из них, и любое отклонение от
# неё случайно. Три дня — минимум, при котором медиана хоть что-то
# отбрасывает.
MIN_DAYS_FOR_BASELINE = 3

# Меньше этого времени в кадре метры не с чем соотнести.
#
# Пять минут. Животное, попавшее в кадр на минуту, «прошло мало» — но
# это ничего не говорит о животном, только о камере.
MIN_SECONDS_VISIBLE = 300.0


@dataclass(frozen=True)
class AnimalDay:
    """Сутки одного животного — то, что посчитала база."""

    animal_id: str
    day: str
    meters: float
    seconds_visible: float
    # Дальше — ТОЛЬКО ИМЕНОВАННЫЕ. Раньше их можно было передать по
    # порядку, и добавление поля в середину молча сдвигало чужие
    # значения: `feeder_visits` встал на место `water_visits`, счётчик
    # воды обнулился, и тесты поймали это одной странной тревогой.
    # Позиционно такую ошибку не увидеть — типы совпадают
    feeder_seconds: float = field(default=0.0, kw_only=True)
    # Сколько раз подошёл к корму. Не то же, что время у корма: животное
    # может простоять долго, подойдя однажды, — и наоборот. Владельцу
    # понятнее число подходов, а болезнь чаще видна именно по нему
    feeder_visits: int = field(default=0, kw_only=True)
    water_visits: int = field(default=0, kw_only=True)

    @property
    def can_judge_movement(self) -> bool:
        """
        Можно ли по этим суткам судить о движении.

        Здесь разводятся две ситуации, которые в базе выглядят почти
        одинаково — ноль метров:

          - больная лежит в углу: секунд в кадре много;
          - не узнали или ушла из кадра: секунд ноль.

        Первое — про животное. Второе — про узнавание, и объявлять его
        болезнью значит поднимать ложную тревогу. После трёх подряд
        человек перестаёт открывать раздел совсем.
        """
        return self.seconds_visible >= MIN_SECONDS_VISIBLE


def own_baseline(days: list[AnimalDay], field_name: str) -> float | None:
    """
    Своя норма животного — медиана по прошлым дням. None — нормы нет.

    Медиана, а не среднее: один день, когда животное простояло у камеры
    весь день, сдвинул бы среднее так, что все остальные дни стали бы
    «ниже нормы».

    Сегодняшний день сюда не передаётся. Иначе показатель сравнивался бы
    сам с собой, и отклонение всегда выходило бы меньше настоящего.
    """
    values = [float(getattr(one, field_name)) for one in days]
    if len(values) < MIN_DAYS_FOR_BASELINE:
        return None
    return statistics.median(values)


def herd_median(rows: list[AnimalDay], field_name: str) -> float | None:
    """
    Норма стада за те же сутки. None — сравнивать не с кем.

    Одно животное стадом не считается: отношение вышло бы единицей, и
    просадка всего загона никогда не была бы замечена — а именно она
    отличает жару от болезни.
    """
    values = [float(getattr(one, field_name)) for one in rows]
    if len(values) < 2:
        return None
    return statistics.median(values)


def ratio(value: float, baseline: float | None) -> float | None:
    """
    Во сколько раз меньше или больше нормы. None — сказать нечего.

    Ноль при живой норме — это НЕ None. Ноль метров при обычных
    шестистах — самый сильный сигнал, который вообще бывает, и
    промолчать здесь значило бы промолчать ровно там, где надо кричать.
    """
    if baseline is None or baseline <= 0:
        return None
    return value / baseline


# ---------------------------------------------------------------------------
# Правила
# ---------------------------------------------------------------------------

# Насколько сильно животное должно выбиться, чтобы это стоило показывать.
#
# Треть — не круглое число ради красоты. День на день не приходится:
# животное могло больше времени провести вне кадра, могла быть жара, мог
# быть перегон. Разброс в 10–20 % — обычный день, и помечать его значит
# приучить человека не смотреть на пометки вовсе.
LOW_RATIO = 0.67
HIGH_RATIO = 1.5

# Сколько дней подряд отклонение должно держаться, чтобы о нём говорить.
#
# Один день не значит ничего, два подряд — уже система. Исключение —
# сочетание двух признаков сразу: оно говорит с первого дня.
DAYS_TO_SPEAK = 2

# Меньше этого числа эталонов — животное узнаётся ненадёжно, и его нули
# это нули УЗНАВАНИЯ, а не поведения. Совпадает с MIN_TO_RECOGNISE в
# дашборде: там по этому же числу решают, показывать ли «узнаётся»
MIN_EMBEDDINGS_TO_JUDGE = 4

# Какая доля стада должна просесть, чтобы личные тревоги отменились.
#
# Жара, перегон, смена корма, чужие люди в загоне — стадо проседает
# целиком. Болезни у всех разом не бывает, и двести личных тревог в
# такой день — худшее, что система может сделать.
HERD_TROUBLE_SHARE = 1.0 / 3.0

# Меньше этого числа голов доля стада ничего не значит: на трёх головах
# «треть стада» — это одна корова, и она как раз может быть больна
MIN_HERD_FOR_SHARE = 5

# Сколько раз в сутки животное должно подходить к корму ОБЫЧНО, чтобы
# сегодняшний ноль что-то значил.
#
# При норме в один подход ноль — это с равным успехом и пропущенный
# приём пищи, и один незамеченный визит. При норме от двух ноль уже
# говорит сам за себя.
MIN_MEALS_TO_JUDGE = 2


@dataclass(frozen=True)
class AnimalHistory:
    """Всё, что нужно знать о животном, чтобы судить о вчерашних сутках."""

    animal_id: str
    label: str
    # По возрастанию дат. Последний день — тот, о котором судим
    days: list[AnimalDay]
    # Сколько у животного эталонов. Мало — не судим вовсе
    embeddings: int
    usable_movement: set[str] = field(default_factory=set)
    usable_feeding: set[str] = field(default_factory=set)
    # Доля стада, просевшая в тот же день
    herd_share_low: float = 0.0


@dataclass(frozen=True)
class Finding:
    """
    Одно отклонение — то, что станет тревогой.

    Числа лежат рядом с выводом нарочно. Вердикт без чисел нечем
    проверить, и первое же несогласие человека с системой кончается тем,
    что он ей не верит.
    """

    animal_id: str
    kind: str
    severity: str
    title: str
    detail: str
    value: float | None = None
    baseline: float | None = None
    days_in_row: int = 1


def _streak(days: list[AnimalDay], test) -> int:
    """Сколько последних суток подряд выполняется условие."""
    count = 0
    for one in reversed(days):
        if not test(one):
            break
        count += 1
    return count


def judge(history: AnimalHistory) -> list[Finding]:
    """
    Что не так с животным. Пустой список — сказать нечего.

    Пустой список чаще всего и есть правильный ответ. Система, которая
    находит отклонение у каждого второго, бесполезна ровно так же, как
    молчащая.
    """
    days = history.days
    if len(days) < MIN_DAYS_FOR_BASELINE:
        # Норма не построена: сравнивать не с чем
        return []

    today = days[-1]
    earlier = days[:-1]

    # --- глухие заслонки: при них не судим вообще ---

    if history.embeddings < MIN_EMBEDDINGS_TO_JUDGE:
        return []

    if history.herd_share_low >= HERD_TROUBLE_SHARE:
        # Просело всё стадо. Это про загон, а не про животное
        return []

    # Годятся ли эти сутки — отдельно по движению и по корму: признаки
    # приходят с разных камер, и упавшая камера над кормовым столом не
    # мешает считать путь.
    #
    # Дальше эти два флага проверяет КАЖДОЕ правило по отдельности, и
    # общей заслонки «обе камеры лежали — молчим» здесь нет намеренно.
    # Она тут была, и мутационная проверка показала, что её можно
    # удалить, не сломав ни одного теста: все ветки ниже уже закрыты.
    # Заслонка, которая ничего не делает, хуже её отсутствия — следующий
    # человек на неё понадеется.
    can_move = today.day in history.usable_movement
    can_feed = today.day in history.usable_feeding

    # --- нормы строятся только по годным суткам ---

    move_days = [one for one in earlier if one.day in history.usable_movement]
    feed_days = [one for one in earlier if one.day in history.usable_feeding]

    seen_norm = own_baseline(move_days, "seconds_visible")
    meters_norm = own_baseline(
        [one for one in move_days if one.can_judge_movement], "meters"
    )
    feeder_norm = own_baseline(feed_days, "feeder_seconds")
    meals_norm = own_baseline(feed_days, "feeder_visits")
    water_norm = own_baseline(feed_days, "water_visits")

    # «Не подходил к корму вовсе» — не «меньше обычного», а ноль при
    # известной норме. Это ближе к правилу про воду, чем к правилу про
    # количество корма, и говорить об этом надо сразу, не дожидаясь
    # второго дня.
    #
    # Когда сработало, обычные «мало корма» подавляются: ноль и так
    # означает «мало», и две тревоги об одном и том же в один день
    # только мешают.
    missed_meals = (
        can_feed
        and meals_norm is not None
        and meals_norm >= MIN_MEALS_TO_JUDGE
        and today.feeder_visits == 0
    )

    found: list[Finding] = []

    # --- не видели ---
    # Проверяется ПЕРВЫМ и отменяет разговор о вялости: ноль метров у
    # животного, которого не видели, — это про камеру, а не про него

    normally_seen = seen_norm is not None and seen_norm >= MIN_SECONDS_VISIBLE
    if can_move and normally_seen and not today.can_judge_movement:
        row = _streak(
            [one for one in days if one.day in history.usable_movement],
            lambda one: not one.can_judge_movement,
        )
        return [
            Finding(
                animal_id=history.animal_id,
                kind="not_seen",
                severity="danger" if row >= DAYS_TO_SPEAK else "warning",
                title=f"{history.label}: не видели {'двое суток' if row >= DAYS_TO_SPEAK else 'сутки'}",
                detail=(
                    f"Обычно попадает в кадр на {seen_norm / 60:.0f} мин в сутки, "
                    f"вчера — {today.seconds_visible / 60:.0f}. Проверьте, в загоне "
                    "ли она. Если в загоне — камера её не узнаёт, допишите ракурсы"
                ),
                value=today.seconds_visible,
                baseline=seen_norm,
                days_in_row=row,
            )
        ]

    # --- движение и корм ---

    # Одно определение «мало» на все дни, включая сегодняшний.
    #
    # Раньше их было два: одно для сегодня, другое для подсчёта дней
    # подряд. Оба проверяли годность суток, и мутационная проверка
    # показала цену этого: любую из копий можно было убрать, не сломав
    # ни одного теста. Два места, где решается один вопрос, — это
    # место, где они однажды разойдутся

    def move_low_on(one: AnimalDay) -> bool:
        if one.day not in history.usable_movement or not one.can_judge_movement:
            return False
        value = ratio(one.meters, meters_norm)
        return value is not None and value < LOW_RATIO

    def feed_low_on(one: AnimalDay) -> bool:
        if one.day not in history.usable_feeding:
            return False
        value = ratio(one.feeder_seconds, feeder_norm)
        return value is not None and value < LOW_RATIO

    move_low = move_low_on(today)
    feed_low = feed_low_on(today)

    # Отношения нужны только для текста тревоги: человеку показывают
    # числа, по которым сделан вывод
    move_ratio = ratio(today.meters, meters_norm) if can_move else None

    if move_low and feed_low and not missed_meals:
        # Два признака сразу весят больше, чем один дважды. Мало
        # двигалась — могла лежать в тени. Мало двигалась И мало ела —
        # это уже про животное, а не про погоду
        row = _streak(days, lambda one: move_low_on(one) and feed_low_on(one))
        found.append(
            Finding(
                animal_id=history.animal_id,
                kind="low_both",
                severity="danger" if row >= DAYS_TO_SPEAK else "warning",
                title=f"{history.label}: мало ест и мало двигается",
                detail=(
                    f"Вчера прошла {today.meters:.0f} м при обычных "
                    f"{meters_norm:.0f}, у корма была {today.feeder_seconds / 60:.0f} "
                    f"мин при обычных {feeder_norm / 60:.0f}. Два признака сразу — "
                    "это повод позвать ветврача"
                ),
                value=today.meters,
                baseline=meters_norm,
                days_in_row=row,
            )
        )
    else:
        # Порознь — только если держится второй день
        if move_low:
            row = _streak(days, move_low_on)
            if row >= DAYS_TO_SPEAK:
                found.append(
                    Finding(
                        animal_id=history.animal_id,
                        kind="low_activity",
                        severity="warning",
                        title=f"{history.label} двигается меньше обычного",
                        detail=(
                            f"{row}-й день подряд. Вчера прошла {today.meters:.0f} м "
                            f"при обычных {meters_norm:.0f}. Посмотрите, встаёт ли "
                            "она и нет ли хромоты"
                        ),
                        value=today.meters,
                        baseline=meters_norm,
                        days_in_row=row,
                    )
                )

        if feed_low and not missed_meals:
            row = _streak(days, feed_low_on)
            if row >= DAYS_TO_SPEAK:
                found.append(
                    Finding(
                        animal_id=history.animal_id,
                        kind="low_feeding",
                        severity="warning",
                        title=f"{history.label} мало подходит к корму",
                        detail=(
                            f"{row}-й день подряд. Вчера у корма была "
                            f"{today.feeder_seconds / 60:.0f} мин при обычных "
                            f"{feeder_norm / 60:.0f}. Посмотрите, ест ли вообще"
                        ),
                        value=today.feeder_seconds,
                        baseline=feeder_norm,
                        days_in_row=row,
                    )
                )

    # --- не подходил к корму ---

    if missed_meals:
        row = _streak(
            [one for one in days if one.day in history.usable_feeding],
            lambda one: one.feeder_visits == 0,
        )
        found.append(
            Finding(
                animal_id=history.animal_id,
                kind="few_meals",
                severity="danger" if row >= DAYS_TO_SPEAK else "warning",
                title=(
                    f"{history.label} не подходила к корму "
                    f"{'вторые сутки' if row >= DAYS_TO_SPEAK else 'сутки'}"
                ),
                detail=(
                    f"Обычно подходит {meals_norm:.0f} раза в сутки, вчера — "
                    "ни разу. Посмотрите, ест ли вообще и не оттирают ли её "
                    "от кормушки"
                ),
                value=0.0,
                baseline=meals_norm,
                days_in_row=row,
            )
        )

    # --- вода ---
    # Строже корма: сутки без воды опаснее суток без корма. Но подходы к
    # поилке короткие и распознаются хуже, поэтому правило включается,
    # только если животное РАНЬШЕ туда ходило. Отсутствие данных не есть
    # отсутствие питья

    if can_feed and water_norm is not None and water_norm > 0 and today.water_visits == 0:
        found.append(
            Finding(
                animal_id=history.animal_id,
                kind="no_water",
                severity="danger",
                title=f"{history.label} сутки не подходила к воде",
                detail=(
                    f"Обычно подходит {water_norm:.0f} раза в сутки. Проверьте "
                    "поилку: не перекрыта ли, есть ли давление"
                ),
                value=0.0,
                baseline=water_norm,
            )
        )

    # --- охота ---
    # Высокая активность никогда не выдаётся за нездоровье: иначе система
    # позовёт ветврача к здоровой корове ровно в тот день, когда её надо
    # осеменять

    if can_move and move_ratio is not None and move_ratio > HIGH_RATIO:
        row = _streak(
            days,
            lambda one: (
                one.day in history.usable_movement
                and one.can_judge_movement
                and (ratio(one.meters, meters_norm) or 0) > HIGH_RATIO
            ),
        )
        if row >= DAYS_TO_SPEAK:
            found.append(
                Finding(
                    animal_id=history.animal_id,
                    kind="heat",
                    severity="info",
                    title=f"{history.label} двигается больше обычного",
                    detail=(
                        f"Вчера прошла {today.meters:.0f} м при обычных "
                        f"{meters_norm:.0f}. У коров так бывает в охоте — "
                        "возможно, пора осеменять"
                    ),
                    value=today.meters,
                    baseline=meters_norm,
                    days_in_row=row,
                )
            )

    return found


def judge_herd(share_low: float, animals: int) -> Finding | None:
    """
    Тревога на всю ферму вместо личных.

    Когда просела треть стада, чинить надо загон, а не корову. Одна
    строка про ферму полезнее двухсот про животных — и, в отличие от
    них, правдива.
    """
    if animals < MIN_HERD_FOR_SHARE:
        return None
    if share_low < HERD_TROUBLE_SHARE:
        return None

    return Finding(
        animal_id="",
        kind="herd_low",
        severity="warning",
        title="Стадо вчера двигалось меньше обычного",
        detail=(
            f"Ниже своей нормы {share_low * 100:.0f} % животных. Это бывает от "
            "жары, перегона или смены корма. Проверьте воду, вентиляцию и "
            "корм. Личные тревоги за этот день не поднимались"
        ),
        value=share_low,
    )


# ---------------------------------------------------------------------------
# Сборка: строки базы → истории → тревоги
# ---------------------------------------------------------------------------


def herd_share_low(low: int, total: int) -> float:
    """Доля стада ниже нормы. Пустое стадо — ноль, а не деление на ноль."""
    if total <= 0:
        return 0.0
    return low / total


def _to_day(raw: dict) -> AnimalDay:
    return AnimalDay(
        animal_id=str(raw["animal_id"]),
        day=str(raw["day"]),
        meters=float(raw.get("meters") or 0.0),
        seconds_visible=float(raw.get("seconds_visible") or 0.0),
        feeder_seconds=float(raw.get("feeder_seconds") or 0.0),
        feeder_visits=int(raw.get("feeder_visits") or 0),
        water_visits=int(raw.get("water_visits") or 0),
    )


def build_histories(
    day_rows: list[dict],
    animal_rows: list[dict],
    camera_rows: list[dict],
) -> list[AnimalHistory]:
    """
    Строки базы — в истории животных.

    Дни сортируются по возрастанию, и это не косметика: последний день —
    тот, о котором судят, а предыдущие идут в норму. Перепутанный
    порядок означал бы, что норму строят по будущему, а судят по
    прошлому — и никакой ошибки при этом не видно, просто выводы неверны.
    """
    usable = usable_days([
        CameraDay(
            camera_id=str(one["camera_id"]),
            day=str(one["day"]),
            alive_hours=float(one.get("alive_hours") or 0.0),
            has_feeder=bool(one.get("has_feeder")),
        )
        for one in camera_rows
    ])

    by_animal: dict[str, list[AnimalDay]] = {}
    known = {str(one["animal_id"]) for one in animal_rows}
    for raw in day_rows:
        animal_id = str(raw["animal_id"])
        # Животное могли удалить, пока шла проверка
        if animal_id not in known:
            continue
        by_animal.setdefault(animal_id, []).append(_to_day(raw))

    histories = []
    for one in animal_rows:
        animal_id = str(one["animal_id"])
        days = sorted(by_animal.get(animal_id, []), key=lambda d: d.day)
        histories.append(
            AnimalHistory(
                animal_id=animal_id,
                label=str(one.get("label") or ""),
                days=days,
                embeddings=int(one.get("embeddings") or 0),
                usable_movement=usable.movement,
                usable_feeding=usable.feeding,
            )
        )
    return histories


def can_judge(camera_rows: list[dict]) -> bool:
    """
    Было ли вообще по чему судить в этот раз.

    Отличает «проверили, всё хорошо» от «проверить не смогли». Разница
    не academic: пустой список находок закрывает ВСЕ открытые тревоги
    по здоровью, а проверка идёт раз в час.

    Как это ломалось. С полуночи до часа дня годных суток нет ни одних:
    вчерашние ушли за горизонт нормы, сегодняшние не кончились. Находок
    ноль, и каждый час ночи все открытые тревоги закрывались заново —
    около тринадцати раз за ночь. Тревога «не видели двое суток»,
    поднятая вечером, к утру исчезала, и хозяин её не видел никогда.

    Поэтому: нет ни одних годных суток — тревоги не трогаем совсем.
    Открытая тревога, о которой нечего сказать нового, должна остаться
    открытой.
    """
    camera_days = [
        CameraDay(
            camera_id=str(one["camera_id"]),
            day=str(one["day"]),
            alive_hours=float(one.get("alive_hours") or 0.0),
            has_feeder=bool(one.get("has_feeder")),
        )
        for one in camera_rows
    ]
    return bool(usable_days(camera_days).movement)


def run_check(
    day_rows: list[dict],
    animal_rows: list[dict],
    camera_rows: list[dict],
) -> list[Finding]:
    """
    Вся проверка целиком. Пустой список — на ферме всё в порядке.

    ВАЖНО: пустой список означает «всё в порядке» только вместе с
    `can_judge() == True`. Сам по себе он неотличим от «судить не по
    чему», а последствия у них противоположные.

    Доля просевшего стада считается ДО личных выводов и передаётся в
    каждый из них. Иначе получилось бы двести тревог в жаркий день:
    каждое животное по отдельности выглядит вялым, и только все вместе
    объясняют, что дело в погоде.
    """
    histories = build_histories(day_rows, animal_rows, camera_rows)
    if not histories:
        return []

    # Первый проход — без оглядки на стадо, только чтобы сосчитать, у
    # скольких просело движение
    low = sum(
        1
        for one in histories
        if any(found.kind in ("low_activity", "low_both") for found in judge(one))
    )

    # На малом стаде доля не значит ничего, и молчать по ней нельзя.
    #
    # Ловушка, которую поймал тест: на ферме из двух голов одна больная —
    # это «половина стада». Личные тревоги гасились как общая просадка, а
    # стадная не поднималась, потому что стадо мало. Система умолкала
    # ровно там, где должна была говорить.
    #
    # Порог один и тот же для обеих сторон — иначе они снова разойдутся
    share = (
        herd_share_low(low, len(histories))
        if len(histories) >= MIN_HERD_FOR_SHARE
        else 0.0
    )

    herd = judge_herd(share, len(histories))
    if herd is not None:
        # Просело стадо: личных тревог за этот день не поднимаем вовсе
        return [herd]

    found: list[Finding] = []
    for one in histories:
        with_herd = AnimalHistory(
            animal_id=one.animal_id,
            label=one.label,
            days=one.days,
            embeddings=one.embeddings,
            usable_movement=one.usable_movement,
            usable_feeding=one.usable_feeding,
            herd_share_low=share,
        )
        found.extend(judge(with_herd))

    return found


# ---------------------------------------------------------------------------
# Поток проверки
# ---------------------------------------------------------------------------

# Раз в час. Чаще незачем: выводы делаются по завершённым суткам, и за
# десять минут ничего не меняется. Реже — тревога о пропавшем животном
# опоздает на полдня
CHECK_INTERVAL_S = 3600.0

# Через сколько считать в первый раз после запуска.
#
# Не сразу: устройство только что включилось, ему надо подняться,
# подключиться и прочитать камеры. Но и не через час — иначе перезапуск
# в полдень означает, что до вечера тревог не будет вовсе, а перезапуск
# случается каждый раз, когда чинят камеру
FIRST_CHECK_S = 120.0


def next_run_delay(runs: int) -> float:
    """Сколько ждать перед следующей проверкой."""
    return FIRST_CHECK_S if runs == 0 else CHECK_INTERVAL_S


class HealthWatcher(threading.Thread):
    """
    Считает поведение раз в час.

    Отдельным потоком по той же причине, что зоны и запись: запрос по
    сети не должен останавливать обработку видео.

    Живёт на устройстве, а не в дашборде. Открытая вкладка не должна
    быть условием того, что болезнь заметили: хозяин заходит на сайт
    раз в день, а корова заболевает без расписания.
    """

    def __init__(
        self,
        check,
        interval_s: float = CHECK_INTERVAL_S,
        first_s: float = FIRST_CHECK_S,
    ):
        super().__init__(name="health", daemon=True)
        self._check = check
        self._interval_s = interval_s
        self._first_s = first_s
        self._stopping = threading.Event()
        self.runs = 0

    def run(self) -> None:
        # Ожидание через событие, а не sleep: иначе остановка висела бы
        # до конца часа, и Ctrl+C выглядел бы как зависание
        if self._stopping.wait(self._first_s):
            return

        while not self._stopping.is_set():
            try:
                self._check()
            except Exception as exc:  # noqa: BLE001 — причина уходит в журнал
                # Связь рвётся, база отвечает не сразу. Упавший поток
                # означал бы, что проверки прекратились до перезапуска
                # устройства, и никто об этом не узнает
                print(f"проверка поведения не выполнена: {exc}")
            self.runs += 1
            self._stopping.wait(self._interval_s)

    def stop(self) -> None:
        self._stopping.set()
