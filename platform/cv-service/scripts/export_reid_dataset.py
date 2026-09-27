"""
Выгружает названные кадры животных в набор для дообучения распознавания.

На выходе — папки по кличкам:

    dataset/
      Зорька/2026-08-01_a1b2.jpg
      Ночка/...

Такую раскладку понимают все библиотеки метрического обучения.

Запуск (из папки cv-service, с заполненным .env):

    python scripts/export_reid_dataset.py --out ~/dataset --min-per-animal 20

Скрипт печатает, сколько кадров у каждого животного и в скольких разных днях
они сняты. Второе важнее первого: двадцать кадров одного визита — это
фактически один кадр, модель заучит грязь на боку, а не животное.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cv_service.crops import CROP_BUCKET  # noqa: E402
from cv_service.supabase_client import get_client, get_device_farm_id  # noqa: E402

PAGE_SIZE = 500


def safe_name(label: str) -> str:
    """Кличка попадает в имя папки, поэтому чистим её от разделителей путей."""
    cleaned = re.sub(r"[^\w\s-]", "", label, flags=re.UNICODE).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "bez_klichki"


def fetch_named_sightings(client, farm_id: str) -> list[dict]:
    """Все кадры с проставленным животным. Постранично: их могут быть тысячи."""
    rows: list[dict] = []
    offset = 0

    while True:
        response = (
            client.table("sightings")
            .select("id, animal_id, crop_path, occurred_at, confidence")
            .eq("farm_id", farm_id)
            .not_.is_("animal_id", "null")
            .order("occurred_at")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def fetch_labels(client, farm_id: str) -> dict[str, str]:
    response = client.table("animals").select("id, label").eq("farm_id", farm_id).execute()
    return {row["id"]: row["label"] for row in (response.data or [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="папка для набора")
    parser.add_argument(
        "--min-per-animal",
        type=int,
        default=20,
        help="животных с меньшим числом кадров пропускать",
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=3,
        help="минимум разных дней съёмки на животное",
    )
    args = parser.parse_args()

    client = get_client()
    farm_id = get_device_farm_id(client)

    labels = fetch_labels(client, farm_id)
    sightings = fetch_named_sightings(client, farm_id)
    if not sightings:
        print("Названных кадров нет. Назовите животных в интерфейсе и повторите.")
        return 1

    by_animal: dict[str, list[dict]] = defaultdict(list)
    for row in sightings:
        by_animal[row["animal_id"]].append(row)

    out_root = Path(args.out).expanduser()
    out_root.mkdir(parents=True, exist_ok=True)

    storage = client.storage.from_(CROP_BUCKET)
    exported = 0
    skipped: list[str] = []

    for animal_id, rows in sorted(by_animal.items()):
        label = labels.get(animal_id, animal_id[:8])
        days = {row["occurred_at"][:10] for row in rows}

        if len(rows) < args.min_per_animal or len(days) < args.min_days:
            skipped.append(
                f"{label}: {len(rows)} кадров за {len(days)} дн. — мало"
            )
            continue

        folder = out_root / safe_name(label)
        folder.mkdir(exist_ok=True)

        for row in rows:
            target = folder / f"{row['occurred_at'][:10]}_{row['id'][:8]}.jpg"
            if target.exists():
                continue
            try:
                target.write_bytes(storage.download(row["crop_path"]))
                exported += 1
            except Exception as exc:
                print(f"  не скачался {row['crop_path']}: {exc}")

        print(f"{label}: {len(rows)} кадров, {len(days)} разных дней")

    print(f"\nВыгружено файлов: {exported}")
    print(f"Животных в наборе: {len(by_animal) - len(skipped)}")

    if skipped:
        print("\nПропущены (данных пока мало):")
        for line in skipped:
            print(f"  {line}")

    ready = len(by_animal) - len(skipped)
    if ready < 30:
        print(
            f"\nДля дообучения нужно не меньше 30 животных, набралось {ready}. "
            "Набор годится, чтобы посмотреть на данные, но не чтобы учить модель."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
