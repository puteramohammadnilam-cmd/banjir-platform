"""The "Next 5 days" card on the Area overview (GET /api/outlook). For each of the next five days: the rain Google
Weather expects at the middle of the area or section, MetMalaysia's own forecast words for the town, whether a
MetMalaysia rain or thunderstorm warning covers the area, and whether it is a big (spring) tide day.

Each day gets a level from fixed rules, not a flood model (level()): high, watch or low, in the area SET_FROM_AREA
only; elsewhere the card gives the forecast with no level, since no floods there were checked. The thresholds come from
JPS daily rain at the gauges of the area SET_FROM_AREA, March 2024 to October 2026 (the average of the gauges with a
full day), against the dated floods in its history.json. 9 of the 10 floods fell on a day of 18 to 44 mm, and the day before was dry
(8 mm or less) every time, so earlier rain is not used. A day of WATCH_MM or more came 1 day in 12 and held 8 of the
10 floods; HIGH_MM or more, 1 day in 32 and 5 of 10. That treats the observed rain as a perfect forecast, so a real
forecast does worse, and they were not tested on Google's forecasts. It is not a flood warning, and the card says so.
Big tides are shown, not scored: no flood here was found to need one. A MetMalaysia continuous-rain warning covering a
day makes it high; a thunderstorm warning is shown on its day but does not set the level, since none was tested.

Each area's met.json gives its MetMalaysia forecast place and the state and districts a warning must name to cover
it, or, for an area split into districts (a state), each section's own under "sections": a section then gets its
place's words and the warnings naming its districts, and the whole area no words and the warnings naming any of them; an area without one gets Google's rain and the tides only. MetMalaysia's forecast and warnings come from data.gov.my (CC BY 4.0, at most 4 requests a minute). The server keeps
each answer for CACHE_S for every visitor, tries again RETRY_S after a failure, keeps the last good answer for
STALE_S, and logs one line per outage. A feed that fails leaves its part of the card out. Google's rain goes through
the free monthly cap in googlemaps.py. Standard library only.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone

from functools import lru_cache

from . import areas, googlemaps, tide

FORECAST = "https://api.data.gov.my/weather/forecast"
WARNINGS = "https://api.data.gov.my/weather/warning"
SOURCE = "https://www.met.gov.my/"
DAYS = 5
ASK_DAYS = 6                  # Google's day runs 07:00 to 07:00: before 7 am its first day is yesterday's
WATCH_MM = 20
HIGH_MM = 30
# What the thresholds rest on (above), for the card to say: of the days at WATCH_MM or more and HIGH_MM or more, how
# many had a recorded flood, out of the area's dated floods since the year given
CALIBRATION = {"since": 2024, "floods": 10, "watch_days": 79, "watch_floods": 8, "high_days": 28, "high_floods": 5}
SET_FROM_AREA = "shah-alam"   # the area whose rain and floods set WATCH_MM and HIGH_MM (above); the card names it
MET_FILE = "met.json"
CACHE_S = 3600
RETRY_S = 300
STALE_S = 86_400
TIMEOUT_S = 5
MAX_BYTES = 1_000_000
CHUNK = 65_536
MAX_TEXT = 80
MAX_WARNINGS = 3
MYT = timezone(timedelta(hours=8))
# by title_en: "Continuous Rain Warning" is rain, "Thunderstorms Warning" thunderstorm; sea, wind, cyclone and earthquake
# warnings are left out
WARNING_KINDS = (("rain", "rain"), ("thunderstorm", "thunderstorm"))
RANK = {"low": 0, "watch": 1, "high": 2}

log = logging.getLogger(__name__)
_locks: dict[str, threading.Lock] = {}   # one per feed, held only by the request fetching it; others use what is kept
_cache: dict[str, dict] = {}  # key -> {"tried", "ok", "good_at", "value"}


@lru_cache(maxsize=4 * areas.MAX_CACHED_AREAS)
def place(area_id: str, section_id: str | None = None) -> tuple[str | None, str | None, str, tuple[str, ...]] | None:
    """(location id, place name, state, districts) from the area's met.json, for one of its sections when the file
    gives sections ("sections": {id: {location_id, place, districts}}); for the whole of such an area, no location or
    place and every section's districts. None without a met.json, or for one that does not fit (logged)."""
    if areas.get(area_id) is None or not (areas.AREAS_DIR / area_id / MET_FILE).is_file():
        return None
    try:
        found = areas._read(area_id, MET_FILE)
        parts = found.get("sections") or {}
        if not isinstance(parts, dict):
            raise ValueError("sections must map section ids to places")
        own = parts.get(section_id) if section_id else None
        if own is not None:
            location, name, districts = own["location_id"], own["place"], tuple(own["districts"])
        elif parts:   # the whole of an area split into districts: no one place, a warning for any of them
            location, name, districts = None, None, tuple(d for each in parts.values() for d in each["districts"])
        else:
            location, name, districts = found["location_id"], found["place"], tuple(found["districts"])
        values = (found["state"], *districts, *((location, name) if location is not None else ()))
        if not districts or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError("location_id, place, state and districts must be text")
    except (ValueError, KeyError, TypeError) as exc:
        log.error("%s: %s does not fit: %s", area_id, MET_FILE, exc)
        return None
    return location, name, found["state"], districts


