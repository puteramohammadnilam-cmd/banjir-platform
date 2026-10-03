"""Build one area's data: public raw files -> the small JSON the app serves (plan card A9, replaces build_data.py).

    .venv/bin/python tools/build_area.py --area kuala-krai --view 102.185 5.513 102.22 5.547 \\
        --pois ../05_Raw_Data_Sources/kuala_krai/overpass_kuala_krai_pois.json \\
        --roads ../05_Raw_Data_Sources/kuala_krai/overpass_kuala_krai_roads.json [--shelters pps.json]

Run from 11_Platform_Draft. It writes premises.json and town.json into app/data/areas/{area} (or --out). The folder's
area.json is written by hand and must hold the same view.

Inputs, read only:
  - the JRC flood depth GeoTIFFs in app/data/rasters (or BANJIR_RASTER_DIR, or --rasters), read by app/raster.py (CC BY 4.0)
  - --pois and --roads: OpenStreetMap businesses and roads from the Overpass API, as fetched (ODbL). Shops, crafts,
    eateries and pharmacies are kept; banks, clinics and fuel stations in a fetch are left out.
  - --shelters, optional: JSON {"located": [{name, lat, lon}]} of flood relief centres from a source we can cite.
    Without it the app shows no shelters rather than guessing.

Local metres use the view's centre latitude for the length of a degree of longitude.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import areas, raster  # noqa: E402

RETURN_PERIODS = raster.RETURN_PERIODS
EATERIES = {"restaurant", "cafe", "fast_food", "food_court"}
VEHICLE_ROADS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "service", "living_street", "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
}
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON_EQUATOR = 111320.0
UNNAMED_BUSINESS = "Unnamed (no name on the map)"
UNNAMED_ROAD = "a road with no name"

Point = tuple[float, float]
View = tuple[float, float, float, float]   # west, south, east, north


@dataclass(frozen=True)
class Projection:
    """Flat local metres. Good to well under a metre across a view a few kilometres wide."""

    m_per_deg_lon: float

    @classmethod
    def for_view(cls, view: Sequence[float]) -> Projection:
        """The length of a degree of longitude at the latitude of the view's centre."""
        centre_lat = (view[1] + view[3]) / 2
        return cls(M_PER_DEG_LON_EQUATOR * math.cos(math.radians(centre_lat)))

    def to_m(self, lon: float, lat: float) -> Point:
        return lon * self.m_per_deg_lon, lat * M_PER_DEG_LAT

    def to_lonlat(self, x: float, y: float) -> Point:
        return x / self.m_per_deg_lon, y / M_PER_DEG_LAT


def _elements(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["elements"]


def nearest_on_segment(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    q = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def load_roads(path: Path, proj: Projection) -> list[dict]:
    """Roads a vehicle can use, each as {name, kind, pts} with points in local metres."""
    roads = []
    for way in _elements(path):
        tags = way["tags"]
        if tags["highway"] in VEHICLE_ROADS and len(way["geometry"]) >= 2:
            roads.append({"name": tags.get("name"), "kind": tags["highway"],
                          "pts": [proj.to_m(pt["lon"], pt["lat"]) for pt in way["geometry"]]})
    return roads


def load_businesses(path: Path) -> list[dict]:
    """Shops, crafts, eateries and pharmacies. Banks, clinics and fuel stations in the fetch are left out."""
    rows = []
    for el in _elements(path):
        tags = el["tags"]
        kind = tags.get("shop") or tags.get("craft") or tags.get("amenity")
        if not ("shop" in tags or "craft" in tags or kind in EATERIES | {"pharmacy"}):
            continue
        at = el if el["type"] == "node" else el["center"]
        rows.append({"id": f"{el['type']}-{el['id']}", "name": tags.get("name"), "kind": kind,
                     "sector": "eatery" if kind in EATERIES else "shop", "is_chain": "brand" in tags,
                     "lon": at["lon"], "lat": at["lat"], "edited": el["timestamp"][:10]})
    return rows


def load_shelters(path: Path | None) -> list[dict]:
    """Relief centres from the "located" list of a file; none when there is no file."""
    if path is None or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))["located"]


def nearest_road(p: Point, roads: list[dict]) -> tuple[dict, float, Point]:
    """(the road, metres to it, the nearest point on it) for a point in local metres."""
    best = None
    for road in roads:
        for a, b in zip(road["pts"], road["pts"][1:]):
            dist, q = nearest_on_segment(p, a, b)
            if best is None or dist < best[1]:
                best = (road, dist, q)
    if best is None:
        raise ValueError("no roads in the OSM extract")
    return best


