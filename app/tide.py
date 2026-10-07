"""Predicted high and low tides at an area's tide gauge, for the Area overview's tide card. Only an area with a built
tide.json beside its area.json has one (tools/build_tide.py: a harmonic fit to a public tide-gauge record).

tide.json: {station, source, fit, typical_error_m, big_range_m, turns: [[Malaysian time "YYYY-MM-DDTHH:MM", "high" |
"low", metres from the mean level], ...]} in time order. A day whose range (highest high minus lowest low) is at least
big_range_m is a big (spring) tide. Read once, checked at start-up.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import areas

TIDE_FILE = "tide.json"
MYT = timezone(timedelta(hours=8))
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
MAX_HEIGHT_M = 10


def _is_turn(turn) -> bool:
    return (isinstance(turn, (list, tuple)) and len(turn) == 3 and isinstance(turn[0], str) and bool(_TIME.match(turn[0]))
            and turn[1] in ("high", "low") and isinstance(turn[2], (int, float)) and abs(turn[2]) <= MAX_HEIGHT_M)


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def doc(area_id: str) -> Mapping | None:
    """The area's tide.json, checked; None for an area without one. Raises areas.AreaError, naming the area, for one
    that does not fit."""
    if not (areas.AREAS_DIR / area_id / TIDE_FILE).is_file():
        return None
    try:
        found = areas._read(area_id, TIDE_FILE)
    except ValueError as error:   # bad JSON or bad UTF-8
        raise areas.AreaError(f"{area_id}: tide.json is not valid JSON ({error}).") from error
    turns = found.get("turns") if isinstance(found, Mapping) else None
    ok = (isinstance(turns, list) and turns and all(_is_turn(t) for t in turns)
          and [t[0] for t in turns] == sorted(t[0] for t in turns)
          and isinstance(found.get("station"), str) and found["station"].strip()
          and isinstance(found.get("big_range_m"), (int, float)) and isinstance(found.get("source"), str))
    if not ok:
        raise areas.AreaError(f"{area_id}: tide.json must give a station, source, big_range_m and turns in time order.")
    return areas._freeze(found)


def today(area_id: str, now: datetime | None = None) -> dict | None:
    """What GET /api/tide sends: today's highs and lows (Malaysian time), the day's range and whether it is a big tide,
    and the next high tide from now; None without a tide.json or outside the dates it covers."""
    found = doc(area_id)
    if found is None:
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(MYT)
    date, clock = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%M")
    day = [t for t in found["turns"] if t[0].startswith(date)]
    if not day:
        return None
    heights = [t[2] for t in day]
    coming = next((t for t in found["turns"] if t[1] == "high" and t[0] > clock), None)
    return {"station": found["station"], "date": date,
            "highs": [t[0][11:] for t in day if t[1] == "high"], "lows": [t[0][11:] for t in day if t[1] == "low"],
            "range_m": round(max(heights) - min(heights), 1), "big": max(heights) - min(heights) >= found["big_range_m"],
            "next_high": {"time": coming[0][11:], "tomorrow": not coming[0].startswith(date)} if coming else None,
            "typical_error_m": found.get("typical_error_m"), "source": found["source"]}
