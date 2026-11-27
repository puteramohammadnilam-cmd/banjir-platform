"""The river model's flood depths as pictures, for an area too big to send its 90 m squares (a state split into
districts, whose town.json holds none). tools/outline_squares.py writes them into app/data/areas/<id>/flood/:
  flood_pictures.json            each outline's id, bounds [west, south, east, north] and files, and the credit
  {section}_rp{rp}_{theme}.png   one indexed PNG per section, flood size (10, 20, 50) and theme (light, dark) in the
                                 map's depth colours, transparent where the model has no water

layer(area_id) gives the page {"url", "pictures": [{"section", "bounds"}], "credit"}, `url` holding "{section}",
"{rp}" and "{theme}" to fill in, or None where the area has none; png_path(area_id, section, rp, theme) the picture,
or None. Read on first use and kept; a JSON that cannot be read is logged with its name and gives None, so a damaged
file costs the pictures, not the page.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from . import areas

log = logging.getLogger("banjir")

FOLDER = "flood"
FILE_NAME = "flood_pictures.json"
URL = "/api/areas/{id}/flood/{{section}}/{{rp}}/{{theme}}.png"
RPS = ("10", "20", "50")
THEMES = ("light", "dark")


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def _read(area_id: str) -> dict | None:
    """{section id: bounds} and the credit of an area's pictures, or None without a readable flood_pictures.json."""
    area = areas.get(area_id)
    path = areas.AREAS_DIR / area.id / FOLDER / FILE_NAME if area else None
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        bounds = {item["id"]: [float(edge) for edge in item["bounds"]] for item in doc["outlines"] if item.get("bounds")}
        return {"bounds": bounds, "credit": str(doc["credit"]), "folder": path.parent}
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.error("%s/%s/%s cannot be read: %s", area.id, FOLDER, FILE_NAME, error)
        return None


def layer(area_id: str) -> dict | None:
    found = _read(area_id)
    if not found:
        return None
    return {"url": URL.format(id=area_id), "credit": found["credit"],
            "pictures": [{"section": section, "bounds": bounds} for section, bounds in found["bounds"].items()]}


def png_path(area_id: str, section_id: str, rp: str, theme: str) -> Path | None:
    found = _read(area_id)
    if not found or section_id not in found["bounds"] or rp not in RPS or theme not in THEMES:
        return None
    path = found["folder"] / f"{section_id}_rp{rp}_{theme}.png"
    return path if path.is_file() else None


def clear_cache() -> None:
    _read.cache_clear()
