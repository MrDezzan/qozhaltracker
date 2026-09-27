"""
Сколько камер тянет ЭТО железо. Замер, а не оценка.

Запуск на устройстве фермы, из папки cv-service:

    ./.venv/bin/python scripts/benchmark.py

Зачем. Число «четыре камеры на мини-ПК» появилось из прикидки и с тех пор
кочует по всем сметам, определяя цену для клиента. На реальном железе его
никто не проверял. Ошибка здесь стоит миллионы: на ферме в 38 камер
разница между «4 на ПК» и «12 на ПК» — это десять мини-ПК против трёх.

Что меряется. Ровно то, что делает боевой код: `model.track()` на кадре
1080p, с тем же persist=True. Не «чистый инференс» из статей — трекер и
NMS входят в стоимость.

Чего замер НЕ покажет:
  * работу в несколько потоков — на настоящей ферме камеры делят ядра, и
    суммарная пропускная способность будет НИЖЕ, чем число из этого
    скрипта, умноженное на камеры;
  * узнавание особей (MegaDescriptor) — оно идёт отдельным потоком и на
    процессоре стоит секунду-две на вектор;
  * нагрев. Мини-ПК без вентилятора через полчаса сбрасывает частоту.
    Для честного числа гоняйте с `--minutes 30`.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def human(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("YOLO_MODEL", "yolov8n-seg.pt"))
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--minutes", type=float, default=0.0,
                        help="гонять столько минут вместо --frames: покажет просадку от нагрева")
    parser.add_argument("--source", default="",
                        help="видеофайл или RTSP: честнее синтетики, там настоящие животные")
    args = parser.parse_args()

    try:
        import numpy as np
        from ultralytics import YOLO
    except ImportError as exc:
        print(f"Нет зависимостей: {exc}")
        print("Запускать из окружения проекта: ./.venv/bin/python scripts/benchmark.py")
        return 2

    import cv2

    print(f"модель:      {args.model}")
    print(f"кадр:        {args.width}x{args.height}, вход сети {args.imgsz}")

    try:
        import torch
        threads = torch.get_num_threads()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        name = torch.cuda.get_device_name(0) if device == "cuda" else "процессор"
        print(f"считает:     {name} ({device}), потоков torch {threads}")
    except Exception:
        print("считает:     процессор")

    model = YOLO(args.model)

    # Кадры. Синтетика годится для сравнения железа, но НЕ для абсолютного
    # числа: на пустом кадре нет объектов, а трекер и NMS дорожают с их
    # числом. На настоящей ферме будет медленнее
    cap = None
    if args.source:
        cap = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
        if not cap.isOpened():
            print(f"не открылся источник: {args.source}")
            return 2
        print(f"источник:    {args.source}")
    else:
        print("источник:    синтетический шум — НА ЖИВОМ ВИДЕО БУДЕТ МЕДЛЕННЕЕ")

    rng = np.random.default_rng(1)
    fallback = rng.integers(0, 255, (args.height, args.width, 3), dtype=np.uint8)

    def next_frame():
        if cap is None:
            return fallback
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        return frame if ok else fallback

    print(f"\nразогрев ({args.warmup} кадров)…")
    for _ in range(args.warmup):
        model.track(next_frame(), persist=True, verbose=False, imgsz=args.imgsz)

    times: list[float] = []
    deadline = time.monotonic() + args.minutes * 60 if args.minutes > 0 else None
    target = args.frames if deadline is None else 10**9

    print("замер…")
    start = time.monotonic()
    while len(times) < target:
        if deadline is not None and time.monotonic() > deadline:
            break
        frame = next_frame()
        t0 = time.perf_counter()
        model.track(frame, persist=True, verbose=False, imgsz=args.imgsz)
        times.append(time.perf_counter() - t0)

    if cap is not None:
        cap.release()

    ms = [t * 1000 for t in times]
    ms_sorted = sorted(ms)
    median = statistics.median(ms)
    p95 = ms_sorted[int(len(ms_sorted) * 0.95) - 1]
    fps = 1000.0 / median

    print(f"\nкадров:      {len(ms)} за {time.monotonic()-start:.0f} с")
    print(f"на кадр:     медиана {median:.0f} мс, худшие 5% {p95:.0f} мс")
    print(f"пропускная:  {fps:.1f} кадр/с в один поток")

    # Просадка от нагрева видна только на длинном прогоне
    if len(ms) >= 40:
        first = statistics.median(ms[: len(ms) // 4])
        last = statistics.median(ms[-len(ms) // 4:])
        drift = (last / first - 1) * 100
        if abs(drift) >= 10:
            print(f"ВНИМАНИЕ:    к концу прогона на {drift:+.0f}% "
                  f"({first:.0f} -> {last:.0f} мс) — похоже на перегрев")

    print("\n--- Сколько камер помещается ---")
    print("Запас 30%: на ферме тот же процессор занят ещё и отправкой,")
    print("узнаванием особей и трекингом зон.\n")
    usable = fps * 0.7
    print(f"{'частота трекинга':>18}{'камер':>8}")
    for track in (8, 4, 2, 1):
        print(f"{str(track) + ' кадр/с':>18}{int(usable // track):>8}")

    print("\nВ смете сейчас заложено 4 камеры на мини-ПК при 8 кадр/с,")
    print(f"то есть 32 кадр/с. Здесь получилось {usable:.0f} кадр/с с запасом.")
    if usable > 40:
        print("-> Смета ЗАВЫШЕНА: мини-ПК тянет больше, чем мы считали.")
    elif usable < 25:
        print("-> Смета ЗАНИЖЕНА: железа надо больше, чем в расчёте.")
    else:
        print("-> Смета близка к правде.")

    print("\nЧто попробовать дальше:")
    print(f"  --imgsz 480               меньше вход сети, быстрее и грубее")
    print(f"  --model yolov8n.pt        без сегментации: быстро, но БЕЗ ВЕСА")
    print(f"  --minutes 30              честное число с учётом нагрева")
    print(f"  --source запись_с_фермы.mp4   настоящие животные вместо шума")
    return 0


if __name__ == "__main__":
    sys.exit(main())
