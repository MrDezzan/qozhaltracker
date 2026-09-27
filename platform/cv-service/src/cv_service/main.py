from __future__ import annotations

import os
import threading
import time

import cv2

from cv_service.detector import (
    Detection,
    Detector,
    security_enabled,
    split_by_group,
)
from cv_service.detector import active_profile as detector_profile
from cv_service.detector import get_tracked_class_names
from cv_service.profile import describe as describe_profile
from cv_service.events import AnimalEvent
from cv_service.preview import close_preview, draw_detections, preview_enabled, show_frame
from cv_service import identity
from cv_service.crops import (
    CropCollector,
    IdentificationTracker,
    crops_enabled,
    SHARP_ENOUGH,
    identify,
    insert_seen,
    match_threshold,
    min_margin,
)
from cv_service.morphometry import (
    MorphometryCollector,
    insert_measurement,
    weighing_enabled,
)
from cv_service.live import Heartbeat, LiveWindow, ZoneCache, live_interval_s
from cv_service import recording as recording_module
from cv_service.health import HealthWatcher, can_judge, run_check
from cv_service import views as views_module
from cv_service.activity import ActivityTracker, activity_enabled, describe as describe_path
from cv_service.pipeline import LatestWorker, TaskWorker
from cv_service.remote import RemotePublisher, relay_enabled
from cv_service.security import (
    GuardSettings,
    SecurityWatcher,
    alert_row,
    describe_window,
)
from cv_service.spool import EventSpool, drain
from cv_service.stream import (
    FrameBuffer,
    local_stream_url,
    start_stream_server,
    stream_enabled,
    stream_fps,
    stream_host,
    stream_port,
    stream_token,
)
from cv_service.supabase_client import fetch_animal_names
from cv_service.embedder import (
    Embedder,
    check_available,
    dimension_mismatch,
    embeddings_enabled,
)
from cv_service.autoenroll import (
    AutoEnroller,
    AutoEnrollRules,
    autoenroll_enabled,
    crop_is_good_enough,
    describe_rules,
    register_animal,
    remember_view,
)
from cv_service.headcount import HeadcountAggregator, headcount_interval_s
from cv_service.snapshot import snapshot_interval_s, snapshots_enabled, upload_snapshot
from cv_service import training
from cv_service.zones import Visit, ZoneTracker, describe_zone_change, parse_zones
from cv_service.supabase_client import (
    ensure_session,
    fetch_cameras,
    fetch_zones,
    get_client,
    get_device_farm_id,
    insert_event,
    insert_event_row,
    fetch_active_recording,
    add_recording_embedding,
    set_recording_hint,
    fetch_health_input,
    apply_health_findings,
    add_activity,
    register_camera_stream,
    send_heartbeat,
)

# Версия сборки. Печатается при запуске: по ней сразу видно, поехал ли
# новый код, а не приходится гадать по поведению.
AGENT_VERSION = "2026.08.14a"

HEARTBEAT_INTERVAL_S = 60.0
# Сколько подряд пропущенных кадров считать сбоем, а не рябью
MAX_READ_FAILURES = 30
RECONNECT_DELAY_S = 5.0
# Как часто пробовать отдать накопленное в буфере
SPOOL_DRAIN_INTERVAL_S = 30.0

# Частота работы трекера, кадров в секунду.
#
# Это оказалось важнее всех прочих настроек. ByteTrack сопоставляет объекты
# между СОСЕДНИМИ кадрами: по смещению рамки и по внешнему виду. Когда
# трекер вызывали раз в две секунды, корова успевала пройти полкадра, и
# сопоставление рвалось — каждое появление получало новый номер. Отсюда
# росло и завышенное поголовье (номера считались уникальными животными),
# и дубликаты в распознавании.
#
# Восемь кадров в секунду достаточно для шага животного и посильно для
# мини-ПК без ускорителя. При нехватке мощности снижать до 4, но не ниже.
DEFAULT_TRACK_FPS = 8.0


def track_fps() -> float:
    raw = os.environ.get("TRACK_FPS", "").strip()
    if not raw:
        return DEFAULT_TRACK_FPS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TRACK_FPS
    return value if value > 0 else DEFAULT_TRACK_FPS


def headcount_to_event(summary: dict, farm_id: str, camera_id: str) -> AnimalEvent:
    """
    Сводка по поголовью за окно. Заменяет запись на каждое обнаружение:
    та давала около 200 тысяч строк в сутки на пять животных.
    """
    return AnimalEvent(
        farm_id=farm_id,
        camera_id=camera_id,
        animal_id=None,
        event_type="counted",
        payload=summary,
    )


def visit_to_event(
    visit: Visit, farm_id: str, camera_id: str, animal_id: str | None = None
) -> AnimalEvent:
    """
    Завершённый визит в зону.

    animal_id проставляется, если распознавание успело узнать животное за
    время визита. Именно эта связка превращает «кто-то ел двенадцать минут»
    в «Зорька ела двенадцать минут» — то, ради чего систему и покупают.
    """
    return AnimalEvent(
        farm_id=farm_id,
        camera_id=camera_id,
        animal_id=animal_id,
        event_type="zone_exit",
        payload={
            "zone_id": visit.zone.id,
            "zone_name": visit.zone.name,
            "zone_kind": visit.zone.kind,
            "track_id": visit.track_id,
            "duration_s": round(visit.duration_s, 1),
        },
    )


def parse_video_source(source_uri: str):
    """"0" означает встроенную камеру (нужен int), остальное — путь или RTSP-адрес."""
    return int(source_uri) if source_uri.isdigit() else source_uri


def is_live_source(source_uri: str) -> bool:
    """
    Живой источник или файл.

    Для файла конец — это нормальное завершение. Для камеры обрыв чтения
    означает сбой: моргнуло питание, отвалилась сеть, система забрала
    устройство под другое приложение. Такое надо переживать, а не умирать.
    """
    lowered = source_uri.lower()
    return source_uri.isdigit() or lowered.startswith(("rtsp://", "http://", "https://"))


def open_capture(source_uri: str):
    """Открывает источник. Возвращает None, если не получилось."""
    cap = cv2.VideoCapture(parse_video_source(source_uri))
    return cap if cap.isOpened() else None


