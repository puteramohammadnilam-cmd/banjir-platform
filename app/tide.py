"""Predicted high and low tides at an area's tide gauge, for the Area overview's tide card. Only an area with a built
tide.json beside its area.json has one (tools/build_tide.py: a harmonic fit to a public tide-gauge record).

tide.json: {station, source, fit, typical_error_m, big_range_m, turns: [[Malaysian time "YYYY-MM-DDTHH:MM", "high" |
"low", metres from the mean level], ...]} in time order. A day whose range (highest high minus lowest low) is at least
big_range_m is a big (spring) tide. Read once, checked at start-up.

An area split into districts along several coasts (a state) has, instead, tide/<gauge>.json files in that form and
tide/sections.json {"sections": {section id: {"gauge": file stem, "km": distance from the district's main town}}}: a
district listed there gets its gauge's tide, said with how far it is; one not listed (inland) and the whole area none.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import areas

TIDE_FILE = "tide.json"
SECTIONS_FILE = "tide/sections.json"
MYT = timezone(timedelta(hours=8))
MAX_HEIGHT_M = 10
ROUND_MIN = 5                 # times are shown to 5 minutes: 92% of predicted highs fall within 30 minutes
WARN_DAYS = 60                # warn this long before the table runs out: rebuild it with tools/build_tide.py
OUTLOOK_DAYS = 14             # big tides ahead are looked for this far

log = logging.getLogger(__name__)


def _is_time(text) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return False
    return True


def _is_turn(turn) -> bool:
    return (isinstance(turn, (list, tuple)) and len(turn) == 3 and _is_time(turn[0]) and turn[1] in ("high", "low")
            and isinstance(turn[2], (int, float)) and math.isfinite(turn[2]) and abs(turn[2]) <= MAX_HEIGHT_M)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def shown(clock: str) -> str:
    """"HH:MM" rounded to the nearest ROUND_MIN minutes, as the card shows it; never past 23:55, so a turn stays on its
    own day."""
    hours, minutes = map(int, clock.split(":"))
    total = min(ROUND_MIN * round((hours * 60 + minutes) / ROUND_MIN), 24 * 60 - ROUND_MIN)
    return f"{total // 60:02d}:{total % 60:02d}"


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def gauges(area_id: str) -> Mapping | None:
    """{section id: {gauge, km}} from the area's tide/sections.json, or None for an area without one."""
    if not (areas.AREAS_DIR / area_id / SECTIONS_FILE).is_file():
        return None
    try:
        found = areas._read(area_id, SECTIONS_FILE)["sections"]
        ok = isinstance(found, dict) and all(isinstance(v, dict) and areas._is_id(str(v.get("gauge"))) and _is_number(v.get("km"))
                                             for v in found.values())
    except (ValueError, KeyError, TypeError):
        ok = False
    if not ok:
        raise areas.AreaError(f"{area_id}: {SECTIONS_FILE} must map section ids to a gauge file and its distance in km.")
    return areas._freeze(found)


def _file(area_id: str, section_id: str | None) -> str | None:
    """The tide file for the area or one of its sections, or None where there is none (see the module docstring)."""
    listed = gauges(area_id)
    if listed is None:
        return TIDE_FILE
    own = listed.get(section_id) if section_id else None
    return f"tide/{own['gauge']}.json" if own else None


def doc(area_id: str, section_id: str | None = None) -> Mapping | None:
    """The tide table of the area, or of one of its sections, checked; None where there is none. Raises
    areas.AreaError, naming the area and file, for one that does not fit. Kept once per file, however many sections
    share it."""
    name = _file(area_id, section_id)
    return _table(area_id, name) if name else None


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def _table(area_id: str, name: str) -> Mapping | None:
    if not (areas.AREAS_DIR / area_id / name).is_file():
        return None
    try:
        found = areas._read(area_id, name)
    except ValueError as error:   # bad JSON or bad UTF-8
        raise areas.AreaError(f"{area_id}: {name} is not valid JSON ({error}).") from error
    turns = found.get("turns") if isinstance(found, Mapping) else None
    ok = (isinstance(turns, list) and turns and all(_is_turn(t) for t in turns)
          and [t[0] for t in turns] == sorted(t[0] for t in turns)
          and all(a[1] != b[1] for a, b in zip(turns, turns[1:]))
          and isinstance(found.get("station"), str) and found["station"].strip() and isinstance(found.get("source"), str)
          and _is_number(found.get("big_range_m")) and _is_number(found.get("typical_error_m")))
    if not ok:
        raise areas.AreaError(f"{area_id}: {name} must give a station, source, big_range_m, typical_error_m and "
                              "highs and lows taking turns in time order.")
    return areas._freeze(found)


