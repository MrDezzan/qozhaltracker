from __future__ import annotations

import queue
import threading
from typing import Any, Callable

# Сколько заданий держим в очереди. Больше держать бессмысленно: если
# обработчик отстаёт, копить впрок нечего — данные протухают быстрее,
# чем очередь разбирается.
DEFAULT_QUEUE_SIZE = 8


class LatestSlot:
    """
    Место ровно на одно задание: новое вытесняет прежнее.

    Для снимков это именно то, что нужно. Если отправка отстала, отправлять
    накопившуюся очередь кадров вредно — зритель будет смотреть прошлое,
    догоняя настоящее. Свежий кадр всегда важнее любого предыдущего.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._item: Any = None
        self._has_item = False
        self._closed = False
        self.dropped = 0

    def put(self, item: Any) -> None:
        with self._lock:
            if self._has_item:
                self.dropped += 1
            self._item = item
            self._has_item = True
            self._ready.notify()

    def take(self, timeout: float = 0.5) -> Any:
        with self._lock:
            if not self._has_item and not self._closed:
                self._ready.wait(timeout)
            if not self._has_item:
                return None
            item = self._item
            self._item = None
            self._has_item = False
            return item

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._ready.notify_all()

    def peek_pending(self) -> Any:
        """Забрать оставшееся, не дожидаясь ничего нового."""
        with self._lock:
            if not self._has_item:
                return None
            item = self._item
            self._item = None
            self._has_item = False
            return item


class LatestWorker(threading.Thread):
    """
    Поток, который отправляет всегда самое свежее.

    Снимок весит десятки килобайт, отправка занимает от десятых долей
    секунды до нескольких секунд на плохой связи. В основном цикле это
    означало бы, что видео стоит, пока уходит картинка.
    """

    def __init__(self, handler: Callable[[Any], None], name: str = "uploader"):
        super().__init__(name=name, daemon=True)
        self._handler = handler
        self._slot = LatestSlot()
        self._stopping = threading.Event()
        # Считаем доставленное, а не отданное в очередь: иначе счётчик
        # рос бы и при наглухо застрявшей отправке
        self.completed = 0

    def submit(self, item: Any) -> None:
        self._slot.put(item)

    @property
    def dropped(self) -> int:
        """Сколько кадров пропущено из-за отставания отправки."""
        return self._slot.dropped

    def run(self) -> None:
        while not self._stopping.is_set():
            item = self._slot.take()
            if item is None:
                continue
            try:
                self._handler(item)
                self.completed += 1
            except Exception as exc:
                print(f"фоновая отправка не удалась: {exc}")

    def stop(self, timeout: float = 3.0) -> None:
        """
        Останавливает поток, но сперва досылает то, что осталось.

        Иначе последний кадр перед выключением просто пропадал, и после
        остановки сервиса в интерфейсе висел кадр на секунду старше нужного.
        """
        self._stopping.set()
        self._slot.close()

        if self.is_alive():
            self.join(timeout)

        pending = self._slot.peek_pending()
        if pending is None:
            return
        try:
            self._handler(pending)
            self.completed += 1
        except Exception as exc:
            print(f"последний кадр не отправлен: {exc}")


class TaskWorker(threading.Thread):
    """
    Очередь тяжёлых заданий с ограничением сверху.

    Сюда уходит всё, что считается долго: вектор признаков, отправка
    вырезанных кадров, запись наблюдений. На процессоре без ускорителя
    один вектор считается секунду-две — в основном цикле это остановило бы
    и трекинг, и живой просмотр.

    При переполнении выбрасываем самое старое задание. Потерянный кадр
    стоит одной несостоявшейся попытки опознания; остановленный цикл
    стоит живого просмотра и пропущенных событий. Второе хуже.
    """

    def __init__(
        self,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        name: str = "worker",
    ):
        super().__init__(name=name, daemon=True)
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._stopping = threading.Event()
        self.dropped = 0

    def submit(self, job: Callable[[], None]) -> bool:
        """Возвращает False, если задание пришлось выбросить."""
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            pass

        # Освобождаем место, выкинув самое старое
        try:
            self._queue.get_nowait()
            self.dropped += 1
        except queue.Empty:
            pass

        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                job()
            except Exception as exc:
                print(f"фоновое задание не выполнено: {exc}")
            finally:
                self._queue.task_done()

    def drain(self, timeout: float = 10.0) -> None:
        """Доделать накопленное — вызывается при остановке камеры."""
        deadline = threading.Event()
        timer = threading.Timer(timeout, deadline.set)
        timer.start()
        try:
            while not self._queue.empty() and not deadline.is_set():
                deadline.wait(0.1)
        finally:
            timer.cancel()

    def stop(self) -> None:
        self._stopping.set()
