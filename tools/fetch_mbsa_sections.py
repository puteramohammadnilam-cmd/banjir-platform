"""Fetch the Shah Alam city outline and its 56 Seksyen (MBSA sections) from OpenStreetMap (plan WS-B, data groundwork).

    .venv/bin/python tools/fetch_mbsa_sections.py [--out DIR] [--date YYYY-MM-DD]

Run from 11_Platform_Draft. Two Overpass questions, a pause between them:
  rel(8347577);rel(r:"subarea");out geom;   the section relations: Seksyen 1 to 36 and U1 to U20
  rel(8347577);out geom;                     the city's own outline (administrative boundary, level 7)
Overpass answers HTTP 406 to a request with no descriptive User-Agent, so one is sent.

It writes outside the repo, into DIR (default ../05_Raw_Data_Sources/shah_alam/mbsa_sections):
  raw_YYYY-MM-DD/sections.json, outline.json   the Overpass answers as they came
  sections.geojson     one MultiPolygon feature per section: name, section, osm_id, area_km2
  city_outline.geojson the city outline in the same form
  SOURCES.md           source, date, counts, total area, ODbL attribution and the limits

Areas are on the sphere, from the rings OSM draws (equal-area cylindrical projection, exact on a sphere), so they differ
from a surveyed area by well under a percent.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

DEFAULT_OUT = SHAH_ALAM_RAW / "mbsa_sections"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CITY_RELATION = 8347577
SECTIONS_QUERY = f'[out:json][timeout:120];rel({CITY_RELATION});rel(r:"subarea");out geom;'
OUTLINE_QUERY = f"[out:json][timeout:120];rel({CITY_RELATION});out geom;"
USER_AGENT = "myflood-research/0.1 (flood risk research prototype; one-off data fetch)"
PAUSE_SECONDS = 2.0
RETRIES = 3
RETRY_WAIT_FACTOR = 15   # times the pause: 30 s before a second try
BUSY_CODES = {429, 502, 503, 504}
EXPECTED_SECTIONS = 56
EARTH_RADIUS_KM = 6371.0088
CLOSE_ENOUGH = 1e-7   # degrees: two way ends this near are the same node

Post = Callable[[str], dict]
Ring = list[tuple[float, float]]   # (lon, lat), first point equals the last


def overpass_post(query: str) -> dict:
    """Ask Overpass, with a descriptive User-Agent, and give back its JSON answer. A busy server (429, 502 to 504) is
    asked again after a longer wait, up to three times in all."""
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(RETRIES):
        time.sleep(PAUSE_SECONDS * (1 if attempt == 0 else RETRY_WAIT_FACTOR))
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in BUSY_CODES or attempt == RETRIES - 1:
                raise
    raise RuntimeError("unreachable")


# ---------- rings: ways joined end to end

def _same(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < CLOSE_ENOUGH and abs(a[1] - b[1]) < CLOSE_ENOUGH


def _way_points(member: dict) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in member.get("geometry") or []]


def stitch_rings(ways: list[list[tuple[float, float]]]) -> tuple[list[Ring], int]:
    """Join ways end to end into closed rings. Returns (rings, how many ways were left over in a ring that did not close)."""
    pending = [w for w in ways if len(w) >= 2]
    rings: list[Ring] = []
    open_ways = 0
    while pending:
        ring = list(pending.pop(0))
        grown = True
        while grown and not _same(ring[0], ring[-1]):
            grown = False
            for i, way in enumerate(pending):
                if _same(ring[-1], way[0]):
                    ring.extend(way[1:])
                elif _same(ring[-1], way[-1]):
                    ring.extend(reversed(way[:-1]))
                else:
                    continue
                pending.pop(i)
                grown = True
                break
        if _same(ring[0], ring[-1]) and len(ring) >= 4:
            rings.append(ring)
        else:
            open_ways += 1
    return rings, open_ways


def ring_area_km2(ring: Ring) -> float:
    """The area inside a ring on the sphere (shoelace on an equal-area cylindrical projection), always positive."""
    xs = [math.radians(lon) * EARTH_RADIUS_KM for lon, _ in ring]
    ys = [math.sin(math.radians(lat)) * EARTH_RADIUS_KM for _, lat in ring]
    twice = sum(xs[i] * ys[i + 1] - xs[i + 1] * ys[i] for i in range(len(ring) - 1))
    return abs(twice) / 2


def _inside(point: tuple[float, float], ring: Ring) -> bool:
    x, y = point
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


# ---------- relations to features

def relation_polygons(relation: dict) -> tuple[list[list[Ring]], int]:
    """The relation's outer rings, each with the inner rings (holes) that lie inside it, and the open-ring count."""
    outers, open_outer = stitch_rings([_way_points(m) for m in relation.get("members", []) if m.get("type") == "way" and m.get("role") == "outer"])
    inners, open_inner = stitch_rings([_way_points(m) for m in relation.get("members", []) if m.get("type") == "way" and m.get("role") == "inner"])
    polygons = [[outer] for outer in outers]
    for hole in inners:
        home = next((poly for poly in polygons if _inside(hole[0], poly[0])), None)
        if home is not None:
            home.append(hole)
    return polygons, open_outer + open_inner


def polygon_area_km2(polygon: list[Ring]) -> float:
    return ring_area_km2(polygon[0]) - sum(ring_area_km2(hole) for hole in polygon[1:])