def process_camera(
    client,
    detector: Detector,
    farm_id: str,
    camera: dict,
    frame_interval_s: float = 2.0,
    max_frames: int | None = None,
    embedder: Embedder | None = None,
    spool: EventSpool | None = None,
    live_view: LiveWindow | None = None,
    frames: FrameBuffer | None = None,
    guard: SecurityWatcher | None = None,
) -> int:
    """
    Обрабатывает поток одной камеры. Возвращает число записанных событий.

    Внутри две частоты. Трекер работает часто — иначе он не удержит животное
    между кадрами. Всё дорогое (кадры в хранилище, векторы, запись событий)
    идёт по редкому интервалу frame_interval_s.

    max_frames используется в тестах, чтобы цикл был конечным.
    """
    source_uri = camera["source_uri"]
    source_is_live = is_live_source(source_uri)

    cap = open_capture(source_uri)
    if cap is None:
        raise RuntimeError(f"Не удалось открыть источник видео: {source_uri}")

    headcount = HeadcountAggregator(interval_s=headcount_interval_s())
    collect_crops = crops_enabled()
    crop_collector = CropCollector() if collect_crops else None
    identification = IdentificationTracker()
    # Клички и идентификаторы опознанных животных по номеру трека
    track_names: dict[int, str] = {}
    track_animals: dict[int, str] = {}

    # Силуэт снимается только с камер над животными: сбоку площадь
    # проекции зависит от поворота и с массой не связана
    if live_view is not None and not live_view.is_alive():
        print(
            f"{camera['name']}: опрос живого режима не запущен — "
            "живой просмотр работать не будет"
        )

    measure_bodies = (
        weighing_enabled()
        and camera.get("placement") in detector_profile().measure_placements
    )

    morphometry = MorphometryCollector() if measure_bodies else None

    # Путь животного. Без калибровки не считается вовсе: пиксель ничего
    # не значит, а число «в пикселях» человек прочтёт как метры
    scale = camera.get("cm_per_pixel")
    activity = ActivityTracker(cm_per_pixel=float(scale)) if (scale and activity_enabled()) else None
    if activity_enabled() and not scale:
        print(
            f"{camera['name']}: активность не считается — камера не "
            "откалибрована, метров из пикселей не получить"
        )

    # Система сама запоминает незнакомую особь и со следующего раза
    # узнаёт её. Без модели признаков это невозможно: сравнивать нечем
    auto = None
    if embedder is not None and autoenroll_enabled():
        auto = AutoEnroller(AutoEnrollRules.from_env())

    # Запись эталонов идёт с этой же камеры. Без модели признаков писать
    # нечего: эталон — это вектор, а считает его именно она
    recorder = None
    if embedder is not None:
        recorder = recording_module.RecordingWatcher(
            lambda: fetch_active_recording(client, camera["id"]),
            camera_id=str(camera["id"]),
        )
        recorder.refresh()
        recorder.start()
    recording_progress: recording_module.RecordingProgress | None = None

    # Ракурс животного: бок, другой бок, спереди, сзади. Нужен только во
    # время записи — в остальное время считать его незачем
    view_estimator = views_module.ViewEstimator() if recorder is not None else None

    zones_cache = ZoneCache(lambda: fetch_zones(client, camera["id"]))
    zone_tracker = ZoneTracker(zones=parse_zones(zones_cache.prime()))
    zones_version = 1
    zones_cache.start()
    if zone_tracker.zones:
        names = ", ".join(f"«{zone.name}»" for zone in zone_tracker.zones)
        print(f"{camera['name']}: зон настроено {len(zone_tracker.zones)} — {names}")
    else:
        print(f"{camera['name']}: зон не настроено")

    # Всё, что ходит в сеть или считает долго, уходит в отдельные потоки.
    # Иначе один вектор признаков на процессоре (секунда-две) останавливал
    # и трекинг, и живой просмотр — как раз то, ради чего живой просмотр есть.
    # Рисование рамок тоже уходит в поток: оно дешёвое, но в основном цикле
    # ничем не защищено, и сбой отрисовки уронил бы обработку целиком
    uploader = LatestWorker(
        lambda job: upload_snapshot(
            client, farm_id, camera["id"], draw_detections(*job)
        ),
        name=f"snapshot-{camera['name']}",
    )
    uploader.start()

    heavy = TaskWorker(name=f"heavy-{camera['name']}")
    heavy.start()

    events_written = 0
    frames_seen = 0
    def beat():
        ensure_session(client)
        send_heartbeat(client)

    heartbeat = Heartbeat(beat, interval_s=HEARTBEAT_INTERVAL_S)
    heartbeat.start()

    last_track = 0.0
    last_heavy = 0.0
    last_drain = 0.0
    track_period = 1.0 / track_fps()
    stream_period = 1.0 / stream_fps()
    last_stream = 0.0
    show_window = preview_enabled()
    send_snapshots = snapshots_enabled()
    snapshot_every_s = snapshot_interval_s()
    live_every_s = live_interval_s()
    last_snapshot = 0.0
    was_live = False
    last_live_report = 0.0
    last_detections: list[Detection] = []
    # Морды тех, кто сейчас у корма. Держим отдельно от detections:
    # туловище и голова показываются ОДНОВРЕМЕННО, одно не заменяет
    # другое. Контур нужен для веса и промеров, отметка морды — чтобы
    # видеть, что засчитано кормление, а не стояние рядом
    feeding_heads: dict[int, tuple[float, float]] = {}
    read_failures = 0

    # --- сбор кадров для дообучения ---
    #
    # Сбор идёт на срок и выключается сам. Проверяем его не один раз при
    # запуске, а на каждой выборке: обработка на ферме работает неделями
    # без перезапуска, и сбор, включённый на две недели, обязан кончиться
    # сам, а не остаться до следующей перезагрузки.
    training_every_s = training.interval_s()
    training_cap = training.daily_cap()
    last_training = 0.0
    training_index = 0
    training_prev_count: int | None = None
    training_saved_today = 0
    training_day = ""

    if training.collecting():
        print(
            f"{camera['name']}: идёт сбор кадров для дообучения "
            f"до {training.collect_until()} включительно, "
            f"не больше {training_cap} кадров в сутки"
        )

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                if not source_is_live:
                    # Файл кончился — это нормальное завершение
                    break

                read_failures += 1
                if read_failures > MAX_READ_FAILURES:
                    print(f"{camera['name']}: связь потеряна, переподключаюсь")
                    cap.release()
                    time.sleep(RECONNECT_DELAY_S)
                    reopened = open_capture(source_uri)
                    if reopened is None:
                        print(f"{camera['name']}: источник недоступен, жду")
                        time.sleep(RECONNECT_DELAY_S)
                        continue
                    cap = reopened
                    read_failures = 0
                    print(f"{camera['name']}: связь восстановлена")
                else:
                    # Одиночный пропуск кадра — обычное дело, просто ждём
                    time.sleep(0.1)
                continue

            read_failures = 0
            frames_seen += 1
            if max_frames is not None and frames_seen > max_frames:
                break

            now = time.monotonic()

            if show_window:
                # Рисуем последние найденные объекты на каждом кадре,
                # иначе рамки моргали бы между опросами трекера
                if not show_frame(
                    camera["name"],
                    draw_detections(frame, last_detections, track_names, feeding_heads),
                ):
                    break

            if spool is not None and now - last_drain >= SPOOL_DRAIN_INTERVAL_S:
                heavy.submit(lambda: _drain_spool(client, spool, camera))
                last_drain = now

            updated = zones_cache.take_if_changed(zones_version)
            if updated is not None:
                zones_version, rows = updated
                before = list(zone_tracker.zones)
                closed = zone_tracker.set_zones(parse_zones(rows))
                _write_visits(client, farm_id, camera, closed, track_animals, spool)
                change = describe_zone_change(before, zone_tracker.zones)
                if change:
                    print(f"{camera['name']}: зоны обновлены — {change}")

            # --- поток по локальной сети: отдельная, более высокая частота ---
            # Кадры идут с частотой камеры, а рамки берутся от последнего
            # опроса трекера. Так картинка плавная, а модель не насилуется:
            # человеческий глаз разницы между 8 и 30 опросами не заметит,
            # а между 1 и 15 кадрами — заметит сразу.
            if frames is not None and frames.has_viewers():
                if now - last_stream >= stream_period:
                    try:
                        frames.put(
                            camera["id"],
                            draw_detections(
                                frame, last_detections, track_names, feeding_heads
                            ),
                        )
                    except Exception as exc:
                        print(f"кадр в локальный поток не попал: {exc}")
                    last_stream = now

            # --- частый контур: трекинг и всё, что от него зависит ---
            if now - last_track < track_period:
                continue
            last_track = now

            found = detector.detect_and_track(frame)
            height, width = frame.shape[:2]

            # РАЗДЕЛЕНИЕ. Всё, что ниже, работает со скотом и только с ним.
            #
            # Стоит человеку просочиться в общий поток — и он войдёт в
            # поголовье, его стояние у кормушки запишется как кормление,
            # его силуэт уйдёт в обучающую выборку для веса, а его лицо —
            # в базу векторов признаков, где ему уж точно не место.
            # Ошибка при этом тихая: система работает, цифры врут.
            #
            # Поэтому `detections` ниже — это ИМЕННО скот, а `intruders`
            # уходит отдельной веткой и больше нигде не появляется.
            detections, intruders = split_by_group(found)
            last_detections = found      # рисуем на кадре и тех, и других

            if guard is not None:
                _watch_for_intruders(
                    client, farm_id, camera, guard, intruders,
                    zone_tracker, width, height, now, frame,
                )

            # Заданием для отправки идёт копия кадра: сам кадр камера
            # перезапишет раньше, чем поток до него доберётся
            def snapshot_job():
                return (frame.copy(), detections, dict(track_names), dict(feeding_heads))

            if live_view is not None and send_snapshots:
                watching = live_view.is_live(camera["id"], now)
                if watching and not was_live:
                    print(f"{camera['name']}: включён живой просмотр")
                elif was_live and not watching:
                    print(f"{camera['name']}: живой просмотр закончен")
                was_live = watching

                if watching and now - last_snapshot >= live_every_s:
                    uploader.submit(snapshot_job())
                    last_snapshot = now

                    # Подтверждаем работу цифрой: молчание журнала одинаково
                    # выглядит и когда кадры доходят, и когда нет.
                    # Считаем именно доставленные хранилищем.
                    if now - last_live_report >= 15.0:
                        print(
                            f"{camera['name']}: кадров доставлено "
                            f"{uploader.completed}, потеряно при отставании "
                            f"{uploader.dropped}"
                        )
                        last_live_report = now

            headcount.add(detections, now)

            if morphometry is not None:
                morphometry.add(detections, width, height)

            if zone_tracker.zones:
                _, finished = zone_tracker.update(detections, width, height, now=now)
                feeding_heads = zone_tracker.current_heads()
                events_written += _write_visits(
                    client, farm_id, camera, finished, track_animals, spool
                )

            if headcount.due(now):
                summary = headcount.take()
                if summary is not None:
                    events_written += _write_event(
                        client, headcount_to_event(summary, farm_id, camera["id"]), spool
                    )

            # --- редкий контур: всё дорогое ---
            if now - last_heavy < frame_interval_s:
                continue
            last_heavy = now

            print(
                f"[{time.strftime('%H:%M:%S')}] {camera['name']}: "
                f"обнаружено животных: {len(detections)}"
            )

            if send_snapshots and now - last_snapshot >= snapshot_every_s:
                # Кадр с рамками — так в интерфейсе видно не только «что»,
                # но и «где» система нашла животное
                uploader.submit(snapshot_job())
                last_snapshot = now

            # --- кадр для дообучения ---
            #
            # Здесь кадр берётся ЧИСТЫМ, до отрисовки. Снимок выше уходит
            # через `draw_detections` и для обучения непригоден: модель
            # научилась бы искать зелёные линии, а не животных.
            if now - last_training >= training_every_s:
                last_training = now

                # Суточный счётчик сбрасывается при смене дня. Без этого
                # потолок сработал бы один раз и сбор бы встал навсегда
                today = time.strftime("%Y-%m-%d")
                if today != training_day:
                    training_day = today
                    training_saved_today = 0

                if training.collecting():
                    reason = training.pick_reason(
                        detections, training_prev_count, training_index
                    )
                    training_index += 1
                    training_prev_count = len(detections)

                    if reason is not None and training_saved_today < training_cap:
                        training_saved_today += 1
                        # Копия кадра: камера перезапишет свой буфер
                        # раньше, чем поток отправки до него доберётся
                        heavy.submit(
                            _training_job(
                                client, farm_id, camera["id"],
                                frame.copy(), reason, list(detections),
                            )
                        )

            # Запись эталонов. Идёт раньше обычного опознания: пока
            # человек ведёт животное мимо камеры, узнавать его не нужно —
            # нужно запомнить
            if recorder is not None:
                session = recorder.current()
                if session is None:
                    recording_progress = None
                else:
                    if (
                        recording_progress is None
                        or recording_progress.session_id != session.id
                    ):
                        recording_progress = recording_module.RecordingProgress(
                            session_id=session.id
                        )
                        print(f"{camera['name']}: {recording_module.describe(session)}")

                    if session.quota_full:
                        # Своё эта камера набрала. Вторая может отставать —
                        # сеанс живой, но мешать ей незачем: лишние кадры
                        # с одной камеры перекосили бы набор эталонов в её
                        # сторону, а узнавать надо с обеих
                        if recording_progress.hint_changed("__quota__"):
                            print(
                                f"{camera['name']}: своё набрано "
                                f"({session.mine} из {session.per_camera}), "
                                "ждём остальные камеры"
                            )
                    elif recording_progress.accepts(now):
                        reason = recording_module.why_not(detections, width, height)

                        # Подсказка уходит в базу, только когда изменилась:
                        # человек у камеры должен видеть, ПОЧЕМУ счётчик
                        # стоит, а не гадать
                        changed = recording_progress.hint_changed(reason)

                        # В журнал — при смене причины и раз в десять
                        # секунд просто так. Тишина в журнале читается как
                        # «ничего не работает», даже когда всё работает
                        if changed or recording_progress.due_to_report(now):
                            waiting = (
                                f", ждём ракурс {session.awaiting_view}"
                                if session.awaiting_view
                                else ""
                            )
                            print(
                                f"{camera['name']}: запись «{session.label}» "
                                f"кадров {session.captured}{waiting} — "
                                f"{reason or 'кадр годится, берём'}"
                            )

                        if changed:
                            heavy.submit(
                                lambda sid=session.id, text=reason,
                                       cam=str(camera["id"]): _say_why(
                                    client, sid, text, cam
                                )
                            )

                        subject = (
                            None
                            if reason
                            else recording_module.pick_single_subject(
                                detections, width, height
                            )
                        )
                        view = None

                        if subject is not None:
                            # Ракурс копится по треку и объявляется, только
                            # когда продержался. None — обычный ответ:
                            # животное поворачивается, ракурса у него нет
                            detected = None
                            if view_estimator is not None:
                                detected = view_estimator.observe(
                                    subject.track_id, subject.bbox, now
                                )

                            # Пометка ракурса — сведение о кадре, а не
                            # условие продвижения. Шагов больше нет:
                            # человек ведёт животное по кругу, и кадры
                            # набираются подряд. Распознали ракурс —
                            # записали, не распознали — тоже записали
                            view = detected

                        if subject is not None:
                            x1, y1, x2, y2 = (int(v) for v in subject.bbox)
                            patch = frame[y1:y2, x1:x2].copy()
                            recording_progress.last_taken_at = now
                            heavy.submit(
                                lambda image=patch, sid=session.id,
                                       progress=recording_progress, moment=now,
                                       taken_view=view,
                                       cam=str(camera["id"]): _record_reference(
                                    client, embedder, image, sid, progress, moment,
                                    recorder, taken_view, cam
                                )
                            )

            if activity is not None:
                activity.add(detections, now)

            if crop_collector is not None:
                crop_collector.add(frame, detections, now)

                # Опознаём, пока животное ещё в кадре, чтобы показать кличку.
                # Считается в фоне: кличка появится на секунду позже, зато
                # видео не встанет на время работы модели.
                if embedder is not None:
                    pending = crop_collector.ready_to_identify(
                        identification.skip(now), now
                    )
                    for crop in pending:
                        identification.record_attempt(crop.track_id, now)
                    if pending:
                        heavy.submit(
                            lambda crops=pending: _identify_crops(
                                client,
                                farm_id,
                                crops,
                                embedder,
                                identification,
                                track_names,
                                track_animals,
                                str(camera["id"]),
                                crop_collector,
                            )
                        )

                finished = crop_collector.take_finished(now)
                if finished:
                    heavy.submit(
                        lambda crops=finished: _save_crops(
                            client,
                            farm_id,
                            camera,
                            crops,
                            embedder,
                            track_animals,
                            morphometry,
                            identification,
                            track_names,
                            auto,
                            activity,
                        )
                    )

    finally:
        if recorder is not None:
            recorder.stop()
        cap.release()
        if show_window:
            close_preview()
        if heavy.dropped or uploader.dropped:
            print(
                f"{camera['name']}: не успевали — отброшено кадров "
                f"{uploader.dropped}, заданий {heavy.dropped}"
            )
        # Накопленное доделываем: незаписанные наблюдения жальче задержки
        heavy.drain()
        heavy.stop()
        uploader.stop()
        heartbeat.stop()
        zones_cache.stop()
        # Незакрытые визиты не должны пропадать при остановке
        _write_visits(
            client, farm_id, camera, zone_tracker.flush(), track_animals, spool
        )
        if crop_collector is not None:
            _save_crops(
                client,
                farm_id,
                camera,
                crop_collector.flush(),
                embedder,
                track_animals,
                morphometry,
                identification,
                track_names,
                auto,
                activity,
            )

    return events_written


