"""
Запись животного с той же камеры, которая потом будет его узнавать.

Раньше эталоны приходили из фотографий, снятых на телефон. Это плохо
работало, и причина глубже неудобства: модель признаков чувствительна к
тому, чем и как снято. Снимок днём с двух метров сбоку и кадр потолочной
камеры ночью для неё почти не связаны — совпадение выходило слабым даже
при аккуратной съёмке.

Здесь эталон и рабочий кадр приходят из одного источника. Человек вводит
кличку, жмёт «Записать» и проводит животное мимо камеры. Дальше всё
делает устройство.

Три правила, без которых запись будет собирать мусор:

  1. В кадре должно быть ровно одно животное. Двое рядом — и половина
     эталонов достанется соседу, причём молча.
  2. Кадры должны отличаться друг от друга. Пятьдесят кадров одной позы
     — это по сути один кадр, а счётчик покажет «готово».
  3. Животное не у края кадра. Обрезанный силуэт даёт вектор, под
     который потом подходит кто угодно.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from cv_service.detector import Detection

# Как часто спрашивать, не началась ли запись.
#
# Две секунды: человек нажал «Записать» и идёт к загону. Задержка в
# минуту означала бы, что первые кадры прогона пропущены, а он об этом
# не узнает.
POLL_INTERVAL_S = 2.0

# Не ближе этой доли кадра к БОКОВОМУ краю.
#
# Проверка только по бокам, и это не небрежность. Слева и справа кадр
# режет животное вдоль — теряется голова или круп, а именно они отличают
# одну особь от другой. Сверху и снизу срезается спина или ноги, бок при
# этом виден целиком, и вектор остаётся годным.
#
# Прежняя проверка отбивала все четыре стороны, и на этом всё вставало:
# человек перед ноутбуком почти всегда обрезан по нижнему краю, коровы
# под потолочной камерой — тоже. Счётчик стоял на нуле, а почему — нигде
# не было написано.
BORDER_MARGIN = 0.02

# Минимальная площадь рамки в пикселях. Мелкое пятно вдалеке даёт вектор
# ни о чём — примерно 200×200
MIN_AREA_PX = 40_000

MIN_CONFIDENCE = 0.6

# Насколько новый кадр должен отличаться от уже записанных.
#
# Косинусное расстояние. Ноль — тот же самый кадр, и таких набирается
# пятьдесят за две секунды. Порог отбирает разные ракурсы: животное
# повернулось, нагнулось, отошло дальше.
MIN_DISTANCE = 0.08

# Реже, чем раз в столько секунд, кадр не берём вовсе. Дешёвая отсечка
# до всякого счёта векторов: соседние кадры почти наверняка одинаковы
MIN_INTERVAL_S = 0.4


# Сколько кадров берёт КАЖДАЯ камера.
#
# Шесть, а не двенадцать: камер две, и вместе они дают те же двенадцать,
# что раньше набирала одна, но с двух сторон — спина и профиль.
#
# Совпадает с `per_camera` в базе и используется, только когда база это
# число не прислала
DEFAULT_PER_CAMERA = 6


@dataclass(frozen=True)
class RecordingSession:
    """
    Идущая запись, в которой участвует эта камера.

    Сеанс общий на несколько камер: человек проводит животное по проходу
    один раз, а верхняя и боковая камеры берут своё. Эталоны с них
    несопоставимы между собой — сверху спина, сбоку профиль, — и одна
    камера не может записать за другую.
    """

    id: str
    animal_id: str
    label: str
    captured: int
    needed: int
    # Сколько набираем на самом деле. Человеку показывается needed:
    # после него животное уже узнаётся и его можно уводить, а остальное
    # добирается молча, пока оно ещё в кадре
    target: int = 20
    # Какой ракурс ждём сейчас. None — камера ракурсов не различает либо
    # все уже набраны
    awaiting_view: str | None = None
    # Сколько кадров нужно с каждой камеры
    per_camera: int = DEFAULT_PER_CAMERA
    # Сколько из них набрала ЭТА камера
    mine: int = 0

    @property
    def quota_full(self) -> bool:
        """
        Набрала ли эта камера своё.

        Дальше она молчит, даже если сеанс ещё идёт: вторая камера может
        отставать, и мешать ей незачем.
        """
        return self.mine >= self.per_camera


def is_other_camera(row: dict | None) -> bool:
    """Запись идёт, но без этой камеры — человек ждёт не там."""
    return bool(row and row.get("__other_camera__"))


def _mine(row: dict, camera_id: str | None) -> int:
    """Сколько кадров записала эта камера. Считает база, мы только читаем."""
    by_camera = row.get("captured_by")
    if not isinstance(by_camera, dict) or camera_id is None:
        # Старая база без разбивки по камерам: сеанс всё равно
        # одно-камерный, и всё набранное — наше
        return int(row.get("captured") or 0)
    try:
        return int(by_camera.get(str(camera_id)) or 0)
    except (TypeError, ValueError):
        return 0


def parse_session(
    row: dict | None, camera_id: str | None = None
) -> RecordingSession | None:
    if not row or row.get("__other_camera__"):
        return None
    try:
        return RecordingSession(
            id=str(row["id"]),
            animal_id=str(row["animal_id"]),
            label=str(row.get("label") or ""),
            captured=int(row.get("captured") or 0),
            needed=int(row.get("needed") or 12),
            target=int(row.get("target") or 20),
            awaiting_view=row.get("awaiting_view") or None,
            per_camera=int(row.get("per_camera") or DEFAULT_PER_CAMERA),
            mine=_mine(row, camera_id),
        )
    except (KeyError, TypeError, ValueError):
        return None


def why_not(
    detections: list[Detection], frame_width: int, frame_height: int
) -> str:
    """
    Почему этот кадр не годится. Пустая строка — годится.

    Отдельно от отбора, чтобы причину можно было показать человеку. Он
    стоит перед камерой и видит только счётчик; молчащий счётчик без
    объяснения — худшее, что может сделать система.
    """
    subjects = [d for d in detections if d.group == "livestock"]

    if not subjects:
        return "никого не вижу в кадре"
    if len(subjects) > 1:
        return f"в кадре сразу {len(subjects)} — нужно одно"

    subject = subjects[0]
    if subject.confidence < MIN_CONFIDENCE:
        return "вижу неуверенно — подойдите ближе или добавьте света"

    x1, y1, x2, y2 = subject.bbox
    if (x2 - x1) * (y2 - y1) < MIN_AREA_PX:
        return "слишком далеко — подойдите ближе к камере"

    margin_x = frame_width * BORDER_MARGIN
    if x1 < margin_x or x2 > frame_width - margin_x:
        return "у края кадра — отойдите от левого и правого краёв"

    return ""


def pick_single_subject(
    detections: list[Detection], frame_width: int, frame_height: int
) -> Detection | None:
    """
    Животное, с которого можно писать эталон. None — этот кадр пропускаем.

    Отказ здесь дешёвый: прогон длится полминуты, кадров сотни. Взять
    не то животное дорого: неверный эталон живёт в базе вечно и портит
    узнавание не только этой особи, но и соседней.
    """
    if why_not(detections, frame_width, frame_height):
        return None
    return [d for d in detections if d.group == "livestock"][0]


def cosine_distance(first, second) -> float:
    """Расстояние между векторами. Одинаковые — ноль."""
    dot = sum(a * b for a, b in zip(first, second))
    norm_a = sum(a * a for a in first) ** 0.5
    norm_b = sum(b * b for b in second) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def is_new_angle(embedding, collected: list, min_distance: float = MIN_DISTANCE) -> bool:
    """
    Отличается ли кадр от уже записанных.

    Без этой проверки счётчик набирает нужные двенадцать за две секунды
    неподвижного стояния, животное «записано», а узнаваться будет только
    в одной позе. Человек при этом уверен, что всё сделал правильно.
    """
    return all(cosine_distance(embedding, other) >= min_distance for other in collected)


@dataclass
class RecordingProgress:
    """
    Что уже записано в этом сеансе.

    Векторы держим у себя, а не перечитываем из базы: сравнение с
    каждым новым кадром идёт в цикле обработки, и ходить за ними по
    сети было бы и медленно, и незачем.
    """

    session_id: str
    embeddings: list = field(default_factory=list)
    # Последняя отправленная подсказка. Шлём только при изменении: писать
    # в базу одно и то же по десять раз в секунду незачем
    last_hint: str | None = None
    # None, а не ноль: ноль — это осмысленный момент времени, и первый
    # кадр прогона на нём пропускался бы. Такую ошибку уже ловили в
    # охране, где посторонний, впервые замеченный в ноль, не копил время
    last_taken_at: float | None = None
    # Когда последний раз отчитывались в журнал
    last_report_at: float | None = None

    def due_to_report(self, now: float, every_s: float = 10.0) -> bool:
        """Пора ли повторить строку в журнале."""
        if self.last_report_at is None or now - self.last_report_at >= every_s:
            self.last_report_at = now
            return True
        return False

    def accepts(self, now: float) -> bool:
        if self.last_taken_at is None:
            return True
        return now - self.last_taken_at >= MIN_INTERVAL_S

    def hint_changed(self, hint: str) -> bool:
        if hint == self.last_hint:
            return False
        self.last_hint = hint
        return True

    def remember(self, embedding, now: float) -> None:
        self.embeddings.append(embedding)
        self.last_taken_at = now


class RecordingWatcher(threading.Thread):
    """
    Спрашивает базу, не идёт ли запись на этой камере.

    Отдельным потоком по той же причине, что и зоны: запрос по сети не
    должен останавливать обработку видео. Цикл обработки только читает
    готовый ответ.
    """

    def __init__(
        self,
        fetch,
        interval_s: float = POLL_INTERVAL_S,
        camera_id: str | None = None,
    ):
        super().__init__(name="recording", daemon=True)
        self._fetch = fetch
        self._camera_id = camera_id
        self._interval_s = interval_s
        self._lock = threading.Lock()
        self._session: RecordingSession | None = None
        self._warned_other = False
        self._stopping = threading.Event()

    def refresh(self) -> RecordingSession | None:
        try:
            row = self._fetch()
            if is_other_camera(row) and not self._warned_other:
                self._warned_other = True
                print(
                    f"запись «{row.get('label', '')}» идёт без этой камеры — "
                    "кадры с неё не берутся. Отмените запись и отметьте эту "
                    "камеру галочкой вместе с остальными, что смотрят на то "
                    "же место"
                )
            elif not is_other_camera(row):
                self._warned_other = False

            session = parse_session(row, self._camera_id)
        except Exception as exc:  # noqa: BLE001 — причина уходит в журнал
            print(f"состояние записи не получено: {exc}")
            return self.current()

        with self._lock:
            self._session = session
        return session

    def current(self) -> RecordingSession | None:
        with self._lock:
            return self._session

    def run(self) -> None:
        while not self._stopping.is_set():
            self.refresh()
            self._stopping.wait(self._interval_s)

    def stop(self) -> None:
        self._stopping.set()


def describe(session: RecordingSession | None) -> str:
    if session is None:
        return "запись не идёт"
    waiting = (
        f", ждём ракурс {session.awaiting_view}" if session.awaiting_view else ""
    )
    # Своё число впереди общего. При двух камерах именно оно объясняет,
    # почему эта камера замолчала, а счётчик на экране продолжает расти
    return (
        f"записываем «{session.label}»: с этой камеры {session.mine} "
        f"из {session.per_camera}, всего {session.captured}{waiting}"
    )
