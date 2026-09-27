from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import cv2

from cv_service.detector import Detection

CROP_BUCKET = "crops"
DEFAULT_QUALITY = 85
# Слишком мелкая рамка — животное далеко, для распознавания бесполезно
MIN_CROP_SIDE = 64
# Сколько ждать, прежде чем считать трек завершённым
DEFAULT_TRACK_TIMEOUT_S = 20.0


def crops_enabled() -> bool:
    """Сбор кадров включается отдельно от распознавания."""
    return os.environ.get("COLLECT_CROPS", "1").strip().lower() in {"1", "true", "yes"}


# Резкость, выше которой кадр считается вполне чётким.
#
# Дисперсия лапласиана: у смазанного кадра перепадов яркости почти нет,
# у чёткого — много. Число подобрано по кадрам с обычной камеры и
# работает как потолок, а не как порог: смазанный кадр не отбрасывается,
# он лишь проигрывает чёткому при выборе лучшего.
#
# Отбрасывать нельзя. Животное могло всю дорогу идти быстро, и тогда все
# кадры смазаны — а опознать его всё равно надо.
SHARP_ENOUGH = 100.0

# К какой ширине приводить кадр перед замером резкости.
#
# Без этого мерить бессмысленно: дисперсия лапласиана зависит от размера,
# и крупное смазанное животное набрало бы больше, чем мелкое чёткое.
# Приведение к общей ширине делает числа сравнимыми между собой.
SHARP_PROBE_WIDTH = 128