def _drain_spool(client, spool: EventSpool, camera: dict) -> None:
    """Отдаёт накопленное за время обрыва связи."""
    pending = spool.count()
    if not pending:
        return
    sent = drain(spool, lambda row: insert_event_row(client, row))
    if sent:
        print(f"{camera['name']}: отправлено из буфера {sent} из {pending}")


def _write_event(client, event: AnimalEvent, spool: EventSpool | None) -> int:
    """
    Пишет событие, а при недоступной базе кладёт его в буфер на диске.

    Событие несёт своё время (occurred_at ставит устройство), поэтому
    отложенная отправка не искажает историю — в базе оно встанет туда,
    где и произошло.
    """
    try:
        insert_event(client, event)
        return 1
    except Exception as exc:
        if spool is None:
            print(f"событие не отправлено: {exc}")
            return 0
        spool.put(event.to_row())
        print(f"событие отложено в буфер ({exc})")
        return 0


def _identify_live(
    client,
    farm_id,
    crop_collector,
    embedder,
    identification: IdentificationTracker,
    track_names,
    track_animals,
    now,
    camera_id: str | None = None,
) -> None:
    """
    Отбирает кадры, готовые к опознанию, и опознаёт их.

    Отбор быстрый и остаётся в основном цикле, само опознание — долгое.
    В рабочем режиме их разносят: отбор здесь, вычисление в фоновом потоке.
    """
    pending = crop_collector.ready_to_identify(identification.skip(now), now)
    for crop in pending:
        identification.record_attempt(crop.track_id, now)
    _identify_crops(
        client,
        farm_id,
        pending,
        embedder,
        identification,
        track_names,
        track_animals,
        camera_id,
        crop_collector,
    )


