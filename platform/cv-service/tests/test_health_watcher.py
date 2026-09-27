"""
Поток проверки здоровья. Этап 5 плана PLAN_POVEDENIE.md.

Проверка идёт на устройстве, а не в браузере: открытая вкладка не должна
быть условием того, что болезнь заметили.
"""

import time

from cv_service.health import HealthWatcher, next_run_delay


class TestKogdaProveryat:
    def test_pervaya_proverka_ne_srazu(self):
        """
        Сразу после запуска считать нечего: устройство только что
        включилось, за сегодня у него ничего нет, а перезапуск бывает
        каждый раз, когда чинят камеру.
        """
        assert next_run_delay(runs=0) > 0

    def test_dalshe_raz_v_chas(self):
        assert next_run_delay(runs=1) == 3600.0

    def test_pervaya_pauza_korotkaya(self):
        # Ждать целый час до первой проверки — значит, что после
        # перезапуска днём тревоги не появятся до вечера
        assert next_run_delay(runs=0) < 3600.0


class TestPotok:
    def test_zovyot_proverku(self):
        calls = []
        watcher = HealthWatcher(lambda: calls.append(1), interval_s=0.01, first_s=0.0)
        watcher.start()
        time.sleep(0.05)
        watcher.stop()
        watcher.join(timeout=1.0)
        assert calls

    def test_oshibka_ne_ubivaet_potok(self):
        """
        Связь рвётся, база отвечает не сразу. Упавший поток означал бы,
        что проверки прекратились до перезапуска устройства — и никто об
        этом не узнает.
        """
        calls = []

        def failing():
            calls.append(1)
            raise RuntimeError("сеть недоступна")

        watcher = HealthWatcher(failing, interval_s=0.01, first_s=0.0)
        watcher.start()
        time.sleep(0.05)
        watcher.stop()
        watcher.join(timeout=1.0)
        assert len(calls) > 1

    def test_ostanovka_ne_zhdyot_ves_interval(self):
        # Иначе Ctrl+C висел бы до часа
        watcher = HealthWatcher(lambda: None, interval_s=3600.0, first_s=3600.0)
        watcher.start()
        watcher.stop()
        watcher.join(timeout=1.0)
        assert not watcher.is_alive()