class FeedError(RuntimeError):
    """data.gov.my did not answer usefully. The message is for logs."""


def _text(value) -> str:
    return " ".join(value.split())[:MAX_TEXT] if isinstance(value, str) else ""


def _get_list(url: str, params: Mapping[str, str]) -> list:
    """A data.gov.my answer that is a JSON list, or FeedError."""
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "MyFlood/1.0 (flood information tool)"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:   # noqa: S310  fixed https host
            if urllib.parse.urlsplit(response.geturl()).hostname != urllib.parse.urlsplit(url).hostname:
                raise FeedError("data.gov.my redirected to another host")
            deadline, body = time.monotonic() + TIMEOUT_S, b""
            while chunk := response.read(CHUNK):
                body += chunk
                if len(body) > MAX_BYTES or time.monotonic() > deadline:
                    raise FeedError("data.gov.my answered too much, or too slowly")
            found = json.loads(body.decode("utf-8"))
    except FeedError:
        raise
    except urllib.error.HTTPError as exc:
        raise FeedError(f"HTTP {exc.code} from data.gov.my") from exc
    except Exception as exc:   # timeouts, resets, bad JSON or UTF-8: all one failure
        raise FeedError(f"{type(exc).__name__} from data.gov.my") from exc
    if not isinstance(found, list):
        raise FeedError("data.gov.my did not answer with a list")
    return found


def _fetch_forecast(location_id: str) -> list:
    return _get_list(FORECAST, {"filter": f"{location_id}@location__location_id", "limit": "10"})


def _fetch_warnings() -> list:
    return _get_list(WARNINGS, {"limit": "50"})


def _cached(key: str, fetch: Callable[[], object], clock: Callable[[], float]):
    """What `fetch` last gave, asked again at most every CACHE_S (RETRY_S after a failure); None when there is nothing
    younger than STALE_S."""
    now = clock()
    found = _cache.get(key, {"tried": -math.inf, "ok": False, "good_at": -math.inf, "value": None})
    due = now - found["tried"] >= (CACHE_S if found["ok"] else RETRY_S)
    lock = _locks.setdefault(key, threading.Lock())
    if due and lock.acquire(blocking=False):
        try:
            found = {"tried": now, "ok": True, "good_at": now, "value": fetch()}
        except FeedError as exc:
            if found["ok"] or found["tried"] == -math.inf:
                log.warning("MetMalaysia feed (%s) failed: %s (asked again every %d s)", key, exc, RETRY_S)
            found = {**found, "tried": now, "ok": False}
        finally:
            lock.release()
        _cache[key] = found
    return found["value"] if now - found["good_at"] <= STALE_S else None


def parse_forecast(rows: Sequence, location_id: str) -> dict[str, dict]:
    """{date: {text, when}} for the location's rows: MetMalaysia's words, in Malay as it gives them."""
    days = {}
    for row in rows:
        if not isinstance(row, Mapping) or (row.get("location") or {}).get("location_id") != location_id:
            continue
        date = row.get("date")
        if isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            days[date] = {"text": _text(row.get("summary_forecast")), "when": _text(row.get("summary_when"))}
    return days


