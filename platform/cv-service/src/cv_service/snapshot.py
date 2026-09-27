from __future__ import annotations

import os

import cv2

SNAPSHOT_BUCKET = "snapshots"
DEFAULT_INTERVAL_S = 15.0
DEFAULT_MAX_WIDTH = 960
DEFAULT_QUALITY = 70

# Сколько секунд снимок разрешено держать в кэше. Ноль: путь постоянный,
# файл перезаписывается, и любая задержка означает застывшую картинку.
CACHE_SECONDS = "0"


def snapshot_interval_s() -> float:
    """0 или отрицательное значение выключает отправку снимков."""
    raw = os.environ.get("SNAPSHOT_INTERVAL_S", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_INTERVAL_S


def snapshots_enabled() -> bool:
    return snapshot_interval_s() > 0


def snapshot_path(farm_id: str, camera_id: str) -> str:
    """
    Фиксированный путь: файл перезаписывается, а не копится.
    Первый сегмент — ферма, на нём держится разграничение доступа.
    """
    return f"{farm_id}/{camera_id}.jpg"


def encode_snapshot(
    frame, max_width: int = DEFAULT_MAX_WIDTH, quality: int = DEFAULT_QUALITY
) -> bytes:
    """
    Уменьшает кадр и жмёт в JPEG. Полноразмерный кадр слать незачем:
    предпросмотр смотрят с телефона, а канал на ферме узкий.
    """
    height, width = frame.shape[:2]
    if width > max_width:
        scale = max_width / width
        frame = cv2.resize(frame, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)

    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Не удалось закодировать снимок в JPEG")
    return buffer.tobytes()


def explain_upload_error(error: Exception) -> str:
    """Превращает ответ хранилища в подсказку, что именно чинить."""
    text = str(error)
    lowered = text.lower()

    if "bucket not found" in lowered or "404" in lowered:
        return (
            "хранилище снимков не создано — примените миграцию "
            "supabase/migrations/0003_snapshots.sql"
        )
    if (
        "row-level security" in lowered
        or "unauthorized" in lowered
        or "403" in lowered
        or "violates" in lowered
    ):
        return (
            "хранилище отказало в доступе — примените миграцию "
            "supabase/migrations/0005_fix_snapshot_policies.sql"
        )
    return text


def upload_snapshot(client, farm_id: str, camera_id: str, frame) -> str:
    """Кладёт снимок в хранилище, перезаписывая прошлый. Возвращает путь."""
    path = snapshot_path(farm_id, camera_id)
    payload = encode_snapshot(frame)

    try:
        client.storage.from_(SNAPSHOT_BUCKET).upload(
            path=path,
            file=payload,
            file_options={
                "content-type": "image/jpeg",
                "upsert": "true",
                # Хранилище по умолчанию просит держать файл в кэше час.
                # Для снимка это смертельно: путь один и тот же, файл
                # перезаписывается, а браузер и сеть доставки продолжают
                # отдавать первый кадр — живой просмотр замирает на картинке.
                #
                # Значение только числом: библиотека подставляет его в
                # шаблон «max-age=…», и любое слово превращает заголовок
                # в недействительный «max-age=no-store».
                "cache-control": CACHE_SECONDS,
            },
        )
    except Exception as exc:
        raise RuntimeError(explain_upload_error(exc)) from exc
    return path
