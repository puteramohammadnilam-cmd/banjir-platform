"""Google Maps Platform, called from the server only: Weather API (rain outlook) and Places API (is a shop open).

Set GOOGLE_MAPS_API_KEY in .env. The key never reaches the browser and travels in a header, not the URL.
Without it, everything here raises NotConfigured and the page simply leaves these items out. Standard library
only, no extra dependency.

Terms that shape this file: Google Maps content may not be cached beyond what each API's terms allow (for
Places, only coordinates and place ids), so nothing here is cached and spend is bounded by the per-visitor
limits in main.py plus the quotas and budget set in Google Cloud (see README). Results are shown with Google
attribution by the callers.

Monthly cap: every Weather and Places call is counted before it is made, and once a month's count reaches its limit
(FREE_LIMITS, under Google's free allowance) the call is not made and FreeLimitReached is raised, so this site alone
cannot run up a bill. The count is kept in MAPS_USAGE_FILE so a restart or deploy does not reset it, and a count that
cannot be read or saved stops the calls rather than start again from 0. Google counts per billing account: other
projects on the same account share the free allowance and are not counted here.
"""
from __future__ import annotations

import http.client
import json
import logging
import math
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

WEATHER = "https://weather.googleapis.com/v1/forecast/hours:lookup"
PLACES = "https://places.googleapis.com/v1/places:searchText"
PLACE_FIELDS = "places.id,places.displayName,places.businessStatus,places.googleMapsUri,places.location"
TIMEOUT_S = 8
MATCH_RADIUS_M = 150      # only Google places this close to the mapped point count, and the search is fenced to it
MM_PER_INCH = 25.4
MAX_NAME_CHARS = 80       # a listing's name is set by whoever owns the listing: keep it short and plain
UNNAMED = "Unnamed"       # how tools/build_area.py labels businesses with no name on the map
STATUS = {"OPERATIONAL": "open", "CLOSED_TEMPORARILY": "closed for now",
          "CLOSED_PERMANENTLY": "closed for good", "FUTURE_OPENING": "not open yet"}
# Calls a month, kept 10% under Google's free allowance (Nov 2026: Weather 10,000; Places Text Search Pro 5,000, then
# USD 32 per 1,000). MAPS_WEATHER_MONTHLY_LIMIT / MAPS_PLACES_MONTHLY_LIMIT can set them lower, never higher.
FREE_LIMITS = {"weather": 9_000, "places": 4_500}
# Google starts the free allowance again at midnight US Pacific on the 1st. A fixed UTC-8 starts our month at that
# moment in winter and an hour after it in summer time, never before it.
BILLING_TZ = timezone(timedelta(hours=-8))
USAGE_FILE = Path(__file__).resolve().parents[1] / ".maps-usage.json"   # MAPS_USAGE_FILE overrides it

log = logging.getLogger(__name__)
_usage_lock = threading.Lock()
_usage: dict | None = None    # {"month": "YYYY-MM" or None, "weather": n, "places": n}; read from the file on first use


class NotConfigured(RuntimeError):
    """No Google Maps Platform key in the environment."""


class UpstreamError(RuntimeError):
    """A Google API did not answer usefully. The message is for logs, not for users, and never holds the key."""


class FreeLimitReached(RuntimeError):
    """This month's free calls of one kind are used up, or their count cannot be kept: the call was not made."""


def _usage_file() -> Path:
    return Path(os.environ.get("MAPS_USAGE_FILE") or USAGE_FILE)


def _limit(kind: str) -> int:
    raw = os.environ.get(f"MAPS_{kind.upper()}_MONTHLY_LIMIT", "").strip()
    try:
        wanted = int(raw) if raw else FREE_LIMITS[kind]
    except ValueError:
        return 0   # a bad setting stops the calls rather than risk a bill
    return max(0, min(wanted, FREE_LIMITS[kind]))


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _stopped(reason: str) -> FreeLimitReached:
    log.error("Google Maps calls stopped: %s (%s)", reason, _usage_file())
    return FreeLimitReached(reason)


def _load() -> dict:
    path = _usage_file()
    if not path.exists():
        return {"month": None}
    try:
        usage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _stopped(f"cannot read the usage file ({type(exc).__name__})") from exc
    if (not isinstance(usage, dict) or not isinstance(usage.get("month"), str)
            or not all(_is_count(usage.get(kind, 0)) for kind in FREE_LIMITS)):
        raise _stopped("the usage file does not hold a month and counts")
    return usage


def _save(usage: dict) -> None:
    path = _usage_file()
    part = path.with_name(path.name + ".part")
    try:
        part.write_text(json.dumps(usage), encoding="utf-8")
        os.replace(part, path)   # whole or not at all: a crash mid-write cannot leave half a count
    except OSError as exc:
        raise _stopped(f"cannot save the usage file ({type(exc).__name__})") from exc


def _spend(kind: str, now: datetime | None = None) -> None:
    """Count one call of `kind` ("weather" or "places") this month, or raise FreeLimitReached without counting it."""
    global _usage
    month = (now or datetime.now(timezone.utc)).astimezone(BILLING_TZ).strftime("%Y-%m")
    with _usage_lock:
        usage = _usage if _usage is not None else _load()
        if usage.get("month") != month:
            usage = {"month": month}
        used, limit = usage.get(kind, 0), _limit(kind)
        if used >= limit:
            _usage = usage
            raise FreeLimitReached(f"{kind}: {used} calls this month, the free limit")
        counted = {**usage, kind: used + 1}
        _save(counted)
        _usage = counted
    if used + 1 == limit:
        log.warning("Google Maps %s: this month's %d free calls are used up; no more until the 1st (US Pacific)",
                    kind, limit)


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_MAPS_API_KEY", "").strip())