def _say_why(
    client, session_id: str, reason: str, camera_id: str | None = None
) -> None:
    """Отправляет подсказку. Ошибку глушим: запись важнее подсказки."""
    try:
        set_recording_hint(client, session_id, reason, camera_id)
    except Exception as exc:
        print(f"подсказка к записи не отправлена: {exc}")


def _record_reference(
    client,
    embedder,
    image,
    session_id: str,
    progress,
    moment: float,
    recorder,
    view: str | None = None,
    camera_id: str | None = None,
) -> None:
    """
    Считает вектор кадра и записывает его как эталон.

    В фоновом потоке: вектор считается секунду-две, и делать это в цикле
    захвата значило бы остановить видео ровно тогда, когда человек ведёт
    животное мимо камеры.

    Кадр, похожий на уже записанные, выбрасывается здесь, а не до счёта:
    насколько он похож, видно только по вектору.
    """
    try:
        embedding = embedder.encode(image)
    except Exception as exc:
        print(f"эталон не посчитан: {exc}")
        return

    # Длину проверяем здесь, а не по ошибке базы: база отбивает каждый
    # кадр одним и тем же сообщением про размерности, и из журнала это
    # читается как «запись не работает», без всякого намёка на причину
    mismatch = dimension_mismatch(embedding)
    if mismatch:
        print(f"ВНИМАНИЕ: {mismatch}")
        return

    if not recording_module.is_new_angle(embedding, progress.embeddings):
        # Та же поза, что уже записана. Молча пропускаем: за прогон таких
        # кадров большинство, и сообщать о каждом незачем
        return

    try:
        captured = add_recording_embedding(
            client, session_id, embedding, view, camera_id
        )
    except Exception as exc:
        print(f"эталон не сохранён: {exc}")
        return

    if captured == -2:
        # Квота этой камеры набрана, пока кадр считался. Не ошибка:
        # вектор считается секунду-две, за это время в базе всё могло
        # закрыться. Обновляемся, чтобы цикл перестал слать кадры
        if recorder is not None:
            recorder.refresh()
        return

    if captured < 0:
        return

    progress.remember(embedding, moment)
    # Счётчик на экране обновляется из базы, но человек стоит у загона и
    # смотрит на животное, а не на экран. Строка в журнале нужна на
    # случай разбора: почему запись встала на пяти из двенадцати
    print(f"эталон записан: {captured}")

    if recorder is not None:
        recorder.refresh()


def _crop_quality(crop) -> float:
    """
    Насколько кадру можно верить, от 0 до 1.

    Резкость приводится к доле от «вполне чёткого»: `sharpness` — это
    дисперсия лапласиана, число без верхней границы, и подставлять его
    как долю нельзя.
    """
    чёткость = (
        min(1.0, crop.sharpness / SHARP_ENOUGH) if SHARP_ENOUGH > 0 else 1.0
    )
    return identity.crop_quality(crop.area, crop.confidence, чёткость)