def sharpness(image) -> float:
    """
    Насколько кадр чёткий. Больше — лучше, ноль — сплошная заливка.

    Стоит доли миллисекунды и окупается дважды: смазанный кадр и вектор
    даёт негодный, и время на него тратится то же самое — секунда-две.
    """
    try:
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return 0.0

        scale = SHARP_PROBE_WIDTH / float(width)
        small = (
            cv2.resize(
                image,
                (SHARP_PROBE_WIDTH, max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
            if scale < 1.0
            else image
        )
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        # Резкость — уточнение, а не условие работы. Не измерилась —
        # считаем кадр обычным и выбираем по размеру с уверенностью
        return SHARP_ENOUGH


def crop_score(area: float, confidence: float, sharp: float) -> float:
    """
    Насколько кадр хорош для опознания.

    Крупный и уверенный — значит, животное видно. Чёткий — значит, видно
    ЧТО именно: масть, отметины, форму головы. Смазанный кадр той же
    величины даёт вектор, под который потом подходит кто угодно.
    """
    clarity = min(1.0, sharp / SHARP_ENOUGH) if SHARP_ENOUGH > 0 else 1.0
    return area * confidence * clarity


@dataclass
class BestCrop:
    """Лучший кадр одного трека: крупный, уверенный и чёткий."""

    track_id: int
    image: object
    confidence: float
    area: float
    last_seen_at: float
    sharpness: float = SHARP_ENOUGH

    @property
    def score(self) -> float:
        return crop_score(self.area, self.confidence, self.sharpness)


@dataclass
class CropCollector:
    """
    Копит по одному лучшему кадру на каждый трек.

    Сохранять каждый кадр нельзя — объём тот же, что у видео. Один кадр
    на визит животного даёт материал и для именования, и для будущего
    обучения модели.
    """

    track_timeout_s: float = DEFAULT_TRACK_TIMEOUT_S
    # Через сколько секунд наблюдения кадр уже годится для опознания.
    # Ждать конца трека нельзя: имя нужно показать, пока животное в кадре.
    identify_after_s: float = 3.0
    _best: dict[int, BestCrop] = field(default_factory=dict)
    _first_seen: dict[int, float] = field(default_factory=dict)

    def add(self, frame, detections: list[Detection], now: float | None = None) -> None:
        moment = time.monotonic() if now is None else now
        height, width = frame.shape[:2]

        for detection in detections:
            x1, y1, x2, y2 = (int(v) for v in detection.bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)

            crop_w, crop_h = x2 - x1, y2 - y1
            if crop_w < MIN_CROP_SIDE or crop_h < MIN_CROP_SIDE:
                continue

            area = float(crop_w * crop_h)
            patch = frame[y1:y2, x1:x2]
            # Резкость меряем один раз: она нужна и для сравнения с
            # прежним лучшим, и для самого кадра, если он победит
            sharp = sharpness(patch)
            score = crop_score(area, detection.confidence, sharp)

            existing = self._best.get(detection.track_id)
            if existing is not None:
                existing.last_seen_at = moment
                if existing.score >= score:
                    continue

            self._first_seen.setdefault(detection.track_id, moment)
            self._best[detection.track_id] = BestCrop(
                track_id=detection.track_id,
                image=patch.copy(),
                confidence=detection.confidence,
                area=area,
                last_seen_at=moment,
                sharpness=sharp,
            )

    def ready_to_identify(
        self, known: set[int], now: float | None = None
    ) -> list[BestCrop]:
        """
        Кадры треков, которых уже видно достаточно долго, чтобы опознать,
        но которые ещё не опознаны. Кадры остаются в работе — трек живой.
        """
        moment = time.monotonic() if now is None else now
        return [
            crop
            for track_id, crop in self._best.items()
            if track_id not in known
            and moment - self._first_seen.get(track_id, moment) >= self.identify_after_s
        ]

    def refresh(self, track_id: int) -> None:
        """
        Забыть накопленный лучший кадр, оставив сам трек живым.

        Нужно, когда опознание вышло спорным и мы собираемся спросить
        ещё раз. Без этого второй заход считал бы вектор ПО ТОМУ ЖЕ
        кадру и получил бы тот же ответ — то есть просто потратил бы
        ещё две секунды впустую.

        `_first_seen` намеренно не трогаем: трек не начинается заново,
        и ждать ещё три секунды перед новой попыткой незачем.
        """
        self._best.pop(track_id, None)

    def take_finished(self, now: float | None = None) -> list[BestCrop]:
        """Треки, которых давно не видно, считаем завершёнными."""
        moment = time.monotonic() if now is None else now
        finished = [
            crop
            for crop in self._best.values()
            if moment - crop.last_seen_at >= self.track_timeout_s
        ]
        for crop in finished:
            del self._best[crop.track_id]
            self._first_seen.pop(crop.track_id, None)
        return finished

    def flush(self) -> list[BestCrop]:
        finished = list(self._best.values())
        self._best.clear()
        self._first_seen.clear()
        return finished


# Сколько раз подряд разные кадры должны назвать одного и того же,
# чтобы спорное опознание считалось решённым.
#
# Двух достаточно. Три давали бы заметно меньше ошибок, но стоили бы
# ещё двух-четырёх секунд, а животное к тому времени уходит из кадра —
# и вместо неверной клички получилась бы никакая.
AGREE_NEEDED = 2


@dataclass
class IdentificationTracker:
    """
    Помнит, кого уже пробовали опознать, сколько раз и с каким исходом.

    Раньше один неудачный поиск помечал трек как неопознаваемый навсегда.
    Но животное могло стоять к камере боком или наполовину за столбом,
    а через полминуты повернуться. Поэтому попытку повторяем несколько
    раз с паузой — и только потом отступаем.

    Отдельно живёт голосование. Когда кандидаты идут вплотную, назвать
    ближайшего — то же самое, что подбросить монету, и неверная кличка
    на кадре разрушает доверие быстрее, чем её отсутствие. В таком
    случае считаем вектор ещё раз по ДРУГОМУ кадру того же трека и
    называем животное, только если оба кадра сошлись на одном.

    Цена платится там, где она нужна: уверенное опознание называется
    сразу, по одному кадру, как и раньше.
    """

    max_attempts: int = 4
    retry_after_s: float = 15.0
    # Пауза перед переспросом, когда кандидаты близки.
    #
    # Короткая нарочно: животное в кадре, оно движется, и через секунду
    # это уже другой ракурс. Ждать пятнадцать секунд, как после полной
    # неудачи, значит почти всегда упустить животное
    doubt_retry_after_s: float = 1.0
    _attempts: dict[int, int] = field(default_factory=dict)
    _last_try: dict[int, float] = field(default_factory=dict)
    _resolved: set[int] = field(default_factory=set)
    _ballots: dict[int, list[str]] = field(default_factory=dict)
    _voted: set[int] = field(default_factory=set)

    def skip(self, now: float) -> set[int]:
        """Треки, которые сейчас пробовать не надо."""
        skipped = set(self._resolved)
        for track_id, attempts in self._attempts.items():
            if attempts >= self.max_attempts:
                skipped.add(track_id)
                continue

            # Спорный трек переспрашиваем быстро, безнадёжный — не скоро
            pause = (
                self.doubt_retry_after_s
                if self._ballots.get(track_id)
                else self.retry_after_s
            )
            if now - self._last_try.get(track_id, 0.0) < pause:
                skipped.add(track_id)
        return skipped

    def record_attempt(self, track_id: int, now: float) -> None:
        self._attempts[track_id] = self._attempts.get(track_id, 0) + 1
        self._last_try[track_id] = now

    def vote(self, track_id: int, candidate: str) -> str | None:
        """
        Голос за кандидата по спорному кадру.

        Возвращает кличку животного, когда голосов за одного набралось
        достаточно, и None — когда надо спросить ещё раз.
        """
        ballot = self._ballots.setdefault(track_id, [])
        ballot.append(candidate)
        if ballot.count(candidate) >= AGREE_NEEDED:
            return candidate
        return None

    def votes(self, track_id: int) -> int:
        """Сколько спорных кадров уже посчитано. Для журнала."""
        return len(self._ballots.get(track_id, []))

    def record_success(self, track_id: int, by_vote: bool = False) -> None:
        self._resolved.add(track_id)
        self._ballots.pop(track_id, None)
        if by_vote:
            self._voted.add(track_id)

    def was_voted(self, track_id: int) -> bool:
        """
        Кличку этого трека добыли переспросом, а не узнали сразу.

        Помнится отдельно, потому что бюллетени стираются в момент
        успеха: спросить «сколько было голосов» после того, как трек
        назван, уже невозможно. А знать это надо позже — при закрытии
        трека решается, класть ли кадр в эталоны, и добытому с сомнением
        там не место.
        """
        return track_id in self._voted

    def forget(self, track_id: int) -> None:
        self._attempts.pop(track_id, None)
        self._last_try.pop(track_id, None)
        self._resolved.discard(track_id)
        self._ballots.pop(track_id, None)
        self._voted.discard(track_id)


def encode_crop(image, quality: int = DEFAULT_QUALITY) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Не удалось закодировать вырезанный кадр в JPEG")
    return buffer.tobytes()


def crop_path(farm_id: str, camera_id: str, track_id: int, moment: float) -> str:
    """
    Уникальный путь: кадры не перезаписываются, в отличие от снимков —
    каждый след животного нужен и для истории, и для датасета.
    """
    stamp = int(moment * 1000)
    return f"{farm_id}/{camera_id}/{stamp}-{track_id}.jpg"


def upload_crop(client, farm_id: str, camera_id: str, crop: BestCrop) -> str:
    path = crop_path(farm_id, camera_id, crop.track_id, time.time())
    client.storage.from_(CROP_BUCKET).upload(
        path=path,
        file=encode_crop(crop.image),
        file_options={"content-type": "image/jpeg"},
    )
    return path


# Косинусное расстояние, ниже которого считаем это тем же животным.
# Строже — будет плодить дубликаты, мягче — путать разных особей.
DEFAULT_MATCH_THRESHOLD = 0.35


def match_threshold() -> float:
    """
    Насколько далёким может быть эталон, чтобы его ещё считали своим.

    Вынесено в настройку не для тонкой подстройки, а потому что порог
    зависит от модели и от того, кого снимаем. MegaDescriptor обучен на
    животных; на людях его расстояния другие, и подходящее значение
    можно узнать только замером на месте — числа в журнале для того и
    печатаются.
    """
    raw = os.environ.get("REID_THRESHOLD", "").strip()
    try:
        return float(raw) if raw else DEFAULT_MATCH_THRESHOLD
    except ValueError:
        return DEFAULT_MATCH_THRESHOLD


# Насколько лучший должен опережать следующего, чтобы назвать кличку.
#
# Это важнее самого расстояния. Если два животных похожи на кадр
# одинаково, ближайший из них — результат подбрасывания монеты, и
# показать его кличку хуже, чем не показать ничего: неверная кличка
# на кадре разрушает доверие ко всей системе быстрее, чем её отсутствие.
DEFAULT_MIN_MARGIN = 0.05


def min_margin() -> float:
    raw = os.environ.get("REID_MIN_MARGIN", "").strip()
    try:
        return float(raw) if raw else DEFAULT_MIN_MARGIN
    except ValueError:
        return DEFAULT_MIN_MARGIN


@dataclass(frozen=True)
class Match:
    """
    Итог поиска по базе эталонов.

    Три состояния, и их нельзя сводить к одному «не узнали»:

      - `animal_id` заполнен — узнали уверенно;
      - `ambiguous` — кто-то похож, но сразу несколько, и назвать одного
        значило бы гадать;
      - ни того, ни другого — рядом никого нет, животное незнакомое.

    Разница между вторым и третьим стоила очень дорого. Раньше оба
    случая возвращали None, и автозаведение принимало «не могу выбрать
    между двумя» за «вижу впервые» — заводило третью запись того же
    животного. Дальше кандидатов становилось больше, отрыв между ними
    падал, и система переставала узнавать вообще кого-либо. Со стороны
    это выглядит как «сначала узнавало, потом перестало».
    """

    animal_id: str | None = None
    distance: float | None = None
    margin: float | None = None
    ambiguous: bool = False
    # Ближайший, кем бы он ни был: и когда назвали уверенно, и когда
    # отрыв мал. Нужен для голосования — без него спорный кадр не
    # передать следующему, и переспрашивать было бы не о чем
    candidate: str | None = None
    # Все, кто прошёл порог, от ближнего к дальнему: (кличка, расстояние).
    #
    # Одного ближайшего мало с тех пор, как решение принимается сразу
    # про весь кадр: чтобы понять, кому достанется Зорька, надо знать,
    # кто ещё на неё претендует и что у претендентов есть кроме неё
    candidates: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        """
        Названный кандидат обязан быть в списке кандидатов.

        Это не формальность. Кличку теперь раздаёт `identity.assign`, и
        он смотрит ТОЛЬКО в список: `Match` с заполненным `animal_id`,
        но пустым списком означал бы «узнали, но кандидатов не было» —
        и животное молча оставалось бы неузнанным. База так не отвечает
        никогда, а вот собранный руками `Match` — запросто, и первым же
        на это наткнулся собственный тест.
        """
        if self.animal_id and not self.candidates:
            object.__setattr__(
                self,
                "candidates",
                ((self.animal_id, self.distance if self.distance is not None else 0.0),),
            )

    @property
    def anyone_close(self) -> bool:
        """Есть ли рядом хоть кто-то. Если есть — новую запись не заводим."""
        return self.animal_id is not None or self.ambiguous

    def explain(self, threshold: float | None = None) -> str:
        """
        Числа для журнала.

        Без них «животное не узнано» ничего не объясняет: то ли эталон
        далёк на волосок, то ли модель вообще не видит сходства. Первое
        лечится порогом, второе — сменой модели, и перепутать их дорого.
        """
        limit = match_threshold() if threshold is None else threshold

        if self.distance is None:
            return f"похожих нет вовсе (порог {limit:.2f})"

        parts = [f"ближайший на {self.distance:.3f} при пороге {limit:.2f}"]
        if self.margin is not None:
            parts.append(f"отрыв от следующего {self.margin:.3f}")
        else:
            parts.append("сравнивать не с кем")
        if self.ambiguous:
            parts.append("отрыв мал — назвать нельзя")
        return ", ".join(parts)


# Аргументы поиска, которых может не быть в старой базе, — от новых к
# старым. Уходят по именам, и лишний аргумент означает не ошибку вызова,
# а отказ выбрать функцию вообще
OPTIONAL_MATCH_ARGS = ("target_camera_id", "target_view")

# Сколько кандидатов просить у базы.
#
# Двух хватало, пока кличка раздавалась по одному кропу: нужен был
# ближайший и следующий для отрыва. С тех пор как кадр разбирается
# целиком, двух мало: чтобы понять, кому достанется Зорька, надо знать,
# что есть у её претендентов КРОМЕ неё. Пять — с запасом: столько
# похожих животных в одном кадре уже означает, что порог задран.
MATCH_COUNT = 5


def _ask(client, payload: dict) -> list[dict]:
    """
    Запрос к поиску с отходом на старые версии функции.

    Пробуем полный набор; не вышло — отбрасываем самый новый аргумент и
    пробуем снова. Последняя попытка идёт БЕЗ перехвата: если дело было
    не в аргументах, а в сети или доступе, ошибка должна дойти до
    вызывающего, а не превратиться в «никого не нашли».
    """
    attempts = [payload]
    for drop in range(1, len(OPTIONAL_MATCH_ARGS) + 1):
        skip = set(OPTIONAL_MATCH_ARGS[:drop])
        attempts.append({k: v for k, v in payload.items() if k not in skip})

    for attempt in attempts[:-1]:
        try:
            return client.rpc("match_animal", attempt).execute().data or []
        except Exception:
            continue

    return client.rpc("match_animal", attempts[-1]).execute().data or []


def identify(
    client,
    farm_id: str,
    embedding: list[float],
    threshold: float | None = None,
    view: str | None = None,
    camera_id: str | None = None,
) -> Match:
    """
    Ищет среди заведённых животных того, чей вектор ближе всего.

    Именно это решает проблему «одно животное считается разными»:
    номер трека сбрасывается при выходе из кадра, а вектор — нет.

    Называет животное только при уверенном отрыве от следующего
    кандидата. Без этой проверки система охотно называет соседнюю корову
    той же масти — и уверенно ошибается вместо того, чтобы промолчать.

    `camera_id` — с какой камеры пришёл кадр. База даёт эталонам этой же
    камеры небольшую надбавку: кадр сверху надо сравнивать прежде всего
    со спинами, а не с профилями, снятыми сбоку.
    """
    threshold = match_threshold() if threshold is None else threshold

    rows = _ask(
        client,
        {
            "query_embedding": embedding,
            "target_farm_id": farm_id,
            "match_threshold": threshold,
            "match_count": MATCH_COUNT,
            "target_view": view,
            "target_camera_id": camera_id,
        },
    )

    if not rows:
        # Порог не пройден никем. Чтобы в журнале было что показать,
        # спрашиваем ещё раз без порога — это дешёвый запрос, и он
        # превращает «не узнано» в «не узнано, ближайший на 0.42»
        try:
            nearest = (
                _ask(
                    client,
                    {
                        "query_embedding": embedding,
                        "target_farm_id": farm_id,
                        "match_threshold": 2.0,
                        "match_count": 1,
                        "target_view": view,
                        "target_camera_id": camera_id,
                    },
                )
                or [None]
            )[0]
        except Exception:
            nearest = None

        if not nearest:
            return Match()

        far = nearest.get("distance")
        return Match(distance=float(far) if far is not None else None)

    best = rows[0]
    margin = best.get("margin")
    distance = best.get("distance")
    distance = float(distance) if distance is not None else None
    candidate = best.get("animal_id")

    others = tuple(
        (str(row.get("animal_id")), float(row.get("distance")))
        for row in rows
        if row.get("animal_id") is not None and row.get("distance") is not None
    )

    # margin пуст, когда сравнивать не с кем — на ферме одно заведённое
    # животное. Тогда отрыв не при чём
    if margin is not None and float(margin) < min_margin():
        return Match(
            distance=distance,
            margin=float(margin),
            ambiguous=True,
            candidate=candidate,
            candidates=others,
        )

    return Match(
        animal_id=candidate,
        distance=distance,
        margin=float(margin) if margin is not None else None,
        candidate=candidate,
        candidates=others,
    )


def match_known_animal(
    client,
    farm_id: str,
    embedding: list[float],
    threshold: float | None = None,
    view: str | None = None,
    camera_id: str | None = None,
) -> str | None:
    """Только кличка. Оставлено для кода, которому подробности не нужны."""
    return identify(client, farm_id, embedding, threshold, view, camera_id).animal_id


def insert_seen(
    client,
    farm_id: str,
    camera_id: str,
    animal_id: str,
    crop: BestCrop,
) -> dict:
    """
    Записывает встречу узнанного животного.

    Ни кадра в хранилище, ни вектора в базе: эталоны берутся только из
    фото, которые человек загрузил осознанно. Раньше сюда попадал каждый
    трек — и кадр, и вектор, и строка «ждёт имени», — а очередь этих
    строк никто не разбирал.

    Здесь остаётся только факт: такое-то животное было на такой-то камере
    в такое-то время. Это и нужно для «последний раз видели».
    """
    row = {
        "farm_id": farm_id,
        "camera_id": camera_id,
        "animal_id": animal_id,
        "track_id": crop.track_id,
        # Колонка обязательная с тех времён, когда кадр действительно
        # сохранялся. Пустая строка означает «кадра нет и не будет»
        "crop_path": "",
        "confidence": round(crop.confidence, 3),
    }

    response = client.table("sightings").insert(row).execute()
    return response.data[0] if response.data else {}
