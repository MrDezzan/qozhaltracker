"""
Отдача видео наружу через сервер ретрансляции.

Зачем это вообще, если поток по локальной сети уже работает:

  - в сети фермы мы отдаём MJPEG прямо с мини-ПК, тридцать кадров, и это
    прекрасно ровно до тех пор, пока телефон в той же сети;
  - снаружи до фермы не достучаться: белого адреса нет, порт пробросить
    не через что;
  - и даже будь адрес, MJPEG туда не влез бы. Пятнадцать кадров по 70 КБ
    это больше восьми мегабит в секунду, а отдача у фермы — один-три.

Поэтому наружу отдаём иначе. Ферма сама подключается к нашему серверу
и отдаёт H.264 ПРЯМО С КАМЕРЫ, без разжатия и сжатия обратно. Камера уже
кодирует H.264 — это её родной формат, мы просто перекладываем пакеты.
Около 400 кбит/с вместо восьми мегабит, и процессор при этом свободен.

Публикуем только пока кто-то смотрит: нет сессии — нет процесса.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

# Как часто спрашивать, не открыл ли кто просмотр. Три секунды — задержка
# между нажатием кнопки в браузере и появлением картинки.
POLL_INTERVAL_S = 3.0

# Сколько ждать, прежде чем поднимать упавшую публикацию. Без паузы
# сорванный канал означал бы запуск ffmpeg в цикле несколько раз в секунду.
RESTART_DELAY_S = 5.0


def relay_url() -> str:
    """
    Адрес сервера ретрансляции. Пусто — наружу не отдаём вовсе,
    и всё продолжает работать как раньше, по локальной сети.
    """
    return os.environ.get("RELAY_URL", "").strip().rstrip("/")


def relay_enabled() -> bool:
    return bool(relay_url())


def ffmpeg_path() -> str | None:
    return shutil.which(os.environ.get("FFMPEG_BIN", "ffmpeg"))


def build_publish_command(source_uri: str, target: str) -> list[str]:
    """
    Команда публикации одного потока.

    Ключевое здесь — `-c copy`. Мы НЕ перекодируем: камера уже отдаёт
    H.264, и трогать его нечем и незачем. Перекодирование съело бы ядро
    на камеру и ухудшило картинку ради ничего.

    `-an` — звук выбрасываем. Он не нужен, занимает канал и записывать
    разговоры работников — отдельный юридический разговор, в который мы
    не идём.
    """
    return [
        ffmpeg_path() or "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        # По TCP, а не UDP: на плохом канале UDP осыпается в кашу,
        # а RTSP по TCP просто притормаживает
        "-rtsp_transport", "tcp",
        # Не ждать вечно мёртвую камеру: пять секунд и наружу с ошибкой,
        # чтобы сработал перезапуск
        "-stimeout", "5000000",
        "-i", source_uri,
        "-c", "copy",
        "-an",
        # Аннексная упаковка: без неё поток из RTSP часто не принимается
        # ни WHIP, ни RTMP — кадры уходят, а на той стороне пусто
        "-bsf:v", "h264_mp4toannexb",
        "-f", "whip",
        target,
    ]


class Publication:
    """
    Один запущенный ffmpeg. Держим отдельным классом, чтобы поведение
    «запустился, живёт, умер, перезапустился» можно было проверить
    тестами, не поднимая ни камеры, ни сервера.
    """

    def __init__(self, camera_id: str, path: str, process):
        self.camera_id = camera_id
        self.path = path
        self.process = process
        self.started_at = time.monotonic()

    def is_running(self) -> bool:
        return self.process.poll() is None

    def stop(self, timeout: float = 3.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout)
        except Exception:
            # Не отреагировал на просьбу — значит по-плохому. Оставлять
            # висеть нельзя: он держит соединение с камерой
            self.process.kill()


class RemotePublisher(threading.Thread):
    """
    Держит публикации в соответствии с открытыми сессиями.

    Работает отдельным потоком и в цикл захвата не лезет ни на шаг:
    это то самое правило, нарушение которого однажды уже остановило
    у нас всю обработку видео из-за одного сетевого вызова.
    """

    def __init__(
        self,
        client,
        farm_id: str,
        cameras: list[dict],
        poll_interval_s: float = POLL_INTERVAL_S,
        spawn=None,
    ):
        super().__init__(name="remote-publisher", daemon=True)
        self._client = client
        self._farm_id = farm_id
        self._sources = {str(c["id"]): c.get("source_uri") for c in cameras}
        self._names = {str(c["id"]): c.get("name", "камера") for c in cameras}
        self._poll_interval_s = poll_interval_s
        self._spawn = spawn or self._spawn_ffmpeg
        self._active: dict[str, Publication] = {}
        self._failed_at: dict[str, float] = {}
        self._stopping = threading.Event()
        self._warned = False

    # --- работа с базой ---

    def _fetch_sessions(self) -> dict[str, str]:
        """Камера → путь публикации, только по живым сессиям."""
        response = (
            self._client.table("active_stream_sessions")
            .select("camera_id, path")
            .eq("farm_id", self._farm_id)
            .execute()
        )
        return {
            str(row["camera_id"]): str(row["path"])
            for row in (response.data or [])
            if row.get("path")
        }

    # --- запуск ---

    def _spawn_ffmpeg(self, source_uri: str, target: str):
        return subprocess.Popen(
            build_publish_command(source_uri, target),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    # Имена намеренно длинные. Короткие `_target` и `_stop` здесь нельзя:
    # threading.Thread держит под этими именами своё — `self._target` это
    # функция потока, а `_stop()` вызывается изнутри при его завершении.
    # Перекрыв их, мы получаем «'NoneType' object is not callable» в одном
    # месте и сломанный учёт живых потоков в другом.
    def _publish_target(self, path: str) -> str:
        return f"{relay_url()}/{path}/whip"

    def _start_publication(self, camera_id: str, path: str) -> None:
        source = self._sources.get(camera_id)
        if not source:
            return

        # Не ломимся сразу после падения: пусть отлежится
        failed = self._failed_at.get(camera_id)
        if failed is not None and time.monotonic() - failed < RESTART_DELAY_S:
            return

        try:
            process = self._spawn(source, self._publish_target(path))
        except Exception as exc:
            self._failed_at[camera_id] = time.monotonic()
            print(f"{self._names.get(camera_id)}: публикация не запущена — {exc}")
            return

        self._active[camera_id] = Publication(camera_id, path, process)
        self._failed_at.pop(camera_id, None)
        print(f"{self._names.get(camera_id)}: отдаю видео наружу")

    def _stop_publication(self, camera_id: str, reason: str) -> None:
        publication = self._active.pop(camera_id, None)
        if publication is None:
            return
        publication.stop()
        print(f"{self._names.get(camera_id)}: {reason}")

    def reconcile(self, wanted: dict[str, str]) -> None:
        """
        Приводит запущенное в соответствие с желаемым.

        Вынесено отдельным методом сознательно: это вся логика модуля,
        и её надо проверять тестами без потоков, сна и сети.
        """
        # Лишнее — остановить
        for camera_id in list(self._active):
            if camera_id not in wanted:
                self._stop_publication(camera_id, "просмотр закончен")
            elif self._active[camera_id].path != wanted[camera_id]:
                # Открыли новую сессию на ту же камеру: путь сменился,
                # старая публикация теперь ведёт в никуда
                self._stop_publication(camera_id, "сессия сменилась, перезапускаю")
            elif not self._active[camera_id].is_running():
                self._stop_publication(camera_id, "публикация оборвалась, перезапускаю")
                self._failed_at[camera_id] = time.monotonic()

        # Недостающее — запустить
        for camera_id, path in wanted.items():
            if camera_id not in self._active:
                self._start_publication(camera_id, path)

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.reconcile(self._fetch_sessions())
            except Exception as exc:
                if not self._warned:
                    self._warned = True
                    print(
                        f"ретрансляция недоступна: {exc}. "
                        "Если ошибка про active_stream_sessions — "
                        "не применена миграция 0013"
                    )
            self._stopping.wait(self._poll_interval_s)

    def stop(self) -> None:
        self._stopping.set()
        for camera_id in list(self._active):
            self._stop_publication(camera_id, "остановка сервиса")

    def check_available(self) -> str:
        """Проверка при запуске — чтобы состояние было видно в журнале сразу."""
        if not relay_enabled():
            return "выключена (не задан RELAY_URL)"
        if ffmpeg_path() is None:
            return "невозможна: не установлен ffmpeg"
        try:
            self._fetch_sessions()
        except Exception as exc:
            return f"недоступна: {exc}"
        return f"готова, сервер {relay_url()}"
