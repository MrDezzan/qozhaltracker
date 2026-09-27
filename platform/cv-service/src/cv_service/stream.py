from __future__ import annotations

import hmac
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cv_service.snapshot import encode_snapshot

BOUNDARY = "frame"
DEFAULT_PORT = 8089
# Частота потока по локальной сети.
#
# Тридцать — это «как в жизни»: движение перестаёт восприниматься как
# череда картинок. Пятнадцати хватало, чтобы понять, что происходит, но
# глаз всё равно видел рывки, и картинка читалась как видеонаблюдение,
# а не как камера.
#
# Цена вопроса — кодирование JPEG: кадр 960 пикселей по ширине при
# качестве 70 жмётся за единицы миллисекунд, то есть тридцать кадров
# укладываются в десятую долю ядра. Дороже обходится сама съёмка.
#
# Потолок задаёт камера: если она отдаёт 15 кадров, тридцати не будет
# никак — узкое место не здесь.
DEFAULT_FPS = 30.0


def stream_enabled() -> bool:
    """
    Поток по локальной сети включается явно.

    Через интернет живое видео не гоняем: один поток — около двух мегабит
    в секунду, а канал на ферме один на всё хозяйство. Но когда хозяин
    ходит по ферме с телефоном в той же сети, смотреть настоящее видео
    можно и нужно — трафик не выходит за пределы фермы.
    """
    return os.environ.get("STREAM_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def stream_port() -> int:
    raw = os.environ.get("STREAM_PORT", "").strip()
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def stream_token() -> str:
    """
    Пароль на поток. Без него любой, кто попал в сеть фермы, увидит камеры.
    Пустое значение означает, что поток не поднимается вовсе.
    """
    return os.environ.get("STREAM_TOKEN", "").strip()


def stream_fps() -> float:
    raw = os.environ.get("STREAM_FPS", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_FPS
    except ValueError:
        return DEFAULT_FPS
    return value if value > 0 else DEFAULT_FPS


def lan_ip() -> str | None:
    """
    Адрес этой машины в локальной сети.

    Открываем UDP-сокет «в сторону» внешнего адреса и смотрим, какой
    интерфейс выбрала система. Ни одного пакета при этом не уходит —
    UDP-подключение только выбирает маршрут. Способ работает и без
    интернета, лишь бы был настроен шлюз.

    Нужно, чтобы устройство само прописало адрес своего потока: вбивать
    IP руками в админку — ровно тот шаг, на котором живой просмотр
    остаётся выключенным навсегда.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        return None


def stream_host() -> str:
    """
    Имя или адрес, по которому до потока достучится дашборд.

    Определяется само, но перебивается через STREAM_HOST: на ферме с
    несколькими сетями автоматика может выбрать не тот интерфейс.
    """
    override = os.environ.get("STREAM_HOST", "").strip()
    if override:
        return override
    return lan_ip() or "127.0.0.1"


def local_stream_url(camera_id: str) -> str | None:
    """
    Полный адрес потока камеры. None, если поток выключен или нет пароля.

    Пароль входит в адрес. Это допустимо ровно потому, что адрес хранится
    в базе и наружу не отдаётся: браузер получает ссылку на наш сервер,
    а тот уже ходит на устройство сам.
    """
    if not stream_enabled():
        return None
    token = stream_token()
    if not token:
        return None
    return f"http://{stream_host()}:{stream_port()}/stream/{camera_id}?token={token}"


class FrameBuffer:
    """
    Последний кадр каждой камеры.

    Хранится ровно один кадр: смотрящий всегда должен видеть настоящее,
    а не догонять очередь. Если зритель тормозит, он просто пропустит кадры.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._frames: dict[str, bytes] = {}
        self._updated = threading.Condition(self._lock)
        self._viewers = 0

    def put(self, camera_id: str, frame) -> None:
        payload = encode_snapshot(frame)
        with self._lock:
            self._frames[camera_id] = payload
            self._updated.notify_all()

    def get(self, camera_id: str) -> bytes | None:
        with self._lock:
            return self._frames.get(camera_id)

    def wait_for(self, camera_id: str, timeout: float) -> bytes | None:
        with self._lock:
            self._updated.wait(timeout)
            return self._frames.get(camera_id)

    def cameras(self) -> list[str]:
        with self._lock:
            return list(self._frames)

    def has_viewers(self) -> bool:
        """
        Есть ли кто-то, кто смотрит поток.

        Без зрителей кодировать кадры незачем: это восемь JPEG в секунду,
        которые никто не прочитает, и заметная доля процессора мини-ПК.
        """
        with self._lock:
            return self._viewers > 0

    def add_viewer(self) -> None:
        with self._lock:
            self._viewers += 1

    def remove_viewer(self) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)


def _make_handler(buffer: FrameBuffer, token: str, fps: float):
    min_period = 1.0 / fps

    class Handler(BaseHTTPRequestHandler):
        # Журнал сервиса и так подробный; запросы кадров его только засорят
        def log_message(self, *args) -> None:
            return

        def _authorized(self, params) -> bool:
            given = (params.get("token") or [""])[0]
            # Сравнение с постоянным временем: иначе токен подбирается
            # по времени ответа
            return hmac.compare_digest(given, token)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if not self._authorized(params):
                self.send_error(403, "forbidden")
                return

            if parsed.path == "/cameras":
                body = ("\n".join(buffer.cameras())).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if not parsed.path.startswith("/stream/"):
                self.send_error(404, "not found")
                return

            camera_id = parsed.path[len("/stream/") :]
            buffer.add_viewer()
            try:
                self._serve_stream(camera_id)
            finally:
                buffer.remove_viewer()

        def _serve_stream(self, camera_id: str) -> None:
            self.send_response(200)
            self.send_header(
                "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            try:
                while True:
                    payload = buffer.wait_for(camera_id, timeout=min_period * 2)
                    if payload is None:
                        continue
                    self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
                    self.wfile.write(payload)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                # Зритель закрыл вкладку — обычное дело, не ошибка
                return

    return Handler


def start_stream_server(buffer: FrameBuffer) -> ThreadingHTTPServer | None:
    """
    Поднимает поток в локальной сети. Возвращает None, если он выключен
    или не задан пароль.
    """
    if not stream_enabled():
        return None

    token = stream_token()
    if not token:
        print(
            "поток по локальной сети не поднят: не задан STREAM_TOKEN. "
            "Без пароля камеры увидит любой, кто попал в сеть фермы"
        )
        return None

    port = stream_port()
    server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(buffer, token, stream_fps()))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="stream", daemon=True).start()
    print(f"поток по локальной сети: http://<адрес мини-ПК>:{port}/stream/<камера>?token=…")
    return server