def _key() -> str:
    if not is_configured():
        raise NotConfigured("Set GOOGLE_MAPS_API_KEY in .env (see .env.example).")
    return os.environ["GOOGLE_MAPS_API_KEY"].strip()


def _fetch(request: urllib.request.Request) -> dict:
    where = request.full_url.split("?")[0]
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"HTTP {exc.code} from {where}") from exc
    except (OSError, http.client.HTTPException, ValueError) as exc:   # timeouts, resets, short reads, bad JSON
        raise UpstreamError(f"{type(exc).__name__} from {where}") from exc


def _get(url: str, params: dict, headers: dict) -> dict:
    return _fetch(urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=headers))


def _post(url: str, body: dict, headers: dict) -> dict:
    return _fetch(urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", **headers}))


def _mm(qpf: dict) -> float:
    quantity = float(qpf.get("quantity") or 0)
    return quantity * MM_PER_INCH if qpf.get("unit") == "INCHES" else quantity


def summarize_hours(hours: list[dict]) -> dict:
    """Total rain, the wettest hour and the highest chance of rain over a list of forecast hours."""
    rows = [(h.get("interval", {}).get("startTime"), _mm(h.get("precipitation", {}).get("qpf", {})),
             h.get("precipitation", {}).get("probability", {}).get("percent") or 0) for h in hours]
    wettest = max(rows, key=lambda r: r[1], default=None)
    return {
        "hours": len(rows),
        "total_mm": round(sum(r[1] for r in rows), 1),
        "max_chance_pct": max((r[2] for r in rows), default=0),
        "wettest": ({"start": wettest[0], "mm": round(wettest[1], 1)}
                    if wettest and wettest[1] > 0 and wettest[0] else None),
        "now": (hours[0].get("weatherCondition", {}).get("description", {}).get("text") if hours else None),
        "first_hour": rows[0][0] if rows else None,
        "source": "Google Weather",
    }


def rain_outlook(lat: float, lon: float, hours: int) -> dict:
    """Rain expected over the next `hours` hours at one point, from the Google Weather API."""
    headers = {"X-Goog-Api-Key": _key()}
    _spend("weather")
    data = _get(WEATHER, {"location.latitude": lat, "location.longitude": lon, "hours": hours, "pageSize": hours},
                headers)
    forecast = data.get("forecastHours", [])[:hours]
    # an empty or unrecognised answer must not read as "no rain" in a flood tool
    if not any("precipitation" in h for h in forecast):
        raise UpstreamError("no usable forecast hours from Google Weather")
    return summarize_hours(forecast)


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * 110_574
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def _same_name(ours: str, theirs: str) -> bool:
    """Every word of one name is in the other, short words such as "YY" included."""
    a, b = (set(re.findall(r"[a-z0-9]+", text.lower())) for text in (ours, theirs))
    return bool(a and b) and (a <= b or b <= a)


def _plain(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:MAX_NAME_CHARS].strip()


def _listing(p: dict) -> tuple[float, float, str] | None:
    """A listing's point and name, or None when Google sends either as null or leaves part of it out."""
    location, shown = p.get("location") or {}, p.get("displayName") or {}
    plat, plon, text = location.get("latitude"), location.get("longitude"), shown.get("text")
    if not (isinstance(plat, (int, float)) and isinstance(plon, (int, float)) and isinstance(text, str)):
        return None
    return plat, plon, text


def place_status(name: str, lat: float, lon: float) -> dict | None:
    """The Google Maps listing with a matching name within MATCH_RADIUS_M of a mapped business, else None.

    A name match is a shared word of three or more letters, so a neighbour with nothing in common cannot stand in for
    the shop. One with the same name wins, then the one sharing the most words, then the nearest. same_name is true
    when every word of one name is in the other ("KFC" and "KFC Drive Thru"), and false for "Kedai Runcit Abu" against
    "Kedai Runcit Ali": two shared words, and maybe another shop."""
    if name.startswith(UNNAMED) or not _words(name):
        return None
    dlat, dlon = MATCH_RADIUS_M / 110_574, MATCH_RADIUS_M / (111_320 * math.cos(math.radians(lat)))
    headers = {"X-Goog-Api-Key": _key(), "X-Goog-FieldMask": PLACE_FIELDS}
    _spend("places")
    data = _post(PLACES, {"textQuery": name, "pageSize": 5,
                          "locationRestriction": {"rectangle": {
                              "low": {"latitude": lat - dlat, "longitude": lon - dlon},
                              "high": {"latitude": lat + dlat, "longitude": lon + dlon}}}},
                 headers)
    wanted = _words(name)
    listings = [(p, got) for p in data.get("places") or [] if (got := _listing(p))]   # a broken listing is skipped
    found = [(_metres(lat, lon, plat, plon), p, text) for p, (plat, plon, text) in listings if wanted & _words(text)]
    in_reach = [f for f in found if f[0] <= MATCH_RADIUS_M]
    best = min(in_reach, key=lambda f: (not _same_name(name, f[2]), -len(wanted & _words(f[2])), f[0]), default=None)
    if best is None:
        return None
    distance, p, text = best
    raw = p.get("businessStatus", "")
    return {"status": STATUS.get(raw, "unknown"), "google_status": raw or None,
            "name": _plain(text), "same_name": _same_name(name, text),
            "maps_uri": p["googleMapsUri"] if str(p.get("googleMapsUri", "")).startswith("https://") else None,
            "distance_m": round(distance), "source": "Google Maps"}
