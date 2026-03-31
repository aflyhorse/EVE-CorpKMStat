#!/usr/bin/env python3
"""Backfill ship icon cache for all victim ship types referenced by killmails."""

import os
import sys
from pathlib import Path

# Allow running this script directly via: python3 migrate/....py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kmstat import app  # noqa: E402
from kmstat.models import Killmail  # noqa: E402
from kmstat.icon_cache import ensure_ship_icons_cached  # noqa: E402


def _read_existing_icon_ids(icons_dir: str) -> set[int]:
    existing: set[int] = set()
    if not os.path.isdir(icons_dir):
        return existing

    for filename in os.listdir(icons_dir):
        if not filename.endswith(".png"):
            continue
        stem = filename[:-4]
        if stem.isdigit():
            existing.add(int(stem))
    return existing


def main() -> int:
    with app.app_context():
        icon_dir = os.path.join(app.root_path, "static", "icons")
        os.makedirs(icon_dir, exist_ok=True)

        all_type_ids = [
            row[0]
            for row in Killmail.query.with_entities(Killmail.victim_ship_type_id)
            .filter(Killmail.victim_ship_type_id.isnot(None))
            .distinct()
            .all()
            if row[0]
        ]

        existing_type_ids = _read_existing_icon_ids(icon_dir)
        missing_type_ids = [
            item_id for item_id in all_type_ids if item_id not in existing_type_ids
        ]

        print(f"Total victim ship types in DB: {len(all_type_ids)}")
        print(f"Already cached: {len(existing_type_ids.intersection(all_type_ids))}")
        print(f"Need warmup: {len(missing_type_ids)}")

        if not missing_type_ids:
            print("Done: all required icons are already cached.")
            return 0

        warmed_ids = ensure_ship_icons_cached(missing_type_ids)
        failed_ids = sorted(set(missing_type_ids) - warmed_ids)

        print(f"Warmup success: {len(warmed_ids)}")
        print(f"Warmup failed: {len(failed_ids)}")
        if failed_ids:
            sample = ", ".join(str(item_id) for item_id in failed_ids[:20])
            print(f"Failed item IDs (up to 20 shown): {sample}")
            return 1

        print("Done: icon warmup completed successfully.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
