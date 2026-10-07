"""The nearest JPS river level gauge to a place, for the "River gauge" fact and the flood checklist: its name, river,
distance; the page links to its live 7-day river level graph on JPS Public Infobanjir by its id. The list (app/data/gauges.json,
tools/build_gauges.py) holds names and places only; the readings stay on JPS's site.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

GAUGES_FILE = Path(__file__).parent / "data" / "gauges.json"
ID = re.compile(r"[A-Za-z0-9_ -]{1,20}")   # JPS ids such as 3015084_, 27233, KGLOMBONG and "SG MUAR"
MAX_TEXT = 80
MAX_KM = 10                   # a gauge further away says little about this place: none is given
SAME_SITE_M = 200             # an "(F2)" station this close to an older one is the same site: the older one is kept
M_PER_DEG = 111_320


@lru_cache(maxsize=1)
def listed() -> tuple[dict, ...]:
    """Every gauge, checked once: a missing or bad file is an error at start-up, not a silent gap."""
    doc = json.loads(GAUGES_FILE.read_text(encoding="utf-8"))
    found = doc.get("gauges") if isinstance(doc, dict) else None
    if not isinstance(found, list) or not found or not all(_is_gauge(g) for g in found):
        raise ValueError(f"{GAUGES_FILE.name} must list gauges with a plain id, a name, a river and a lat and lon")
    return tuple(found)


def _is_text(value, allow_empty: bool = False) -> bool:
    return (isinstance(value, str) and (allow_empty or value.strip() != "") and len(value) <= MAX_TEXT
            and value.isprintable() and not any(c in value for c in "<>"))   # shown as text only, never in a link


def _is_gauge(g) -> bool:
    return (isinstance(g, dict) and isinstance(g.get("id"), str) and bool(ID.fullmatch(g["id"]))
            and _is_text(g.get("name")) and _is_text(g.get("river", ""), allow_empty=True)
            and isinstance(g.get("lat"), (int, float)) and isinstance(g.get("lon"), (int, float)))


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * M_PER_DEG * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, (lat2 - lat1) * M_PER_DEG)


def nearest(lat: float, lon: float) -> dict | None:
    """{id, name, river, distance_m} of the nearest gauge within MAX_KM (the page links to JPS's graph by the id),
    preferring an older station to an
    "(F2)" one at the same site; None when none is that close."""
    pad = MAX_KM * 1000 / M_PER_DEG
    near = sorted(((_metres(lat, lon, g["lat"], g["lon"]), g) for g in listed()
                   if abs(g["lat"] - lat) <= pad and abs(g["lon"] - lon) <= pad / max(math.cos(math.radians(lat)), 0.1)),
                  key=lambda pair: (pair[0], pair[1]["id"]))
    near = [(d, g) for d, g in near if d <= MAX_KM * 1000]
    if not near:
        return None
    best_d, best = near[0]
    if "(F2)" in best["name"]:
        best_d, best = next(((d, g) for d, g in near if "(F2)" not in g["name"] and d - best_d <= SAME_SITE_M), (best_d, best))
    return {"id": best["id"], "name": best["name"], "river": best.get("river") or None, "distance_m": round(best_d)}