def forecast_for(area_id: str, clock: Callable[[], float] = time.monotonic, section_id: str | None = None) -> dict[str, dict] | None:
    found = place(area_id, section_id)
    if not found:
        return None
    if found[0] is None:   # a whole state: no one place's words
        return {}
    rows = _cached(f"forecast {found[0]}", lambda: _fetch_forecast(found[0]), clock)
    return None if rows is None else parse_forecast(rows, found[0])


def _at_word(text: str, at: int, word: str) -> bool:
    end = at + len(word)
    return (at == 0 or not text[at - 1].isalnum()) and (end == len(text) or not text[end].isalnum())


def covers(text: str, state: str, districts: Sequence[str]) -> bool:
    """Whether a warning's text ("... over the states of Selangor (Petaling, Klang) • Pahang until ...") names the state
    on its own (the whole state), or with one of `districts` in the brackets right after it. A mention inside another
    state's brackets, such as "Hulu Selangor", does not count."""
    depth = 0
    for at, char in enumerate(text):
        depth = max(0, depth + (char == "(") - (char == ")"))
        if depth or not text.startswith(state, at) or not _at_word(text, at, state):
            continue
        rest = text[at + len(state):].lstrip()
        if not rest.startswith("("):
            return True
        inside = rest[1:rest.find(")")] if ")" in rest else rest[1:]
        if any(re.search(rf"\b{re.escape(d)}\b", inside, re.IGNORECASE) for d in districts):
            return True
    return False


def _warning(raw: Mapping) -> dict | None:
    issue = raw.get("warning_issue") or {}
    title, text = issue.get("title_en"), raw.get("text_en")
    start, end = raw.get("valid_from"), raw.get("valid_to")
    if not (isinstance(title, str) and isinstance(text, str) and isinstance(start, str) and isinstance(end, str)):
        return None
    kind = next((name for word, name in WARNING_KINDS if word in title.lower()), None)
    try:
        datetime.fromisoformat(start[:19]), datetime.fromisoformat(end[:19])
    except ValueError:
        return None
    if not kind:
        return None
    return {"title_en": _text(title), "title_ms": _text(issue.get("title_bm")), "heading_en": _text(raw.get("heading_en")),
            "heading_ms": _text(raw.get("heading_bm")), "valid_from": start[:19], "valid_to": end[:19], "kind": kind,
            "text": text}


def warnings_for(area_id: str, now: datetime | None = None, clock: Callable[[], float] = time.monotonic,
                 section_id: str | None = None) -> list[dict] | None:
    """The rain and thunderstorm warnings that cover the area and have not ended, without their long text, soonest
    first; [] for an area without a met.json; None when MetMalaysia gave nothing (the card says so)."""
    where = place(area_id, section_id)
    if not where:
        return []
    rows = _cached("warnings", _fetch_warnings, clock)
    if rows is None:
        return None
    clock_now = (now or datetime.now(timezone.utc)).astimezone(MYT).strftime("%Y-%m-%dT%H:%M:%S")
    found = [w for w in (_warning(r) for r in rows if isinstance(r, Mapping)) if w]
    kept = [w for w in found if w["valid_to"] > clock_now and covers(w["text"], where[2], where[3])]
    return [{k: v for k, v in w.items() if k != "text"} for w in sorted(kept, key=lambda w: w["valid_from"])][:MAX_WARNINGS]


def level(mm: float | None, warned: bool) -> str | None:
    """high: a MetMalaysia continuous-rain warning covers the day (`warned`), or HIGH_MM or more; watch: WATCH_MM or
    more; else low. None without Google's rain and with no such warning."""
    if warned:
        return "high"
    if mm is None:
        return None
    return "high" if mm >= HIGH_MM else "watch" if mm >= WATCH_MM else "low"


def trend(levels: Sequence[str | None]) -> str | None:
    """rising, easing or steady: today against the worst day ahead; None when a day has no level."""
    if not levels or any(lv is None for lv in levels):
        return None
    today, ahead = RANK[levels[0]], max(RANK[lv] for lv in levels[1:])
    return "rising" if ahead > today else "easing" if ahead < today else "steady"


