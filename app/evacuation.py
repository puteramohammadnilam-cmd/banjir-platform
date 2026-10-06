"""Flood evacuation centres (PPS) open now, from the public feed behind JKM's InfoBencana portal: for each open centre
its name, district, the disaster, and counts of evacuees and families with how full it is. The feed holds no person's
details. Centres opened for other disasters (fire, storm) are left out: this is a flood tool.

Fetched by the server only, at most once every CACHE_S for all visitors together (RETRY_S after a failure). One request
fetches while the others are answered from what was last fetched, so none waits on JKM. A list older than STALE_S is
not shown. The page gets the centres within MARGIN_KM of the box of the area or section on screen, nearest its middle
first. Standard library only.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone

from .places import distance_m

FEED = "https://infobencanajkmv2.jkm.gov.my/api/pusat-buka.php"
PORTAL = "https://infobencanajkmv2.jkm.gov.my/landing/"
TIMEOUT_S = 8                 # per socket wait, and for the whole read
MAX_BYTES = 2_000_000         # today's answer is under 1 kB; thousands of centres fit well within this
CHUNK = 65_536
CACHE_S = 300
RETRY_S = 60
STALE_S = 900
MARGIN_KM = 5
MAX_SHOWN = 5
MAX_NAME_CHARS = 80
MAX_COUNT = 100_000           # more evacuees than this at one centre is a bad row, not a reading
MAX_FULL_PCT = 1000
KM_PER_DEG = 111.32
MALAYSIA = (99.0, 0.5, 120.0, 7.6)   # west, south, east, north: a centre outside is a bad row
FLOOD = "banjir"              # JKM's word for the disaster, as in "Banjir" and "Banjir Kilat"

log = logging.getLogger(__name__)
_lock = threading.Lock()   # held only by the one request that is fetching; the others do not wait for it
_EMPTY = {"tried": -math.inf, "ok": False, "good_at": -math.inf, "centres": None, "checked": None}
_state = dict(_EMPTY)


class FeedError(RuntimeError):
    """The feed did not answer usefully. The message is for logs."""


def _count(value, ceiling: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if 0 <= number <= ceiling else None


def _text(value) -> str:
    return " ".join(str(value).split())[:MAX_NAME_CHARS] if isinstance(value, (str, int)) else ""


def clean(raw: Mapping) -> dict | None:
    """One centre as the server keeps it, or None for a row that is not a usable centre."""
    lat, lon = _count(raw.get("latti"), 90), _count(raw.get("longi"), 180)
    evacuees, families = _count(raw.get("mangsa"), MAX_COUNT), _count(raw.get("keluarga"), MAX_COUNT)
    full, name = _count(raw.get("kapasiti"), MAX_FULL_PCT), _text(raw.get("name"))
    west, south, east, north = MALAYSIA
    if None in (lat, lon, evacuees, families) or not name or not (west <= lon <= east and south <= lat <= north):
        return None
    return {"name": name, "lat": lat, "lon": lon, "district": _text(raw.get("daerah")),
            "disaster": _text(raw.get("bencana")), "evacuees": int(evacuees), "families": int(families),
            "full_pct": int(full + 0.5) if full is not None else None}


def _read(response) -> bytes:
    """The body, refusing one bigger than MAX_BYTES or slower than TIMEOUT_S in all."""
    deadline, body = time.monotonic() + TIMEOUT_S, b""
    while chunk := response.read(CHUNK):
        body += chunk
        if len(body) > MAX_BYTES or time.monotonic() > deadline:
            raise FeedError("the JKM feed answered too much, or too slowly")
    return body


def _fetch() -> list[dict]:
    """Every open flood centre the feed lists. Raises FeedError for any answer that is not one."""
    request = urllib.request.Request(FEED, headers={"User-Agent": "BanjirCheck/1.0 (flood information tool)"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:   # noqa: S310  fixed https host
            if urllib.parse.urlsplit(response.geturl()).hostname != urllib.parse.urlsplit(FEED).hostname:
                raise FeedError("the JKM feed redirected to another host")
            points = json.loads(_read(response).decode("utf-8")).get("points")
    except FeedError:
        raise
    except urllib.error.HTTPError as exc:
        raise FeedError(f"HTTP {exc.code} from the JKM feed") from exc
    except Exception as exc:   # timeouts, resets, bad JSON or UTF-8, a body that is not an object: all one failure
        raise FeedError(f"{type(exc).__name__} from the JKM feed") from exc
    if not isinstance(points, list):
        raise FeedError("the JKM feed has no list of points")
    centres = [c for c in (clean(p) for p in points if isinstance(p, Mapping)) if c]
    if points and not centres:   # the feed changed shape: say nothing rather than "none open"
        raise FeedError(f"none of the JKM feed's {len(points)} rows could be read")
    return [c for c in centres if FLOOD in c["disaster"].lower()]


def open_centres(clock: Callable[[], float] = time.monotonic, fetch: Callable[[], list] = _fetch) -> tuple | None:
    """(every open flood centre, when it was checked as ISO UTC), or None when there is no list younger than STALE_S."""
    global _state
    now = clock()
    due = now - _state["tried"] >= (CACHE_S if _state["ok"] else RETRY_S)
    if due and _lock.acquire(blocking=False):
        try:
            centres = fetch()
            _state = {"tried": now, "ok": True, "good_at": now, "centres": centres,
                      "checked": datetime.now(timezone.utc).isoformat(timespec="minutes")}
        except FeedError as exc:
            log.warning("Evacuation centre feed failed: %s", exc)
            _state = {**_state, "tried": now, "ok": False}
        finally:
            _lock.release()
    found = _state
    if found["centres"] is None or now - found["good_at"] > STALE_S:
        return None
    return found["centres"], found["checked"]


def near(box: Sequence[float], centres: Sequence[Mapping]) -> list[dict]:
    """The centres within MARGIN_KM of the box [west, south, east, north], nearest its middle first."""
    west, south, east, north = box
    mid_lat, mid_lon = (south + north) / 2, (west + east) / 2
    pad_lat = MARGIN_KM / KM_PER_DEG
    pad_lon = MARGIN_KM / (KM_PER_DEG * math.cos(math.radians(mid_lat)))
    close = [c for c in centres if west - pad_lon <= c["lon"] <= east + pad_lon and south - pad_lat <= c["lat"] <= north + pad_lat]
    return sorted(close, key=lambda c: distance_m(mid_lat, mid_lon, c["lat"], c["lon"]))


def for_box(box: Sequence[float], **ways) -> dict | None:
    """What GET /api/evacuation sends: the nearest flood centres (without their coordinates, which the page does not
    use), how many are open near the box and nationwide, the margin, and when the feed was checked; None while there is
    no recent list."""
    found = open_centres(**ways)
    if found is None:
        return None
    centres, checked = found
    close = near(box, centres)
    shown = [{key: value for key, value in c.items() if key not in ("lat", "lon")} for c in close[:MAX_SHOWN]]
    return {"checked": checked, "count": len(close), "evacuees": sum(c["evacuees"] for c in close),
            "open_nationwide": len(centres), "margin_km": MARGIN_KM, "centres": shown, "source": PORTAL}