def _premise(row: dict, proj: Projection, roads: list[dict], shelters: list[dict], depth_set: raster.DepthSet) -> dict:
    def depths(lon: float, lat: float) -> dict:
        found = depth_set.depths(lon, lat)
        if found is None:
            raise ValueError(f"{row['id']} at {lat}, {lon} is outside the loaded depth rasters")
        return found

    here = proj.to_m(row["lon"], row["lat"])
    road, road_dist, road_pt = nearest_road(here, roads)
    shelter = min(shelters, key=lambda s: math.dist(here, proj.to_m(s["lon"], s["lat"])), default=None)
    return {
        "id": row["id"],
        "name": row["name"] or UNNAMED_BUSINESS,
        "sector": row["sector"], "kind": row["kind"], "is_chain": row["is_chain"],
        "lat": row["lat"], "lon": row["lon"],
        "map_last_edited": row["edited"],
        "depth_m": depths(row["lon"], row["lat"]),
        "road": {"name": road["name"] or UNNAMED_ROAD, "kind": road["kind"],
                 "distance_m": round(road_dist), "depth_m": depths(*proj.to_lonlat(*road_pt))},
        "shelter": shelter and {"name": shelter["name"],
                                "distance_m": round(math.dist(here, proj.to_m(shelter["lon"], shelter["lat"])))},
    }


def check_premises(premises: list[dict]) -> None:
    """Refuse an empty list, a repeated id, or a bigger flood that wets fewer businesses than a smaller one."""
    if not premises:
        raise ValueError("no businesses in the OSM extract")
    if len({p["id"] for p in premises}) != len(premises):
        raise ValueError("a business id is repeated")
    wet = [sum(1 for p in premises if p["depth_m"][str(rp)]) for rp in RETURN_PERIODS]
    if wet != sorted(wet):
        raise ValueError(f"a bigger flood wets fewer businesses: wet counts {wet}")


def build(view: View, businesses: list[dict], roads: list[dict], shelters: list[dict],
          depth_set: raster.DepthSet) -> tuple[list[dict], dict]:
    """(premises, town) for one area: the view's wet squares first, so a view the rasters do not cover fails fast."""
    cells = depth_set.view_cells(view)
    proj = Projection.for_view(view)
    premises = [_premise(row, proj, roads, shelters, depth_set) for row in businesses]
    premises.sort(key=lambda p: (p["sector"], p["name"]))
    check_premises(premises)
    grid = depth_set.locate(view[0], view[3])[0]
    town = {
        "view": view, "cell_deg": grid.px, "return_periods": RETURN_PERIODS,
        "cells": cells,  # [south, west, depth10, depth100, depth500]
        "shelters": [{"name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in shelters],
    }
    return premises, town


def write_area(out: Path, premises: list[dict], town: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "premises.json").write_text(json.dumps(premises, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "town.json").write_text(json.dumps(town, separators=(",", ":")), encoding="utf-8")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build one area's premises.json and town.json.")
    parser.add_argument("--area", required=True, help="the area id, the folder name under app/data/areas")
    parser.add_argument("--view", required=True, nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--pois", required=True, type=Path, help="Overpass answer: businesses")
    parser.add_argument("--roads", required=True, type=Path, help="Overpass answer: roads, with geometry")
    parser.add_argument("--shelters", type=Path, help='JSON {"located": [{name, lat, lon}]}')
    parser.add_argument("--out", type=Path, help="output folder (default app/data/areas/AREA)")
    parser.add_argument("--rasters", type=Path, help="folder of JRC depth files (default app/data/rasters)")
    args = parser.parse_args(argv)
    west, south, east, north = args.view
    if not (west < east and south < north):
        parser.error("--view must have west below east and south below north")
    if not areas.AREA_ID.fullmatch(args.area):
        parser.error("--area must be lower-case letters, digits and single hyphens")
    return args


def check_inputs(args: argparse.Namespace, out: Path) -> None:
    """Stop with a plain message for a missing input, or an area.json whose view is not the one given."""
    for flag, path in (("--pois", args.pois), ("--roads", args.roads), ("--shelters", args.shelters)):
        if path is not None and not path.is_file():
            raise SystemExit(f"{flag} file not found: {path}")
    config = out / "area.json"
    if not config.is_file():
        print(f"note: {config} does not exist yet; write it by hand before the app can load this area")
    elif json.loads(config.read_text(encoding="utf-8")).get("view") != list(args.view):
        raise SystemExit(f"{config} holds a different view from --view; make them the same first")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.out or areas.AREAS_DIR / args.area
    check_inputs(args, out)
    depth_set = raster.DepthSet.load(args.rasters) if args.rasters else raster.depth_set()
    if not depth_set.grids:
        raise SystemExit(f"no depth rasters (JRC ID..._RP10_depth.tif and friends) in {depth_set.folder}")
    view = tuple(args.view)
    proj = Projection.for_view(view)
    premises, town = build(view, load_businesses(args.pois), load_roads(args.roads, proj),
                           load_shelters(args.shelters), depth_set)
    write_area(out, premises, town)
    wet = {rp: sum(1 for p in premises if p["depth_m"][str(rp)]) for rp in RETURN_PERIODS}
    print(f"{len(premises)} premises, {len(town['cells'])} flood cells, wet counts {wet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
