"""Helpers for ship icon caching under static/icons."""

from __future__ import annotations

import os

from kmstat import app
from kmstat.api import api


def ensure_ship_icons_cached(item_type_ids: list[int], timeout: int = 10) -> set[int]:
    """Ensure ship icons exist under static/icons and return available item IDs."""
    if not item_type_ids:
        return set()

    icons_dir = os.path.join(app.root_path, "static", "icons")
    os.makedirs(icons_dir, exist_ok=True)

    available_ids: set[int] = set()
    for item_id in set(item_type_ids):
        if not item_id:
            continue

        icon_path = os.path.join(icons_dir, f"{item_id}.png")
        if os.path.exists(icon_path):
            available_ids.add(item_id)
            continue

        icon_url = f"https://newedenencyclopedia.net/rsc/type_icons/{item_id}.png"
        try:
            response = api.session.get(icon_url, timeout=timeout)
            if response.status_code == 200 and response.content:
                with open(icon_path, "wb") as f:
                    f.write(response.content)
                available_ids.add(item_id)
        except Exception:
            continue

    return available_ids