def _identify_crops(
    client,
    farm_id: str,
    crops,
    embedder,
    identification: IdentificationTracker,
    track_names: dict[int, str],
    track_animals: dict[int, str],
    camera_id: str | None = None,
    crop_collector=None,
) -> None:
    """
    Считает векторы и ищет знакомых животных.

    Тяжёлая часть: на процессоре без ускорителя один вектор считается
    секунду-две. Поэтому вызывается из фонового потока — иначе на это
    время останавливались бы и трекинг, и живой просмотр.

    Кличка появляется на экране с задержкой в секунду. Это заметно меньшая
    беда, чем замерший видеопоток.

    Уверенное совпадение принимается сразу, по одному кадру. Спорное —
    когда второй кандидат идёт вплотную — не принимается и не
    отбрасывается: кандидат запоминается, кадр трека сбрасывается, и
    через секунду вопрос задаётся заново по ДРУГОМУ кадру. Кличка
    называется, когда два разных кадра сошлись на одном животном.

    Решение принимается СРАЗУ ПРО ВЕСЬ КАДР, а не по кропу за раз.
    Раньше каждый кроп опознавался сам по себе, и проверки «занята ли
    эта кличка другим треком» не было вовсе: две коровы рядом могли обе
    стать Зорькой. Правило раздачи живёт в `identity.assign` — отдельно
    от сети и базы, и потому проверено целиком.
    """
    наблюдения = []
    ответы: dict[int, object] = {}

    for crop in crops:
        try:
            embedding = embedder.encode(crop.image)
            match = identify(client, farm_id, embedding, camera_id=camera_id)
        except Exception as exc:
            print(f"опознание не выполнено: {exc}")
            continue
        ответы[crop.track_id] = match
        наблюдения.append(
            identity.Seen(
                track_id=crop.track_id,
                quality=_crop_quality(crop),
                candidates=tuple(
                    identity.Candidate(имя, расстояние)
                    for имя, расстояние in match.candidates
                ),
            )
        )

    # Клички, уже закреплённые за живыми треками. Своему треку кличка не
    # мешает, чужому недоступна: животное, которое сейчас видно вон там,
    # не может оказаться ещё и здесь
    закреплено = {
        animal: track for track, animal in track_animals.items() if animal
    }
    решения = identity.assign(
        наблюдения, match_threshold(), min_margin(), taken=закреплено
    )
    по_треку = {v.track_id: v for v in решения}
    видели = {s.track_id: s for s in наблюдения}

    for crop in crops:
        match = ответы.get(crop.track_id)
        if match is None:
            continue

        решение = по_треку.get(crop.track_id)
        animal_id = решение.animal_id if решение is not None else None
        спорно = решение is not None and решение.quality == identity.AMBIGUOUS
        ближайший = (
            identity.candidate_of(решение, видели[crop.track_id])
            if решение is not None
            else ""
        )

        if not animal_id and спорно and ближайший:
            # Кандидаты идут вплотную. Назвать ближайшего — то же самое,
            # что подбросить монету, а неверная кличка на кадре стоит
            # дороже, чем её отсутствие
            agreed = identification.vote(crop.track_id, ближайший)

            # Голосование идёт мимо общей раздачи, и дыру в правиле «одна
            # кличка — один трек» оно способно проделать само: два
            # спорных трека с одним и тем же ближайшим наберут голоса
            # независимо и получат одну кличку на двоих
            занял = закреплено.get(agreed) if agreed else None
            if agreed and занял is not None and занял != crop.track_id:
                print(
                    f"спорно (трек {crop.track_id}): переспрос сошёлся на том, "
                    f"кто уже занят треком {занял} — не называю"
                )
                agreed = None

            if agreed:
                animal_id = agreed
                голосов = identification.votes(crop.track_id)
                identification.record_success(crop.track_id, by_vote=True)
                print(
                    f"узнано с переспроса (трек {crop.track_id}): "
                    f"{голосов} кадра сошлись"
                )
            else:
                # Другой кадр того же трека, иначе второй заход считал бы
                # вектор по тому же самому и получил бы тот же ответ
                if crop_collector is not None:
                    crop_collector.refresh(crop.track_id)
                print(
                    f"спорно (трек {crop.track_id}): {решение.reason} — "
                    "переспрошу по другому кадру"
                )
                continue

        if not animal_id:
            # Не отчаиваемся: животное могло стоять боком. Следующая
            # попытка будет через паузу, всего их несколько.
            #
            # Числа печатаем всегда: без них «не узнано» не отличить от
            # «не узнано, но был почти похож», а лечится это разным
            print(f"не узнано (трек {crop.track_id}): {match.explain()}")
            continue

        identification.record_success(crop.track_id)
        track_animals[crop.track_id] = animal_id
        закреплено[animal_id] = crop.track_id
        try:
            names = fetch_animal_names(client, [animal_id])
            track_names[crop.track_id] = names.get(animal_id, "")
            if track_names[crop.track_id]:
                print(f"узнано: {track_names[crop.track_id]} (трек {crop.track_id})")
        except Exception as exc:
            print(f"кличка не получена: {exc}")


def _look_up(
    client,
    farm_id: str,
    crops,
    embedder,
    camera: dict,
    track_animals: dict[int, str],
) -> dict[int, tuple]:
    """
    Посчитать векторы пачки кропов и раздать клички по одному правилу.

    Возвращает трек → (вектор, ответ базы, решение). Вынесено отдельно,
    потому что мест, где надо узнать животное, два — живой кадр и
    закрытие трека, — а правило раздачи должно быть одно. Пока оно было
    списано дважды, второе место успело разойтись с первым.
    """
    наблюдения = []
    сырое: dict[int, tuple] = {}

    for crop in crops:
        try:
            embedding = embedder.encode(crop.image)
            match = identify(
                client, farm_id, embedding, camera_id=str(camera["id"])
            )
        except Exception as exc:
            print(f"опознание не выполнено: {exc}")
            continue
        сырое[crop.track_id] = (embedding, match)
        наблюдения.append(
            identity.Seen(
                track_id=crop.track_id,
                quality=_crop_quality(crop),
                candidates=tuple(
                    identity.Candidate(имя, расстояние)
                    for имя, расстояние in match.candidates
                ),
            )
        )

    закреплено = {animal: track for track, animal in track_animals.items() if animal}
    решения = identity.assign(
        наблюдения, match_threshold(), min_margin(), taken=закреплено
    )
    по_треку = {v.track_id: v for v in решения}

    return {
        track: (вектор, ответ, по_треку.get(track))
        for track, (вектор, ответ) in сырое.items()
    }