def day_ranges(area_id: str, section_id: str | None = None) -> dict[str, float]:
    """{Malaysian date: highest turn minus lowest} over the table."""
    return _ranges(area_id, _file(area_id, section_id))


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def _ranges(area_id: str, name: str) -> dict[str, float]:
    days: dict[str, list[float]] = {}
    for when, _, height in _table(area_id, name)["turns"]:
        days.setdefault(when[:10], []).append(height)
    return {day: max(h) - min(h) for day, h in days.items()}


def next_big(area_id: str, start: datetime, section_id: str | None = None) -> dict | None:
    """{from, to}: the first run of big-tide days from `start`'s date (today counts) within OUTLOOK_DAYS; None if none."""
    ranges, threshold, run = day_ranges(area_id, section_id), doc(area_id, section_id)["big_range_m"], None
    for k in range(OUTLOOK_DAYS + 1):
        day = (start + timedelta(days=k)).strftime("%Y-%m-%d")
        if ranges.get(day, 0) >= threshold:
            run = {"from": run["from"] if run else day, "to": day}
        elif run:
            break
    return run


def check(area_id: str, now: datetime | None = None) -> None:
    """At start-up: each table is there and well formed, and a warning when one runs out within WARN_DAYS."""
    listed = gauges(area_id)
    unknown = sorted(set(listed or ()) - (areas.section_ids(area_id) or frozenset()))
    if unknown:
        raise areas.AreaError(f"{area_id}: {SECTIONS_FILE} names sections the area does not have: {', '.join(unknown)}.")
    for section_id in listed or [None]:
        found = doc(area_id, section_id)
        if found is None:
            if section_id is None:
                return
            raise areas.AreaError(f"{area_id}: {SECTIONS_FILE} names a gauge with no tide file for {section_id}.")
        last = datetime.strptime(found["turns"][-1][0], "%Y-%m-%dT%H:%M").replace(tzinfo=MYT)
        if last - (now or datetime.now(timezone.utc)) < timedelta(days=WARN_DAYS):
            log.warning("%s: %s ends on %s: rebuild it with tools/build_tide.py", area_id, _file(area_id, section_id), last.date())


def today(area_id: str, now: datetime | None = None, section_id: str | None = None) -> dict | None:
    """What GET /api/tide sends: today's highs and lows (Malaysian time), the day's range and whether it is a big tide,
    the next high tide from now, the next run of big-tide days within two weeks, and for a state's district the
    gauge's distance from its main town (`km`) and the district it was picked for (`section`: null for a city's one
    gauge); None without a table or outside the dates it covers."""
    found = doc(area_id, section_id)
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
            "highs": [shown(t[0][11:]) for t in day if t[1] == "high"], "lows": [shown(t[0][11:]) for t in day if t[1] == "low"],
            "range_m": round(max(heights) - min(heights), 1), "big": max(heights) - min(heights) >= found["big_range_m"],
            "next_high": {"time": shown(coming[0][11:]), "tomorrow": not coming[0].startswith(date)} if coming else None,
            "next_big": next_big(area_id, now, section_id),
            "typical_error_m": found["typical_error_m"], "source": found["source"], "fit": found.get("fit"),
            "km": (gauges(area_id) or {}).get(section_id, {}).get("km"),
            "section": section_id if section_id in (gauges(area_id) or {}) else None}
