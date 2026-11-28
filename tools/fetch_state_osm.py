"""Ask Overpass for a whole state's rivers, drains and roads, tile by tile: the OpenStreetMap inputs that
tools/build_elevation.py (rivers) and tools/build_section_scores.py (rivers, drains, roads) take, for an area too big
for the one question tools/build_elevation.py fetch and tools/fetch_indexes.py drains ask.

    .venv/bin/python tools/fetch_state_osm.py --area johor [--tiles 3] [rivers] [drains] [roads]

Run from 11_Platform_Draft (no layer named: all three). Boxes: the rivers', as tools/build_elevation.py grows the
area's box for them (margin, nearest-river cap and river-level radius); the drains' and roads', tools/fetch_indexes.py's
(the index grid's edges and a little more). Each box is cut into tiles x tiles parts, asked one at a time with
tools/fetch_area_osm.py's polite asking (its User-Agent, a pause before each question, longer waits when Overpass is
busy); a part Overpass runs out of time on is cut in four and asked again, down to MAX_SPLITS times. The answers are
merged (each element once, the oldest data timestamp kept). Each part's answer is kept in a .parts folder beside the
file until the whole is written, so a run stopped by a busy server goes on where it stopped; a part Overpass is still
too busy for after fetch_area_osm.py's three tries is asked again after BUSY_WAIT_S, up to BUSY_ROUNDS times. Writes,
unless the file is already there:
  <raw>/copernicus_glo30/rivers_{name}.json               the rivers question of tools/build_elevation.py
  <raw>/<area>/indexes/osm_drains/drains_{name}.json      rivers, canals, streams, drains and ditches
  <raw>/<area>/indexes/osm_roads/roads_{name}.json        vehicle roads, service ways left out
and logs the drains and roads in <raw>/<area>/indexes/fetch_log.json (and SOURCES.md) as tools/fetch_indexes.py does.
Data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_elevation as be  # noqa: E402
import build_section_scores as bs  # noqa: E402
import fetch_area_osm as fa  # noqa: E402
import fetch_indexes as fi  # noqa: E402
import index_inputs as ii  # noqa: E402
from rawpaths import RAW_SOURCES  # noqa: E402

LAYERS = ("rivers", "drains", "roads")
MAX_SPLITS = 2
BUSY_WAIT_S = 120
BUSY_ROUNDS = 5
TIMEOUT_S = fa.QUERY_TIMEOUT_S
Box = tuple[float, float, float, float]   # west, south, east, north


def tiles(box: Box, n: int) -> list[Box]:
    """The box cut into n x n parts, north-west first."""
    west, south, east, north = box
    dx, dy = (east - west) / n, (north - south) / n
    return [(west + i * dx, north - (j + 1) * dy, west + (i + 1) * dx, north - j * dy) for j in range(n) for i in range(n)]


def _bbox(box: Box) -> str:
    west, south, east, north = box
    return f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"


def rivers_query(box: Box) -> str:
    return be.overpass_query(box).replace("[timeout:120]", f"[timeout:{TIMEOUT_S}]")


def drains_query(box: Box) -> str:
    kinds = "|".join(fi.DRAIN_TYPES)
    return f'[out:json][timeout:{TIMEOUT_S}];way["waterway"~"^({kinds})$"]({_bbox(box)});out geom;'


def roads_query(box: Box) -> str:
    kinds = "|".join(sorted(bs.ROAD_KINDS))
    return f'[out:json][timeout:{TIMEOUT_S}];way["highway"~"^({kinds})$"]({_bbox(box)});out geom;'


def ask_box(query_of: Callable[[Box], str], box: Box, post: fa.Post, splits: int = MAX_SPLITS) -> list[dict]:
    """The answers for one box: one, or, when Overpass runs out of time and splits are left, its four parts'."""
    try:
        return [fa.checked(post(query_of(box)))]
    except Exception as error:   # noqa: BLE001 - only a timeout is split; anything else goes on up
        if not (fa._is_timeout(error) and splits > 0):
            raise
    print(f"  timed out; asking its four parts", flush=True)
    return [a for part in tiles(box, 2) for a in ask_box(query_of, part, post, splits - 1)]


