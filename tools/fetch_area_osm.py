"""Fetch a whole city's businesses and roads from OpenStreetMap once (plan Phase 2, workstream E, gate G-P2-1).

    .venv/bin/python tools/fetch_area_osm.py [--relation 8347577] [--sections GEOJSON] [--out DIR] [--date YYYY-MM-DD]

Run from 11_Platform_Draft. Two Overpass questions, a pause before each:
  businesses  shops, crafts, eateries and pharmacies (what tools/build_area.py keeps) inside the city's boundary
              relation, as the Overpass area 3600000000 + relation id, `out center meta` (a centre for ways and
              relations, and the last-edited date build_area needs)
  roads       the roads a vehicle can use (build_area's VEHICLE_ROADS) in the box of the sections widened by
              --margin-m (500 m), so a business near the city edge still finds the road outside it, `out geom`
If the city-wide question times out (an Overpass "runtime error" remark, HTTP 504 after the retries, or no answer in
time), the same question is asked section by section (each section's own area, or its own widened box for roads) and
the answers are merged, each element once, in Overpass order (nodes, ways, relations; by id).

Polite by design: one question at a time, a pause before each, a longer wait and up to three tries when the server is
busy, and a User-Agent that names the project and nothing about a person.

It writes outside the repo, into DIR (default ../05_Raw_Data_Sources/shah_alam/city_osm):
  pois.json, roads.json   the Overpass answers (merged when fetched by section)
  SOURCES.md              the queries, the date, how it was fetched, counts and the ODbL credit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sections_io  # noqa: E402
from build_area import EATERIES, M_PER_DEG_LAT, M_PER_DEG_LON_EQUATOR, VEHICLE_ROADS  # noqa: E402
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

DEFAULT_OUT = SHAH_ALAM_RAW / "city_osm"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CITY_RELATION = 8347577
AREA_OFFSET = 3_600_000_000          # Overpass area id = this + the relation id
VERSION = "0.2"
USER_AGENT = f"BanjirCheck/{VERSION} (flood research)"
QUERY_TIMEOUT_S = 300                # what Overpass is told it may take
READ_TIMEOUT_S = 400                 # how long we wait for the answer
PAUSE_SECONDS = 2.0
RETRIES = 3
RETRY_WAIT_FACTOR = 15               # times the pause: 30 s before a second try
BUSY_CODES = {429, 502, 503, 504}
ROAD_MARGIN_M = 500.0
TYPE_ORDER = {"node": 0, "way": 1, "relation": 2}
AMENITIES = "|".join(sorted(EATERIES | {"pharmacy"}))
ROAD_KINDS = "|".join(sorted(VEHICLE_ROADS))

Post = Callable[[str], dict]
BBox = tuple[float, float, float, float]   # west, south, east, north


class OverpassTimeout(RuntimeError):
    """Overpass ran out of time (or memory) on a question, so the answer is missing or cut short."""


# ---------- the questions

def area_id(relation: int) -> int:
    return AREA_OFFSET + relation


def pois_query(relation: int, timeout: int = QUERY_TIMEOUT_S) -> str:
    """The businesses build_area keeps, inside one boundary relation."""
    return (f"[out:json][timeout:{timeout}];area({area_id(relation)})->.a;("
            f'nwr["shop"](area.a);nwr["craft"](area.a);nwr["amenity"~"^({AMENITIES})$"](area.a););'
            "out center meta;")


def roads_query(box: BBox, timeout: int = QUERY_TIMEOUT_S) -> str:
    """The vehicle roads in a (west, south, east, north) box; Overpass wants (south, west, north, east)."""
    west, south, east, north = box
    return (f"[out:json][timeout:{timeout}];"
            f'way["highway"~"^({ROAD_KINDS})$"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});out geom;')


def widen(box: BBox, metres: float) -> BBox:
    """The box grown by `metres` on every side (a degree of longitude measured at the box's middle latitude)."""
    west, south, east, north = box
    dlat = metres / M_PER_DEG_LAT
    dlon = metres / (M_PER_DEG_LON_EQUATOR * math.cos(math.radians((south + north) / 2)))
    return (west - dlon, south - dlat, east + dlon, north + dlat)


def union_box(boxes: Sequence[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


# ---------- asking Overpass

def overpass_post(query: str) -> dict:
    """Ask Overpass, with the project's User-Agent, and give back its JSON answer. A busy server (429, 502 to 504) is
    asked again after a longer wait, up to three times in all; the last refusal is raised."""
    body = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(RETRIES):
        time.sleep(PAUSE_SECONDS * (1 if attempt == 0 else RETRY_WAIT_FACTOR))
        try:
            with urllib.request.urlopen(request, timeout=READ_TIMEOUT_S) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in BUSY_CODES or attempt == RETRIES - 1:
                raise
    raise RuntimeError("unreachable")


def checked(answer: dict) -> dict:
    """The answer, unless Overpass says in its remark that it ran out of time or memory."""
    remark = str(answer.get("remark") or "")
    if "runtime error" in remark.lower():
        raise OverpassTimeout(remark)
    return answer


def _is_timeout(error: Exception) -> bool:
    if isinstance(error, (OverpassTimeout, TimeoutError)):
        return True
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 504
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, TimeoutError)


def merge(answers: Sequence[dict]) -> dict:
    """One answer from several: each element once (the first copy), in Overpass order (nodes, ways, relations; by id).
    The oldest data timestamp of the parts is kept, as the one that holds for all of them."""
    seen: dict[tuple[str, int], dict] = {}
    for answer in answers:
        for element in answer.get("elements", []):
            seen.setdefault((element["type"], element["id"]), element)
    stamps = sorted(s for s in ((a.get("osm3s") or {}).get("timestamp_osm_base") for a in answers) if s)
    merged = {"version": 0.6, "generator": f"tools/fetch_area_osm.py, {len(answers)} Overpass answers merged",
              "osm3s": {"timestamp_osm_base": stamps[0] if stamps else None,
                        "copyright": "The data included in this document is from www.openstreetmap.org. "
                                     "The data is made available under ODbL."}}
    order = sorted(seen, key=lambda key: (TYPE_ORDER.get(key[0], 3), key[1]))
    return {**merged, "elements": [seen[key] for key in order]}


def ask(post: Post, whole: str, parts: Sequence[str]) -> tuple[dict, str]:
    """(answer, how): the whole question's answer and "city", or, when it times out, the parts' merged answer and
    "sections". Any other failure is raised."""
    try:
        return checked(post(whole)), "city"
    except Exception as error:   # noqa: BLE001 - only a timeout falls back; anything else goes on up
        if not _is_timeout(error):
            raise
    return merge([checked(post(query)) for query in parts]), "sections"


# ---------- the files

def sources_md(fetched_on: str, queries: dict, how: dict, answers: dict, files: dict) -> str:
    """The SOURCES.md text: what was asked, how it was answered, counts, file sizes and hashes, attribution, limits.
    files maps each name ("pois", "roads") to the bytes written."""
    lines = ["# City businesses and roads (OpenStreetMap)", "",
             f"Fetched {fetched_on} by tools/fetch_area_osm.py from the Overpass API ({OVERPASS_URL}),",
             f'User-Agent "{USER_AGENT}".', ""]
    for name in ("pois", "roads"):
        stamp = (answers[name].get("osm3s") or {}).get("timestamp_osm_base")
        lines += [f"## {name}.json", "",
                  f"- {len(answers[name]['elements'])} elements, OSM data as of {stamp}; "
                  + ("the city-wide question timed out, so it was asked section by section and the answers merged."
                     if how[name] == "sections" else "one city-wide question."),
                  f"- {len(files[name])} bytes, SHA-256 {hashlib.sha256(files[name]).hexdigest()}.",
                  "- Query (city-wide form):", "", f"      {queries[name]}", ""]
    return "\n".join(lines + [
        "Businesses are shops, crafts, eateries (restaurant, cafe, fast_food, food_court) and pharmacies, the ones",
        "tools/build_area.py keeps. Roads are the vehicle roads it keeps, in the sections' box widened by 500 m.", "",
        "shelters.json beside them is not from OpenStreetMap's own lists: tools/pps_shelters.py writes it from",
        "../pps/pps.csv (relief centres named in news reports, placed with OSM; see ../pps/SOURCES.md).", "",
        "## Attribution", "",
        "Contains information from OpenStreetMap, which is made available under the Open Database License (ODbL) 1.0.",
        "(c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright. Anything built from these files and",
        "shared must carry that credit, and a database derived from them is shared under the same licence.", "",
        "## Limits", "",
        "- What volunteers have mapped, not checked on the ground: many real businesses are missing and some listed",
        "  ones may have closed.",
        "- A business is in the city when Overpass puts it inside the city's boundary relation.", ""])


def fetch(out: Path, fetched_on: str, sections: Sequence[dict], relation: int = CITY_RELATION,
          margin_m: float = ROAD_MARGIN_M, post: Post = overpass_post) -> dict:
    """Ask for the businesses and roads, write pois.json, roads.json and SOURCES.md under `out`. Returns counts."""
    box = widen(union_box([s["bbox"] for s in sections]), margin_m)
    queries = {"pois": pois_query(relation), "roads": roads_query(box)}
    parts = {"pois": [pois_query(s["osm_id"]) for s in sections],
             "roads": [roads_query(widen(s["bbox"], margin_m)) for s in sections]}
    answers, how = {}, {}
    for name in ("pois", "roads"):
        answers[name], how[name] = ask(post, queries[name], parts[name])
    out.mkdir(parents=True, exist_ok=True)
    files = {name: (json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8") for name, answer in answers.items()}
    for name, data in files.items():
        (out / f"{name}.json").write_bytes(data)
    (out / "SOURCES.md").write_text(sources_md(fetched_on, queries, how, answers, files), encoding="utf-8")
    return {name: len(answer["elements"]) for name, answer in answers.items()} | {"how": how}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--relation", type=int, default=CITY_RELATION, help="the city's boundary relation id")
    parser.add_argument("--sections", type=Path, help="sections.geojson (default: the raw MBSA sections file)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--margin-m", type=float, default=ROAD_MARGIN_M, help="metres the roads box is widened by")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    sections = sections_io.load_sections(args.sections)
    counts = fetch(args.out, args.date, sections, args.relation, args.margin_m)
    print(f"{counts['pois']} business elements ({counts['how']['pois']}), {counts['roads']} roads "
          f"({counts['how']['roads']}) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
