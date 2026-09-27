from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

# Сколько событий держим на диске. Событий немного — сводка раз в минуту
# плюс визиты, — так что месяца автономии хватает с запасом. Ограничение
# нужно на случай, когда связи нет неделями и о ферме просто забыли.
DEFAULT_CAPACITY = 200_000

DEFAULT_PATH = "spool.db"


def spool_path() -> str:
    return os.environ.get("EVENT_SPOOL_PATH", "").strip() or DEFAULT_PATH


class EventSpool:
    """
    Очередь событий на диске на время обрыва связи.

    Ферма сидит на сельском интернете: пропасть на несколько часов — обычное
    дело, а кадры за это время уже не переснять. Событие несёт собственное
    время (occurred_at ставит устройство), поэтому отложенная отправка не
    искажает историю.

    SQLite взят намеренно: он переживает выключение питания посреди записи,
    чего не гарантирует ни файл со строками, ни очередь в памяти.
    """

    def __init__(self, path: str | None = None, capacity: int = DEFAULT_CAPACITY):
        self.path = path or spool_path()
        self.capacity = capacity
        self._lock = threading.Lock()

        parent = Path(self.path).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        # Журнал упреждающей записи: питание пропало — база осталась целой
        self._conn.execute("pragma journal_mode=WAL")
        self._conn.execute(
            "create table if not exists pending ("
            " id integer primary key autoincrement,"
            " body text not null)"
        )
        self._conn.commit()

    def put(self, row: dict) -> None:
        with self._lock:
            self._conn.execute(
                "insert into pending (body) values (?)", (json.dumps(row),)
            )
            # Переполнение выбрасывает самое старое: свежие данные полезнее
            self._conn.execute(
                "delete from pending where id <= ("
                " select max(id) - ? from pending)",
                (self.capacity,),
            )
            self._conn.commit()

    def take(self, limit: int = 100) -> list[tuple[int, dict]]:
        with self._lock:
            rows = self._conn.execute(
                "select id, body from pending order by id limit ?", (limit,)
            ).fetchall()
        result = []
        for row_id, body in rows:
            try:
                result.append((row_id, json.loads(body)))
            except json.JSONDecodeError:
                # Битую строку не оставляем навсегда блокировать очередь
                self.remove([row_id])
        return result

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(f"delete from pending where id in ({placeholders})", ids)
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("select count(*) from pending").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def drain(spool: EventSpool, send, batch: int = 100) -> int:
    """
    Пробует отправить накопленное. Возвращает число отправленных.

    Останавливается на первой же ошибке: если связи нет, продолжать перебор
    бессмысленно — только зря греть радиоканал. Порядок сохраняется.
    """
    sent = 0
    for row_id, row in spool.take(batch):
        try:
            send(row)
        except Exception:
            break
        spool.remove([row_id])
        sent += 1
    return sent
