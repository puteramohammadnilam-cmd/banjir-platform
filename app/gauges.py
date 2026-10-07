"""The nearest JPS river level gauge to a place, for the "River gauge" fact and the flood checklist: its name, river,
distance and the link to its live 7-day river level graph on JPS Public Infobanjir. The list (app/data/gauges.json,
tools/build_gauges.py) holds names and places only; the readings stay on JPS's site.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

GAUGES_FILE = Path(__file__).parent / "data" / "gauges.json"
GRAPH = "https://publicinfobanjir.water.gov.my/wl-graph/?stationid={id}"
MAX_KM = 10                   # a gauge further away says little about this place: none is given
SAME_SITE_M = 200             # an "(F2)" station this close to an older one is the same site: the older one is kept
M_PER_DEG = 111_320


@lru_cache(maxsize=1)
def listed() -> tuple[dict, ...]:
    """Every gauge, checked once: a missing or bad file is an error at start-up, not a silent gap."""
    doc = json.loads(GAUGES_FILE.read_text(encoding="utf-8"))
    found = doc.get("gauges") if isinstance(doc, dict) else None
    if not isinstance(found, list) or not found or not all(
            isinstance(g, dict) and isinstance(g.get("id"), str) and isinstance(g.get("name"), str) and g["name"]
            and isinstance(g.get("lat"), (int, float)) and isinstance(g.get("lon"), (int, float)) for g in found):
        raise ValueError(f"{GAUGES_FILE.name} must list gauges with an id, name, lat and lon")
    return tuple(found)


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dx = (lon2 - lon1) * M_PER_DEG * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, (lat2 - lat1) * M_PER_DEG)


def nearest(lat: float, lon: float) -> dict | None:
    """{id, name, river, distance_m, link} of the nearest gauge within MAX_KM, preferring an older station to an
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
    return {"id": best["id"], "name": best["name"], "river": best.get("river") or None, "distance_m": round(best_d),
            "link": GRAPH.format(id=best["id"])}