def _covers_day(day: str, warnings: Sequence[Mapping]) -> bool:
    """Whether a warning is in force on the Malaysian date `day`; one ending at 00:00 ends the day before."""
    last = lambda w: (datetime.fromisoformat(w["valid_to"]) - timedelta(seconds=1)).strftime("%Y-%m-%d")
    return any(w["valid_from"][:10] <= day <= last(w) for w in warnings)


def _big_tides(area_id: str, days: Sequence[str], section_id: str | None = None) -> list[bool | None]:
    found = tide.doc(area_id, section_id)
    if found is None:
        return [None] * len(days)
    ranges = tide.day_ranges(area_id, section_id)
    return [ranges[day] >= found["big_range_m"] if day in ranges else None for day in days]


def _rain(rain_fn: Callable, lat: float, lon: float) -> tuple[dict[str, dict], str]:
    try:
        return {d["date"]: d for d in rain_fn(lat, lon, ASK_DAYS)}, "ok"
    except googlemaps.NotConfigured:
        return {}, "off"
    except googlemaps.DailyShareReached:
        return {}, "capped_day"
    except googlemaps.FreeLimitReached:
        return {}, "capped"
    except googlemaps.UpstreamError as exc:
        log.warning("Google daily rain failed: %s", exc)
        return {}, "down"


def arus_link(lat: float, lon: float) -> str | None:
    """A link to Arus (Farhan Syah's flood forecast map) at the spot, from ARUS_URL, a https:// address that may hold
    {lat} and {lon}; None while it is not set or not https. Arus is its author's own, uncalibrated model: the card
    only links to it, and says so."""
    template = os.environ.get("ARUS_URL", "").strip()
    if not template.startswith("https://"):
        return None
    try:
        return template.format(lat=f"{lat:.5f}", lon=f"{lon:.5f}")
    except (KeyError, IndexError, ValueError):
        log.error("ARUS_URL must hold only {lat} and {lon} as placeholders")
        return None


def build(area_id: str, lat: float, lon: float, now: datetime | None = None, rain_fn: Callable | None = None,
          section_id: str | None = None) -> dict:
    """What GET /api/outlook sends: the next DAYS days from today (Malaysian dates), each with Google's rain and
    chance, MetMalaysia's words, whether a warning covers it, a big-tide flag and a level; the warnings themselves; the
    trend; whether Google's rain came ("ok", "capped", "capped_day", "off" or "down"); whether MetMalaysia answered ("ok", "down",
    or "none" for an area without a met.json); and whether levels are given (only in SET_FROM_AREA)."""
    today = (now or datetime.now(timezone.utc)).astimezone(MYT)
    dates = [(today + timedelta(days=k)).strftime("%Y-%m-%d") for k in range(DAYS)]
    rain, rain_state = _rain(rain_fn or googlemaps.rain_days, lat, lon)
    where = place(area_id, section_id)
    words, warnings = forecast_for(area_id, section_id=section_id), warnings_for(area_id, today, section_id=section_id)
    met_state = "none" if not where else "down" if words is None or warnings is None else "ok"
    warnings, words = warnings or [], words or {}
    rain_warnings = [w for w in warnings if w["kind"] == "rain"]
    has_levels = area_id == SET_FROM_AREA
    days = []
    for date, big in zip(dates, _big_tides(area_id, dates, section_id)):
        found = rain.get(date)
        mm = found["mm"] if found else None
        days.append({"date": date, "rain_mm": mm, "chance_pct": found["chance_pct"] if found else None,
                     "level": level(mm, _covers_day(date, rain_warnings)) if has_levels else None,
                     "warned": _covers_day(date, warnings), "met": words.get(date), "big_tide": big})
    calibrated = areas.get(SET_FROM_AREA)
    return {"days": days, "warnings": warnings, "trend": trend([d["level"] for d in days]), "rain": rain_state,
            "met": met_state, "met_place": where[1] if where else None, "levels": has_levels,
            "thresholds": {"watch_mm": WATCH_MM, "high_mm": HIGH_MM, "set_from": calibrated.name if calibrated else None,
                           **CALIBRATION},
            "source": SOURCE, "arus": arus_link(lat, lon)}