def patient(post: fa.Post, wait_s: float = BUSY_WAIT_S, rounds: int = BUSY_ROUNDS) -> fa.Post:
    """`post`, asked again after wait_s while Overpass stays busy (429, 502 to 504 but a timeout), up to `rounds`."""
    def ask(query: str) -> dict:
        for round_ in range(rounds):
            try:
                return post(query)
            except urllib.error.HTTPError as error:
                if error.code not in fa.BUSY_CODES or fa._is_timeout(error) or round_ == rounds - 1:
                    raise
            print(f"  still busy; asking again in {wait_s:.0f} s", flush=True)
            time.sleep(wait_s)
        raise RuntimeError("unreachable")
    return ask


def fetch(query_of: Callable[[Box], str], box: Box, n: int, parts: Path, post: fa.Post = fa.overpass_post) -> dict:
    """The merged answer of the box's n x n parts; each part's answers are kept in `parts` as they come."""
    parts.mkdir(parents=True, exist_ok=True)
    answers = []
    for k, part in enumerate(tiles(box, n), 1):
        kept = parts / f"{n}x{n}_{k}.json"
        if not kept.exists():
            print(f"  part {k} of {n * n}", flush=True)
            kept.write_text(json.dumps(ask_box(query_of, part, patient(post)), separators=(",", ":")), encoding="utf-8")
        answers += json.loads(kept.read_text(encoding="utf-8"))
    return fa.merge(answers)


def boxes(place: ii.Place) -> dict[str, Box]:
    rivers = be.expand(place.bbox, ii.MARGIN_KM * 1000 + be.CAP_M + be.LEVEL_RADIUS_M)
    return {"rivers": rivers, "drains": fi.fetch_box(place), "roads": fi.fetch_box(place)}


def target(place: ii.Place, layer: str) -> Path:
    if layer == "rivers":
        return RAW_SOURCES / "copernicus_glo30" / f"rivers_{place.name}.json"
    folder = {"drains": "osm_drains", "roads": "osm_roads"}[layer]
    return fi.raw_dir(place) / folder / f"{layer}_{place.name}.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("layers", nargs="*", choices=LAYERS, default=list(LAYERS))
    parser.add_argument("--area", choices=sorted(ii.PLACES), required=True)
    parser.add_argument("--tiles", type=int, default=3)
    args = parser.parse_args(argv)
    place = ii.PLACES[args.area]
    queries = {"rivers": rivers_query, "drains": drains_query, "roads": roads_query}
    for layer in args.layers or LAYERS:
        path = target(place, layer)
        if not path.exists():
            print(f"{layer}: asking Overpass in {args.tiles * args.tiles} parts", flush=True)
            parts = path.parent / f".{path.stem}.parts"
            answer = fetch(queries[layer], boxes(place)[layer], args.tiles, parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(answer, separators=(",", ":")), encoding="utf-8")
            shutil.rmtree(parts)
        answer = json.loads(path.read_text(encoding="utf-8"))
        stamp = (answer.get("osm3s") or {}).get("timestamp_osm_base")
        print(f"{path.name}: {path.stat().st_size} bytes, {len(answer['elements'])} elements, OSM data as of {stamp}")
        if layer != "rivers":
            note = (f"Overpass query, per part of the box cut {args.tiles} x {args.tiles} (tools/fetch_state_osm.py): "
                    f"{queries[layer](boxes(place)[layer])} OSM data as of {stamp}")
            fi.log_download(layer if layer == "drains" else "roads", fi.OVERPASS_URL, path, note, place)
    return 0


if __name__ == "__main__":
    sys.exit(main())