def _save_crops(
    client,
    farm_id: str,
    camera: dict,
    crops,
    embedder,
    track_animals: dict[int, str] | None = None,
    morphometry: MorphometryCollector | None = None,
    identification: IdentificationTracker | None = None,
    track_names: dict[int, str] | None = None,
    auto: AutoEnroller | None = None,
    activity: ActivityTracker | None = None,
) -> None:
    """
    Закрывает завершённые треки: записывает встречу узнанного животного
    и его обмеры.

    Раньше сюда попадал КАЖДЫЙ трек: кадр уходил в хранилище, строка —
    в базу, и всё неопознанное копилось в очереди «ждут имени», которую
    человек должен был разбирать вручную. От этого отказались, и вот
    почему.

    Во-первых, эталон из такой очереди — это догадка. Человек опознавал
    животное на глаз по мутному кадру со спины, и ошибка закреплялась
    навсегда: дальше система сравнивала новые кадры с неверным образцом.

    Во-вторых, очередь не кончалась. Каждый проход животного мимо камеры
    добавлял в неё кадр, разбирать их было некому, и она превращалась
    в свалку, которую перестают открывать.

    Теперь эталоны берутся из записи с камеры, сделанной человеком
    осознанно. Неузнанное животное просто не записывается: пустая строка
    честнее выдуманной.
    """
    track_animals = track_animals if track_animals is not None else {}

    # Последняя попытка узнать тех, кого не узнали при жизни трека: за
    # визит животное могло ни разу не встать удобно, а на лучшем кадре —
    # встать.
    #
    # Решение и здесь принимается про всю пачку разом, тем же правилом:
    # эти треки закрываются одновременно, и раздать двум из них одну
    # кличку так же нельзя, как и в живом кадре
    неузнанные = [
        crop
        for crop in crops
        if track_animals.get(crop.track_id) is None and embedder is not None
    ]
    поздние = _look_up(client, farm_id, неузнанные, embedder, camera, track_animals)

    for crop in crops:
        animal_id = track_animals.get(crop.track_id)
        embedding, match, решение = поздние.get(crop.track_id, (None, None, None))
        if animal_id is None and решение is not None:
            animal_id = решение.animal_id or None

        # Кто-то похожий уже заведён, просто похожих сразу несколько.
        # Заводить третью запись того же животного нельзя: кандидатов
        # станет больше, отрыв между ними меньше, и система перестанет
        # узнавать вообще кого-либо
        спорно = решение is not None and решение.quality == identity.AMBIGUOUS
        if animal_id is None and спорно:
            print(
                f"{camera['name']}: похоже сразу на нескольких заведённых "
                f"({решение.reason}) — не называю и новую запись не завожу"
            )
            if auto is not None:
                auto.forget(crop.track_id)
            if activity is not None:
                activity.forget(crop.track_id)
            _forget_track(
                crop.track_id, track_animals, track_names, identification, morphometry
            )
            continue

        # Незнакомая особь: заводим сами, чтобы со следующего раза
        # узнавать. Человек потом переименует «№ 12» в «Зорьку»
        if animal_id is None and auto is not None and embedding is not None:
            allowed, why = auto.consider(
                crop, nearest=match.distance if match is not None else None
            )
            if allowed:
                try:
                    created = register_animal(client, farm_id, embedding)
                    animal_id = (created or {}).get("id")
                    label = (created or {}).get("label", "")
                    if animal_id:
                        track_animals[crop.track_id] = animal_id
                        if track_names is not None:
                            track_names[crop.track_id] = label
                        print(f"{camera['name']}: запомнил новую особь {label}")
                except Exception as exc:
                    print(f"новая особь не заведена: {exc}")
            else:
                print(f"{camera['name']}: не завожу особь — {why}")

        elif animal_id is not None and embedding is not None and auto is not None:
            # Новый ракурс запоминаем — именно так узнавание со временем
            # становится надёжным. Но НЕ каждый: правило в
            # `identity.worth_remembering`, и оно отсекает два случая,
            # которые раньше проходили молча.
            #
            # Тот же ракурс: банк на двенадцать эталонов, вытесняется
            # старейший, и десять одинаковых спин выбрасывают
            # единственный профиль. Узнавание сбоку пропадает.
            #
            # Узнанное с переспроса: показать кличку двух сошедшихся
            # кадров хватает, положить в эталоны — нет. Кличка живёт
            # секунду, эталон вечно
            стоит, почему = identity.worth_remembering(
                решение if решение is not None else identity.Verdict(crop.track_id),
                crop_ok=crop_is_good_enough(crop, auto.rules) is None,
                voted=identification is not None
                and identification.was_voted(crop.track_id),
            )
            if стоит:
                try:
                    remember_view(client, animal_id, embedding)
                except Exception as exc:
                    print(f"ракурс не запомнен: {exc}")
            else:
                print(f"{camera['name']}: ракурс не запоминаю — {почему}")

        if animal_id is None:
            details = match.explain() if match is not None else "опознание не выполнялось"
            print(
                f"{camera['name']}: животное не узнано, трек {crop.track_id} — "
                f"{details}"
            )
            if auto is not None:
                auto.forget(crop.track_id)
            # Путь неузнанного животного выбрасываем: приписать его
            # некому, а «активность неизвестно чья» никому не нужна
            if activity is not None:
                activity.forget(crop.track_id)
            _forget_track(
                crop.track_id, track_animals, track_names, identification, morphometry
            )
            continue

        try:
            insert_seen(client, farm_id, camera["id"], animal_id, crop)
        except Exception as exc:
            print(f"встреча не записана: {exc}")

        if morphometry is not None:
            _save_measurement(
                client, farm_id, camera, crop.track_id, morphometry, animal_id, None
            )

        if activity is not None:
            _save_activity(client, camera, crop.track_id, activity, animal_id)

        if auto is not None:
            auto.forget(crop.track_id)
        _forget_track(crop.track_id, track_animals, track_names, identification, morphometry)


def _save_activity(
    client,
    camera: dict,
    track_id: int,
    activity: ActivityTracker,
    animal_id: str,
) -> None:
    """
    Путь за визит — в суточную сводку животного.

    Пишется по одному визиту, а не раз в сутки: трек кончается, когда
    животное вышло из кадра, и держать день в памяти устройства значило
    бы терять его при каждом перезапуске.
    """
    result = activity.take(track_id)
    if result is None:
        return

    meters, steps, seconds = result
    if steps == 0:
        # Животное простояло весь визит. Ноль метров записать надо: без
        # этого «стояла весь день» не отличить от «её не было»
        pass

    try:
        add_activity(client, animal_id, meters, steps, seconds)
        print(f"{camera['name']}: {describe_path(meters, seconds)}")
    except Exception as exc:
        print(f"активность не сохранена: {exc}")


def _save_measurement(
    client,
    farm_id: str,
    camera: dict,
    track_id: int,
    morphometry: MorphometryCollector,
    animal_id: str | None,
    sighting_id: str | None,
) -> None:
    """Итоговый обмер силуэта за визит — по нему потом считается вес."""
    silhouette = morphometry.summarize(track_id)
    if silhouette is None:
        # Замеров было мало или все негодные — молча пропускаем.
        # Лучше не измерить, чем измерить неправильно.
        return
    try:
        insert_measurement(
            client,
            farm_id,
            camera["id"],
            track_id,
            silhouette,
            animal_id=animal_id,
            sighting_id=sighting_id,
            cm_per_pixel=camera.get("cm_per_pixel"),
        )
    except Exception as exc:
        print(f"обмер не сохранён: {exc}")


def _forget_track(
    track_id: int,
    track_animals: dict,
    track_names: dict | None,
    identification: IdentificationTracker | None,
    morphometry: MorphometryCollector | None,
) -> None:
    """
    Убирает следы завершённого трека.

    Без этого словари росли всё время работы процесса: номера треков
    не переиспользуются, а сервис на ферме работает месяцами.
    """
    track_animals.pop(track_id, None)
    if track_names is not None:
        track_names.pop(track_id, None)
    if identification is not None:
        identification.forget(track_id)
    if morphometry is not None:
        morphometry.forget(track_id)


def _write_visits(
    client,
    farm_id: str,
    camera: dict,
    visits: list[Visit],
    track_animals: dict[int, str] | None = None,
    spool: EventSpool | None = None,
) -> int:
    track_animals = track_animals or {}
    written = 0
    for visit in visits:
        animal_id = track_animals.get(visit.track_id)
        who = "" if not animal_id else " (животное опознано)"
        print(
            f"{camera['name']}: визит в «{visit.zone.name}» "
            f"завершён, {visit.duration_s:.0f} с{who}"
        )
        written += _write_event(
            client, visit_to_event(visit, farm_id, camera["id"], animal_id), spool
        )
    return written


