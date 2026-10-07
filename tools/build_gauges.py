"""Build app/data/gauges.json: every JPS river level gauge in Malaysia (name, river, place), so a business or point can
be given the nearest one and a link to its live page on JPS Public Infobanjir.

    .venv/bin/python tools/build_gauges.py

Reads JPS Public Infobanjir's national station list (the feed its own map uses). Only the stations that measure river
level ("WL" in their type) with a place in Malaysia are kept, and only their id, name, river and place: no readings.
The page links to JPS's own 7-day river level graph for the gauge, so JPS's readings stay on JPS's site.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = "https://publicinfobanjir.water.gov.my/wp-content/themes/enlighten/data/latestreadingstrendabc.json"
MALAYSIA = (99.0, 0.5, 120.0, 7.6)   # west, south, east, north
OUT = ROOT / "app" / "data" / "gauges.json"


def fetch() -> list[dict]:
    context = ssl.create_default_context()
    # The site serves an incomplete certificate chain, so it cannot be verified: every id and name kept is checked
    # against strict patterns below (and again by app/gauges.py), and the run is by hand, once.
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    request = urllib.request.Request(FEED, headers={"User-Agent": "BanjirCheck (station list, once)"})
    with urllib.request.urlopen(request, timeout=120, context=context) as response:   # noqa: S310  fixed https host
        return json.loads(response.read().decode("utf-8", "replace"))


def gauges(stations: list[dict]) -> list[dict]:
    west, south, east, north = MALAYSIA
    kept = {}
    for s in stations:
        try:
            lat, lon = float(s["c"]), float(s["d"])
        except (KeyError, TypeError, ValueError):
            continue
        name, sid = " ".join(str(s.get("b") or "").split()), str(s.get("a") or "").strip()
        plain = re.fullmatch(r"[A-Za-z0-9_ -]{1,20}", sid) and re.fullmatch(r"[^<>]{1,80}", name)
        if "WL" not in str(s.get("i") or "") or not plain or not (west <= lon <= east and south <= lat <= north):
            continue
        kept[sid] = {"id": sid, "name": name, "river": " ".join(str(s.get("g") or "").split())[:80],
                                     "lat": round(lat, 5), "lon": round(lon, 5)}
    return sorted(kept.values(), key=lambda g: g["id"])


def main() -> int:
    found = gauges(fetch())
    OUT.write_text(json.dumps({"version": 1, "source": "JPS Public Infobanjir station list", "gauges": found},
                              separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(found)} river level gauges, {OUT.stat().st_size // 1024} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
