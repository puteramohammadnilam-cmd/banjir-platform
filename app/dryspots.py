"""Where to move the car: the nearest street point the flood model keeps dry, from an area's dry_spots.json
(tools/build_dry_spots.py).

nearest(area_id, lat, lon) gives, for each flood size, the closest spot that stays dry in it within REACH_M, and the
file's credit: {"10": spot, "20": spot, "50": spot, "credit": text}. A spot is {lat, lon, road, distance_m, bearing}
(bearing in whole degrees from north, for the page to say "north-east"), or None when there is none that close. An area
without the file gives None.
Distances are straight lines, not the way by road. The file is read once and kept.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("banjir")

AREAS_DIR = Path(__file__).parent / "data" / "areas"
FILE = "dry_spots.json"
REACH_M = 3000
SIZES = ("10", "20", "50")          # a spot's `dry` count: dry in this many of these, smallest first
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON_EQUATOR = 111320.0
MAX_CACHED_AREAS = 32


@lru_cache(maxsize=MAX_CACHED_AREAS)
def _load(area_id: str) -> dict | None:
    path = AREAS_DIR / area_id / FILE
    if not path.is_file():
        return None
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
        return {"credit": found["credit"], "names": tuple(found["names"]), "spots": tuple(tuple(spot) for spot in found["spots"])}
    except (ValueError, KeyError, TypeError) as error:   # a damaged file costs the feature, not the page
        log.warning("%s could not be read: %s", path, error)
        return None


def _spot(dist: float, dx: float, dy: float, spot: tuple, names: tuple) -> dict:
    """A found spot for the page: where it is, its street (None when unnamed), how far and which way."""
    return {"lat": spot[0], "lon": spot[1], "road": names[spot[3]] if spot[3] >= 0 else None, "distance_m": round(dist),
            "bearing": round(math.degrees(math.atan2(dx, dy))) % 360}


def nearest(area_id: str | None, lat: float, lon: float) -> dict | None:
    """For each flood size, the closest spot dry in it, or None; None for an area without spots."""
    found = _load(area_id) if area_id else None
    if found is None:
        return None
    per_lon = M_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat))
    reach_lat, reach_lon = REACH_M / M_PER_DEG_LAT, REACH_M / per_lon
    best: list[tuple | None] = [None] * len(SIZES)   # per size: (metres, dx, dy, spot)
    for spot in found["spots"]:
        if abs(spot[0] - lat) > reach_lat or abs(spot[1] - lon) > reach_lon:   # cheap box test first
            continue
        dx, dy = (spot[1] - lon) * per_lon, (spot[0] - lat) * M_PER_DEG_LAT
        dist = math.hypot(dx, dy)
        if dist > REACH_M:
            continue
        for size in range(spot[2]):   # dry in the first `dry` sizes
            if best[size] is None or dist < best[size][0]:
                best[size] = (dist, dx, dy, spot)
    spots = {key: pick and _spot(*pick, found["names"]) for key, pick in zip(SIZES, best)}
    return {**spots, "credit": found["credit"]}