def run(frame_interval_s: float = 2.0) -> None:
    client = get_client()
    farm_id = get_device_farm_id(client)
    cameras = fetch_cameras(client, farm_id)

    if not cameras:
        raise RuntimeError(
            "Для этой фермы не настроено ни одной камеры. "
            "Добавьте камеру в админке — устройство подхватит её автоматически."
        )

    print(f"версия обработки: {AGENT_VERSION}")
    print(f"режим: {describe_profile(detector_profile())}")
    # Список классов печатается всегда: молчаливое «никого не вижу»
    # разбирать в разы дороже, чем прочитать одну строку при запуске
    print(f"ищем в кадре: {', '.join(sorted(get_tracked_class_names()))}")
    print(f"ферма {farm_id}, камер: {len(cameras)}")
    print(f"частота трекинга: {track_fps():.0f} кадр/с")

    spool = EventSpool()
    pending = spool.count()
    if pending:
        print(f"в буфере накоплено событий: {pending}")

    # Модель одна на все камеры: она только считает векторы и состояния не хранит
    embedder = None
    if embeddings_enabled():
        problem = check_available()
        if problem:
            # Выключаем, а не терпим: иначе каждый кадр пишет в журнал
            # одну и ту же ошибку, и настоящие сообщения в нём тонут
            print(f"ВНИМАНИЕ: {problem}")
        else:
            embedder = Embedder()
            print(f"распознавание особей включено, модель: {embedder.name}")
    else:
        print("распознавание особей выключено (REID_ENABLED)")

    # Живой просмотр: одна проверка на всю ферму, общая для всех камер
    live_view = LiveWindow(client, farm_id)
    print(f"живой просмотр: {live_view.check_available()}")
    live_view.start()
    frames = FrameBuffer()
    start_stream_server(frames)
    _register_streams(client, cameras)

    guard = _make_guard(client, farm_id, cameras)

    # Поведение: не ест, не двигается, пропала. Считается здесь, а не в
    # браузере — открытая вкладка не должна быть условием того, что
    # болезнь заметили
    health = HealthWatcher(lambda: _check_health(client, farm_id))
    health.start()

    if embedder is not None and autoenroll_enabled():
        print(f"запоминание новых особей: {describe_rules(AutoEnrollRules.from_env())}")
    elif embedder is None:
        print("новые особи не запоминаются: распознавание особей выключено")

    # Отдача наружу: поднимается сама, когда кто-то открыл просмотр,
    # и молчит всё остальное время
    publisher = RemotePublisher(client, farm_id, cameras)
    print(f"видео через интернет: {publisher.check_available()}")
    if relay_enabled():
        publisher.start()

    if len(cameras) == 1:
        # Один поток — проще отлаживать и видно окно предпросмотра
        _run_camera_safely(
            client, farm_id, cameras[0], frame_interval_s, embedder, spool,
            live_view=live_view, frames=frames, guard=guard,
        )
        return

    # Каждой камере — свой Detector: трекер хранит состояние внутри модели,
    # общий экземпляр перемешал бы номера объектов между камерами.
    threads = [
        threading.Thread(
            target=_run_camera_safely,
            args=(client, farm_id, camera, frame_interval_s, embedder, spool),
            kwargs={"live_view": live_view, "frames": frames, "guard": guard},
            name=f"camera-{camera['name']}",
            daemon=True,
        )
        for camera in cameras
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def _check_health(client, farm_id: str) -> None:
    """
    Один круг проверки поведения.

    Итог печатается всегда, включая «ничего не нашли». Молчащий журнал
    неотличим от сломанной проверки, а узнать об этом хочется раньше,
    чем через больную корову.
    """
    day_rows, animals, cameras = fetch_health_input(client, farm_id)

    # Судить не по чему — не трогаем тревоги вовсе.
    #
    # Пустой список находок закрывает всё открытое, и это правильно,
    # когда мы посмотрели и увидели, что всё хорошо. Но с полуночи до
    # часа дня годных суток нет ни одних, находок ноль по этой причине,
    # а проверка идёт раз в час: за ночь все открытые тревоги закрывались
    # тринадцать раз подряд. Поднятая вечером «не видели двое суток» к
    # утру исчезала
    if not can_judge(cameras):
        print("поведение: годных суток нет, тревоги оставлены как были")
        return

    found = run_check(day_rows, animals, cameras)

    # Здесь пустой список — уже осмысленный ответ: посмотрели и не нашли,
    # значит открытое пора закрыть
    opened, resolved = apply_health_findings(client, farm_id, found)

    if found:
        print(
            f"поведение: {len(found)} отклонений "
            f"({', '.join(sorted({one.kind for one in found}))}), "
            f"новых тревог {opened}, закрыто {resolved}"
        )
    else:
        print(f"поведение: отклонений нет, закрыто {resolved}")


def _make_guard(client, farm_id: str, cameras: list[dict]) -> SecurityWatcher | None:
    """
    Наблюдатель за посторонними — один на ферму.

    Возвращает None, когда охрана выключена: тогда классы людей и техники
    вообще не отслеживаются, и разделять нечего.
    """
    if not security_enabled():
        return None

    if "person" in detector_profile().subject_classes:
        # Человек не может быть одновременно подопечным и посторонним.
        # Оставить охрану включённой значило бы поднимать тревогу на
        # каждого, кого система в этот момент считает
        print("охрана выключена: людей сейчас считают наравне с животными")
        return None

    guarded = [c for c in cameras if c.get("security_enabled")]
    if not guarded:
        print(
            "охрана включена, но ни на одной камере не отмечена — "
            "включите её в настройках камеры"
        )

    row = None
    timezone_name = None
    try:
        response = (
            client.table("alert_settings").select("*").eq("farm_id", farm_id).execute()
        )
        row = (response.data or [None])[0]
    except Exception as exc:
        print(f"настройки охраны не прочитаны ({exc}), беру значения по умолчанию")

    try:
        response = (
            client.table("farms").select("timezone").eq("id", farm_id).single().execute()
        )
        timezone_name = (response.data or {}).get("timezone")
    except Exception:
        pass

    settings = GuardSettings.from_row(row, timezone_name)
    print(
        f"охрана: {describe_window(settings)}, камер под охраной {len(guarded)}, "
        f"выдержка {settings.min_seconds:.0f} с"
    )
    return SecurityWatcher(settings)


def _perimeter_polygon(zone_tracker) -> list[tuple[float, float]] | None:
    """
    Обведённый периметр камеры, если он есть.

    Без периметра тревога поднимается на любого человека в кадре — включая
    прохожего на дороге за забором. С периметром — только на того, кто
    внутри.
    """
    for zone in zone_tracker.zones:
        if zone.kind == "perimeter":
            return zone.polygon
    return None


def _training_job(client, farm_id, camera_id, frame, reason, detections):
    """
    Задание на отправку кадра для дообучения.

    Отдельной функцией, а не замыканием прямо в цикле: замыкание держало
    бы ссылки на переменные цикла, и к моменту выполнения в очереди они
    указывали бы уже на следующий кадр. Такая ошибка не падает — просто
    в датасет ложится кадр с чужой разметкой, и обнаружить это можно
    только глазами.

    Ошибка здесь гасится: место в хранилище кончилось или связь пропала —
    это не повод останавливать обработку видео. Сбор кадров идёт две
    недели, а работа фермы — постоянно.
    """
    def job():
        try:
            training.upload_training_frame(
                client, farm_id, camera_id, frame, reason, detections
            )
        except Exception as exc:
            print(f"кадр для дообучения не отправлен: {exc}")

    return job


def _watch_for_intruders(
    client,
    farm_id: str,
    camera: dict,
    guard,
    intruders: list[Detection],
    zone_tracker,
    width: int,
    height: int,
    now: float,
    frame,
) -> None:
    """
    Решает, стал ли человек в кадре тревогой, и записывает её.

    Ошибки глушим намеренно: не записанная тревога — это плохо, но
    остановленная из-за неё обработка видео означает, что ферма перестала
    считаться вовсе. Второе хуже.
    """
    if not camera.get("security_enabled"):
        return

    persons = guard.count_in_zone(
        intruders, _perimeter_polygon(zone_tracker), width, height
    )
    decision = guard.observe(
        str(camera["id"]),
        persons,
        now,
        mode=camera.get("security_mode") or "schedule",
    )

    if decision.raise_alert:
        path = None
        try:
            path = upload_intruder_snapshot(client, farm_id, camera, frame, intruders)
        except Exception as exc:
            # Тревогу поднимаем даже без снимка: сам факт важнее картинки
            print(f"{camera['name']}: снимок к тревоге не сохранён — {exc}")

        row = alert_row(farm_id, str(camera["id"]), camera["name"], decision, path)
        try:
            # Пока тревога по этой камере открыта, вторая не создастся:
            # это обеспечивает частичный уникальный индекс в базе
            client.table("alerts").upsert(row, on_conflict="farm_id,kind,subject_id").execute()
            print(
                f"{camera['name']}: ТРЕВОГА — посторонний, "
                f"людей в кадре {decision.persons}"
            )
        except Exception as exc:
            print(f"{camera['name']}: тревога не записана — {exc}")

    elif decision.resolve_alert:
        try:
            (
                client.table("alerts")
                .update({"resolved_at": "now()"})
                .eq("camera_id", camera["id"])
                .eq("kind", "intruder")
                .is_("resolved_at", "null")
                .execute()
            )
            print(f"{camera['name']}: посторонних больше нет, тревога закрыта")
        except Exception as exc:
            print(f"{camera['name']}: тревога не закрыта — {exc}")


def upload_intruder_snapshot(client, farm_id: str, camera: dict, frame, intruders):
    """
    Снимок к тревоге, с обведёнными людьми.

    Путь с меткой времени, а не постоянный: снимок к каждой тревоге свой,
    и затирать предыдущий нельзя — по нему потом разбираются.
    """
    from cv_service.preview import draw_detections
    from cv_service.snapshot import CACHE_SECONDS, SNAPSHOT_BUCKET, encode_snapshot

    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = f"{farm_id}/intruder/{camera['id']}-{stamp}.jpg"
    payload = encode_snapshot(draw_detections(frame, intruders, {}))

    client.storage.from_(SNAPSHOT_BUCKET).upload(
        path,
        payload,
        {"content-type": "image/jpeg", "cache-control": CACHE_SECONDS, "upsert": "true"},
    )
    return path


def _register_streams(client, cameras: list[dict]) -> None:
    """
    Прописывает адрес потока каждой камере и говорит об этом вслух.

    Раньше это делалось руками в админке, и поэтому не делалось никогда:
    надо было выяснить адрес мини-ПК в сети, собрать ссылку с паролем и
    вставить её в карточку. Живой просмотр из-за одного пропущенного шага
    оставался на кадре в секунду при полностью готовом видеотракте.
    """
    if not stream_enabled():
        print("поток по локальной сети выключен: живой просмотр пойдёт кадрами")
        return

    if not stream_token():
        # Сообщение уже напечатал start_stream_server — не повторяемся
        return

    registered = 0
    for camera in cameras:
        url = local_stream_url(camera["id"])
        if url is None:
            continue
        if register_camera_stream(client, camera["id"], url):
            registered += 1

    if registered:
        print(f"адрес потока прописан камерам: {registered} из {len(cameras)}")
        print(f"поток отдаётся с {stream_host()}:{stream_port()}, {stream_fps():.0f} кадр/с")
    else:
        print("ни одной камере не удалось прописать адрес потока")


# Пауза перед перезапуском камеры и её потолок. Растёт, чтобы не молотить
# в отвалившуюся камеру каждую секунду, но и не ждать полчаса после
# случайного сбоя.
RESTART_DELAY_S = 5.0
MAX_RESTART_DELAY_S = 120.0


def _run_camera_safely(
    client,
    farm_id: str,
    camera: dict,
    frame_interval_s: float,
    embedder=None,
    spool: EventSpool | None = None,
    max_restarts: int | None = None,
    live_view: LiveWindow | None = None,
    frames: FrameBuffer | None = None,
    guard: SecurityWatcher | None = None,
) -> None:
    """
    Держит камеру в работе.

    Раньше исключение просто печаталось, и поток тихо завершался: камера
    оставалась мёртвой до ручного перезапуска, а узнавали об этом через
    сутки. Теперь поток поднимается сам, с растущей паузой.

    max_restarts ограничивает цикл в тестах.
    """
    delay = RESTART_DELAY_S
    attempts = 0

    while True:
        try:
            process_camera(
                client,
                Detector(),
                farm_id,
                camera,
                frame_interval_s,
                embedder=embedder,
                spool=spool,
                live_view=live_view,
                frames=frames,
                guard=guard,
            )
            # Штатное завершение — например, кончился файл
            return
        except Exception as exc:
            print(f"камера {camera['name']} остановлена: {exc}")

        attempts += 1
        if max_restarts is not None and attempts >= max_restarts:
            return

        print(f"камера {camera['name']}: перезапуск через {delay:.0f} с")
        time.sleep(delay)
        delay = min(delay * 2, MAX_RESTART_DELAY_S)


def debug_camera(cameras: list[dict], source_uri: str, camera_id: str | None) -> dict:
    """
    Карточка камеры для ручного режима отладки (`VIDEO_SOURCE`).

    Раньше здесь требовался ещё и `CAMERA_ID`, причём обязательно: без
    него запуск падал с `KeyError: 'CAMERA_ID'` уже после того, как всё
    поднялось и отрапортовало «живой просмотр: готов». Выглядело как
    поломка живого просмотра, хотя дело было в незаполненной переменной.

    Теперь `CAMERA_ID` необязателен: берётся ПЕРВАЯ камера фермы. Событиям
    нужен существующий идентификатор — иначе база отклонит их по внешнему
    ключу, — а какой именно, для отладки на столе безразлично.

    Берётся вся карточка камеры, а не только идентификатор: в ней
    `placement`, от которого зависит, снимается ли силуэт для веса. С
    заглушкой «отладка» без расположения вес не считался бы, и причину
    пришлось бы искать в коде обмеров.
    """
    if camera_id:
        for camera in cameras:
            if camera.get("id") == camera_id:
                return {**camera, "source_uri": source_uri}
        print(
            f"CAMERA_ID={camera_id} нет среди камер фермы — "
            "события по нему база не примет"
        )
        return {"id": camera_id, "name": "отладка", "source_uri": source_uri}

    if not cameras:
        raise RuntimeError(
            "VIDEO_SOURCE задан, но у фермы нет ни одной камеры. "
            "Заведите камеру в админке или укажите CAMERA_ID вручную"
        )

    first = cameras[0]
    print(f"отладка на камере «{first.get('name', '?')}» (первая у фермы)")
    return {**first, "source_uri": source_uri}


if __name__ == "__main__":
    override = os.environ.get("VIDEO_SOURCE")
    if override:
        # Ручной режим для отладки: игнорирует АДРЕС камеры с сервера, но
        # саму карточку берёт оттуда же. Живой просмотр здесь тоже нужен —
        # иначе проверка на ноутбуке показывала бы, что он не работает,
        # хотя дело в режиме запуска.
        client = get_client()
        farm_id = get_device_farm_id(client)
        camera = debug_camera(
            fetch_cameras(client, farm_id),
            override,
            os.environ.get("CAMERA_ID", "").strip() or None,
        )
        live_view = LiveWindow(client, farm_id)
        print(f"живой просмотр: {live_view.check_available()}")
        live_view.start()
        frames = FrameBuffer()
        start_stream_server(frames)
        process_camera(
            client,
            Detector(),
            farm_id,
            camera,
            live_view=live_view,
            frames=frames,
        )
    else:
        run()