def feature_of(relation: dict) -> dict:
    """A GeoJSON MultiPolygon feature for one boundary relation, with its name, section and area."""
    tags = relation.get("tags", {})
    polygons, open_rings = relation_polygons(relation)
    name = tags.get("name", "")
    section = re.sub(r"^(Seksyen|Section)\s+", "", name, flags=re.I)
    properties = {"osm_id": relation["id"], "name": name, "name_en": tags.get("name:en"), "section": section or None,
                  "admin_level": tags.get("admin_level"), "area_km2": round(sum(polygon_area_km2(p) for p in polygons), 3)}
    if open_rings:
        properties["open_rings"] = open_rings
    return {"type": "Feature", "properties": properties,
            "geometry": {"type": "MultiPolygon", "coordinates": [[[list(pt) for pt in ring] for ring in poly] for poly in polygons]}}


def section_order(feature: dict) -> tuple[int, int, str]:
    """1 to 36 first in number order, then U1 to U20."""
    section = feature["properties"].get("section") or ""
    number = re.sub(r"\D", "", section)
    return (section.upper().startswith("U"), int(number) if number else 0, section)


def sections_of(answer: dict) -> list[dict]:
    relations = [e for e in answer.get("elements", []) if e.get("type") == "relation"]
    return sorted((feature_of(r) for r in relations), key=section_order)


def outline_of(answer: dict) -> dict:
    relations = [e for e in answer.get("elements", []) if e.get("type") == "relation" and e["id"] == CITY_RELATION]
    if not relations:
        raise RuntimeError(f"the answer holds no relation {CITY_RELATION}")
    return feature_of(relations[0])


# ---------- files

def collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def sources_md(sections: list[dict], outline: dict, stamps: dict, fetched_on: str) -> str:
    """The SOURCES.md text: provenance, counts, areas, attribution and limits."""
    total = sum(f["properties"]["area_km2"] for f in sections)
    city = outline["properties"]["area_km2"]
    open_rings = [f["properties"]["name"] for f in sections + [outline] if f["properties"].get("open_rings")]
    note = "all rings closed" if not open_rings else f"rings that did not close in: {', '.join(open_rings)}"
    return f"""# MBSA sections of Shah Alam (OpenStreetMap)

Fetched {fetched_on} by tools/fetch_mbsa_sections.py from the Overpass API ({OVERPASS_URL}); OSM data as of {stamps.get('sections', '?')}.

    {SECTIONS_QUERY}
    {OUTLINE_QUERY}

- {len(sections)} section relations (expected {EXPECTED_SECTIONS}: Seksyen 1 to 36 and U1 to U20), admin_level 10, subareas of
  the Shah Alam city relation {CITY_RELATION}. Files: `sections.geojson`, `city_outline.geojson`.
- Sum of the sections' areas: {total:.1f} km2. The city outline alone: {city:.1f} km2 (the project notes expected about 301 km2 for the
  city). Areas are computed here from the drawn rings on a sphere ({note}).
- Raw answers: `raw_{fetched_on}/sections.json` and `outline.json`.

## Attribution

Contains information from OpenStreetMap, which is made available under the Open Database License (ODbL) 1.0.
(c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright. Anything built from these files and shared
must carry that credit, and a database derived from them is shared under the same licence.

## Limits

- OSM boundaries are drawn by volunteers from MBSA's section plans. They are not the council's own cadastral lines.
- The sections cover the part of the city MBSA numbers; the city outline also holds land outside any section.
- The Overpass server refuses requests with no descriptive User-Agent (HTTP 406).
"""


def build(out: Path, fetched_on: str, post: Post = overpass_post) -> dict:
    """Ask Overpass for the sections and the outline, write the files under `out`. Returns the counts and areas."""
    raw_sections = post(SECTIONS_QUERY)
    raw_outline = post(OUTLINE_QUERY)
    sections, outline = sections_of(raw_sections), outline_of(raw_outline)
    raw_dir = out / f"raw_{fetched_on}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "sections.json").write_text(json.dumps(raw_sections, ensure_ascii=False) + "\n", encoding="utf-8")
    (raw_dir / "outline.json").write_text(json.dumps(raw_outline, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, features in (("sections.geojson", sections), ("city_outline.geojson", [outline])):
        (out / name).write_text(json.dumps(collection(features), ensure_ascii=False) + "\n", encoding="utf-8")
    stamps = {"sections": (raw_sections.get("osm3s") or {}).get("timestamp_osm_base")}
    (out / "SOURCES.md").write_text(sources_md(sections, outline, stamps, fetched_on), encoding="utf-8")
    return {"sections": len(sections), "sections_km2": sum(f["properties"]["area_km2"] for f in sections),
            "city_km2": outline["properties"]["area_km2"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--date", default=date.today().isoformat(), help="the date in the raw folder's name")
    args = parser.parse_args(argv)
    counts = build(args.out, args.date)
    print(f"{counts['sections']} sections (expected {EXPECTED_SECTIONS}), {counts['sections_km2']:.1f} km2 together; "
          f"city outline {counts['city_km2']:.1f} km2 -> {args.out}")
    return 0 if counts["sections"] == EXPECTED_SECTIONS else 1


if __name__ == "__main__":
    sys.exit(main())
