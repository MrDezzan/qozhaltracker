"""
Разнесение работы по потокам.

Смысл всего этого — в том, чтобы медленное не останавливало быстрое.
Вектор признаков на процессоре считается секунду-две; пока он считался
в основном цикле, на это время замирали и трекинг, и живой просмотр.
"""

import threading
import time

from cv_service.pipeline import LatestSlot, LatestWorker, TaskWorker


class TestLatestSlot:
    def test_gives_back_what_was_put(self):
        slot = LatestSlot()
        slot.put("кадр")
        assert slot.take(timeout=0.1) == "кадр"

    def test_a_new_item_replaces_the_old_one(self):
        """
        Отправлять накопившуюся очередь кадров вредно: зритель смотрел бы
        прошлое, догоняя настоящее. Свежий кадр всегда важнее предыдущего.
        """
        slot = LatestSlot()
        slot.put("старый")
        slot.put("новый")

        assert slot.take(timeout=0.1) == "новый"
        assert slot.take(timeout=0.05) is None

    def test_counts_what_it_dropped(self):
        slot = LatestSlot()
        for n in range(5):
            slot.put(n)
        assert slot.dropped == 4

    def test_empty_slot_returns_nothing_after_the_wait(self):
        assert LatestSlot().take(timeout=0.05) is None

    def test_closing_wakes_the_waiting_reader(self):
        slot = LatestSlot()
        slot.close()
        assert slot.take(timeout=0.05) is None


class TestLatestWorker:
    def test_sends_in_the_background(self):
        sent = []
        worker = LatestWorker(sent.append, name="test-uploader")
        worker.start()
        try:
            worker.submit("кадр")
            _wait_until(lambda: sent == ["кадр"])
        finally:
            worker.stop()

    def test_the_caller_is_not_held_up_by_a_slow_send(self):
        """
        Отправка снимка занимает от долей секунды до нескольких секунд
        на плохой связи. В основном цикле это означало бы стоящее видео.
        """
        started = threading.Event()
        release = threading.Event()

        def slow(_item):
            started.set()
            release.wait(2.0)

        worker = LatestWorker(slow, name="test-slow")
        worker.start()
        try:
            worker.submit("первый")
            started.wait(1.0)

            began = time.monotonic()
            for n in range(50):
                worker.submit(n)
            assert time.monotonic() - began < 0.2
        finally:
            release.set()
            worker.stop()

    def test_a_failed_send_does_not_kill_the_thread(self):
        results = []

        def flaky(item):
            if item == "плохой":
                raise RuntimeError("нет сети")
            results.append(item)

        worker = LatestWorker(flaky, name="test-flaky")
        worker.start()
        try:
            worker.submit("плохой")
            _wait_until(lambda: worker.is_alive())
            worker.submit("хороший")
            _wait_until(lambda: results == ["хороший"])
        finally:
            worker.stop()


class TestTaskWorker:
    def test_runs_the_job(self):
        done = []
        worker = TaskWorker(name="test-worker")
        worker.start()
        try:
            worker.submit(lambda: done.append(1))
            _wait_until(lambda: done == [1])
        finally:
            worker.stop()

    def test_submitting_does_not_wait_for_the_job(self):
        release = threading.Event()
        worker = TaskWorker(name="test-block")
        worker.start()
        try:
            worker.submit(lambda: release.wait(2.0))
            began = time.monotonic()
            worker.submit(lambda: None)
            assert time.monotonic() - began < 0.2
        finally:
            release.set()
            worker.stop()

    def test_drops_the_oldest_when_it_falls_behind(self):
        """
        Потерянный кадр стоит одной несостоявшейся попытки опознания.
        Остановленный цикл стоит живого просмотра и пропущенных событий.
        """
        worker = TaskWorker(maxsize=2, name="test-full")
        # Не запускаем: очередь должна переполниться
        for _ in range(5):
            worker.submit(lambda: None)

        assert worker.pending == 2
        assert worker.dropped == 3

    def test_a_failing_job_does_not_kill_the_thread(self):
        done = []
        worker = TaskWorker(name="test-boom")
        worker.start()
        try:
            worker.submit(lambda: (_ for _ in ()).throw(RuntimeError("сбой")))
            worker.submit(lambda: done.append("после"))
            _wait_until(lambda: done == ["после"])
            assert worker.is_alive()
        finally:
            worker.stop()

    def test_jobs_keep_their_order(self):
        done = []
        worker = TaskWorker(name="test-order")
        worker.start()
        try:
            for n in range(5):
                worker.submit(lambda n=n: done.append(n))
            _wait_until(lambda: len(done) == 5)
            assert done == [0, 1, 2, 3, 4]
        finally:
            worker.stop()

    def test_drain_finishes_the_backlog(self):
        """При остановке камеры незаписанные наблюдения жальче задержки."""
        done = []
        worker = TaskWorker(name="test-drain")
        worker.start()
        try:
            for n in range(5):
                worker.submit(lambda n=n: done.append(n))
            worker.drain(timeout=3.0)
            assert len(done) == 5
        finally:
            worker.stop()

    def test_drain_gives_up_instead_of_hanging(self):
        release = threading.Event()
        worker = TaskWorker(name="test-stuck")
        worker.start()
        try:
            worker.submit(lambda: release.wait(5.0))
            worker.submit(lambda: None)

            began = time.monotonic()
            worker.drain(timeout=0.3)
            assert time.monotonic() - began < 2.0
        finally:
            release.set()
            worker.stop()


def _wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("условие не выполнилось за отведённое время")


class TestLatestWorkerShutdown:
    def test_the_last_item_is_still_sent(self):
        """
        Иначе последний кадр перед выключением пропадал, и в интерфейсе
        оставалась картинка на секунду старше нужной.
        """
        sent = []
        worker = LatestWorker(sent.append, name="test-flush")
        worker.start()
        worker.submit("последний")
        worker.stop()

        assert sent == ["последний"]

    def test_counts_only_what_was_delivered(self):
        """
        Считать отданное в очередь нельзя: счётчик рос бы и при наглухо
        застрявшей отправке, создавая видимость работы.
        """
        worker = LatestWorker(lambda _: None, name="test-count")
        worker.submit("кадр")
        assert worker.completed == 0

        worker.start()
        worker.stop()
        assert worker.completed == 1

    def test_a_failing_last_item_does_not_explode(self):
        def boom(_item):
            raise RuntimeError("нет сети")

        worker = LatestWorker(boom, name="test-boom-last")
        worker.start()
        worker.submit("кадр")
        worker.stop()
        assert worker.completed == 0

    def test_stopping_an_empty_worker_is_fine(self):
        worker = LatestWorker(lambda _: None, name="test-empty")
        worker.start()
        worker.stop()
        assert worker.completed == 0
