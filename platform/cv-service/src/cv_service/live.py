from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

# Как часто спрашивать базу, не просит ли кто живой просмотр.
# Три секунды — это задержка между нажатием кнопки и ускорением камеры.
POLL_INTERVAL_S = 3.0

# Как часто отдавать кадры в живом режиме.
# Секунда — это не видео, но этого хватает, чтобы увидеть, что происходит
# в загоне прямо сейчас. Настоящее видео пошло бы через локальную сеть,
# а не через интернет: один поток — это около двух мегабит в секунду.
DEFAULT_LIVE_INTERVAL_S = 1.0


def live_interval_s() -> float:
    raw = os.environ.get("LIVE_SNAPSHOT_INTERVAL_S", "").strip()
    if not raw:
        return DEFAULT_LIVE_INTERVAL_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LIVE_INTERVAL_S
    return value if value > 0 else DEFAULT_LIVE_INTERVAL_S


def parse_until(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # Postgres отдаёт время со смещением; ISO-разбор его понимает
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


class LiveWindow(threading.Thread):
    """
    Знает, для каких камер сейчас просят живой просмотр.

    Опрашивает базу в собственном потоке. Это принципиально: раньше запрос
    шёл прямо из цикла захвата, и один зависший вызов останавливал обработку
    видео целиком — вместе с тем самым живым просмотром, ради которого всё
    и затевалось. Сетевым вызовам в цикле захвата не место.

    is_live() читает только память и не ждёт никогда.
    """

    def __init__(self, client, farm_id: str, poll_interval_s: float = POLL_INTERVAL_S):
        super().__init__(name="live-window", daemon=True)
        self._client = client
        self._farm_id = farm_id
        self._poll_interval_s = poll_interval_s
        self._lock = threading.Lock()
        self._until: dict[str, datetime] = {}
        self._stopping = threading.Event()
        self._warned = False

    def _refresh(self) -> None:
        # Берём все камеры фермы и отсеиваем пустые отметки уже здесь.
        # Отрицающий фильтр на стороне базы — лишний повод для тихой
        # осечки, а камер у фермы единицы, экономить не на чем.
        response = (
            self._client.table("cameras")
            .select("id, live_until")
            .eq("farm_id", self._farm_id)
            .execute()
        )
        fresh: dict[str, datetime] = {}
        for row in response.data or []:
            until = parse_until(row.get("live_until"))
            if until is not None:
                fresh[str(row["id"])] = until

        with self._lock:
            self._until = fresh

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._refresh()
            except Exception as exc:
                # Жалуемся один раз: иначе журнал забьётся за час
                if not self._warned:
                    self._warned = True
                    print(
                        f"живой просмотр недоступен: {exc}. "
                        "Если это ошибка про колонку live_until — "
                        "не применена миграция 0010"
                    )
            self._stopping.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stopping.set()

    def is_live(self, camera_id: str, now: float | None = None) -> bool:
        """Только чтение памяти: вызывается из цикла захвата и ждать не может."""
        with self._lock:
            until = self._until.get(camera_id)
        return until is not None and until > datetime.now(timezone.utc)

    def check_available(self) -> str:
        """
        Проверка при запуске: умеет ли эта база живой просмотр вообще.

        Нужна, чтобы в журнале сразу было видно, работает ли новый код,
        а не выяснять это по возрасту кадра в браузере.
        """
        try:
            self._refresh()
        except Exception as exc:
            return f"недоступен: {exc}"
        return "готов"


class Heartbeat(threading.Thread):
    """
    Отметка «устройство живо» и продление сессии — тоже в своём потоке.

    Оба вызова ходят в сеть. В цикле захвата они означали бы, что раз
    в минуту видео замирает на время сетевого запроса, а при зависшем
    соединении — навсегда.
    """

    def __init__(self, beat, interval_s: float = 60.0):
        super().__init__(name="heartbeat", daemon=True)
        self._beat = beat
        self._interval_s = interval_s
        self._stopping = threading.Event()

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._beat()
            except Exception as exc:
                print(f"heartbeat не отправлен: {exc}")
            self._stopping.wait(self._interval_s)

    def stop(self) -> None:
        self._stopping.set()


class ZoneCache(threading.Thread):
    """
    Держит свежий список зон, перечитывая его в своём потоке.

    Админ нарисовал зону — устройство подхватит её в течение минуты,
    но чтение из базы не остановит обработку видео.
    """

    def __init__(self, fetch, interval_s: float = 60.0):
        super().__init__(name="zones", daemon=True)
        self._fetch = fetch
        self._interval_s = interval_s
        self._lock = threading.Lock()
        self._rows: list[dict] = []
        self._version = 0
        self._stopping = threading.Event()

    def prime(self) -> list[dict]:
        """Первое чтение — до запуска потока, чтобы зоны были сразу."""
        try:
            rows = self._fetch()
        except Exception as exc:
            print(f"зоны не загружены: {exc}")
            rows = []
        with self._lock:
            self._rows = rows
            self._version += 1
        return rows

    def run(self) -> None:
        while not self._stopping.is_set():
            self._stopping.wait(self._interval_s)
            if self._stopping.is_set():
                return
            self.prime()

    def take_if_changed(self, seen_version: int) -> tuple[int, list[dict]] | None:
        """Отдаёт зоны, только если они перечитывались с прошлого раза."""
        with self._lock:
            if self._version == seen_version:
                return None
            return self._version, list(self._rows)

    def stop(self) -> None:
        self._stopping.set()
