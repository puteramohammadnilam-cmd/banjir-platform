"""Bake the 3D flood mock-up's data for one shop: the buildings around it from OpenStreetMap and the flood model's
squares, into app/static/flood3d/<place id>.json for app/static/3d.html.

    .venv/bin/python tools/build_flood3d.py [--area shah-alam] [--place node-5565878632] [--radius-m 450]

Run from 11_Platform_Draft. One Overpass question (fetch_area_osm's polite overpass_post): the building ways in a box
--radius-m around the shop, `out geom`. Each building keeps its outline and a height: OSM's `height`, else
`building:levels` floors, else a guess from its kind (marked guessed, so the page can say so). The building the shop
stands in (or the nearest within NEAR_M) is marked as the shop's. The squares are town.json's cells inside the box
that hold water, each with its depth per flood size (0 = dry); each building takes the depths of the square under its
middle, so the page can draw its walls wet up to the water line.

ponytail: one shop baked by hand for the mock-up; buildings drawn as OSM ways only (multipolygon relations left out).
Upgrade path: an /api/flood3d/<place> answer built the same way, cached per place.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_area_osm import QUERY_TIMEOUT_S, overpass_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AREAS = ROOT / "app" / "data" / "areas"
OUT_DIR = ROOT / "app" / "static" / "flood3d"
DEFAULT_PLACE = "node-5565878632"   # a 7-Eleven in a busy shop row, wet in all three flood sizes
DEFAULT_RADIUS_M = 450
NEAR_M = 30                         # a shop mapped as a dot just outside its building's outline still finds it
FLOOR_M = 3.2                       # one storey, floor to floor
GUESS_FLOORS = {"house": 2, "terrace": 2, "detached": 2, "semidetached_house": 2, "residential": 2, "bungalow": 1,
                "commercial": 3, "retail": 3, "office": 4, "apartments": 8, "industrial": 2, "warehouse": 2,
                "mosque": 2, "school": 3, "roof": 1, "shed": 1, "garage": 1}
DEFAULT_FLOORS = 2
METRES_PER_DEG = 111_320.0
CREDIT = "Buildings © OpenStreetMap contributors (ODbL) · flood depth: JRC v2.1 (CC BY 4.0)"


def box_around(lat: float, lon: float, metres: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) of a square box `metres` out from the point on each side."""
    dlat = metres / METRES_PER_DEG
    dlon = metres / (METRES_PER_DEG * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def height_of(tags: dict) -> tuple[float, bool]:
    """A building's height in metres and whether it was guessed (no `height` or `building:levels` in OSM)."""
    for key, scale in (("height", 1.0), ("building:levels", FLOOR_M)):
        try:
            value = float(str(tags.get(key, "")).replace("m", "").strip())
        except ValueError:
            continue
        if value > 0:
            return round(value * scale, 1), False
    return round(GUESS_FLOORS.get(tags.get("building"), DEFAULT_FLOORS) * FLOOR_M, 1), True


def contains(ring: list[list[float]], lon: float, lat: float) -> bool:
    """Ray casting: whether (lon, lat) falls inside the closed ring of [lon, lat] points."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def metres_to_ring(ring: list[list[float]], lon: float, lat: float) -> float:
    """Metres from (lon, lat) to the nearest wall of the ring, on a flat local grid (fine over tens of metres)."""
    x_scale = METRES_PER_DEG * math.cos(math.radians(lat))
    points = [((x - lon) * x_scale, (y - lat) * METRES_PER_DEG) for x, y in ring]
    nearest = math.inf
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        share = 0.0 if length2 == 0 else max(0.0, min(1.0, -(x1 * (x2 - x1) + y1 * (y2 - y1)) / length2))
        nearest = min(nearest, math.hypot(x1 + share * (x2 - x1), y1 + share * (y2 - y1)))
    return nearest


def shop_building(rings: list[list[list[float]]], lat: float, lon: float) -> int | None:
    """Index of the ring the shop stands in, else of the ring with a wall nearest the shop within NEAR_M, else None."""
    for i, ring in enumerate(rings):
        if contains(ring, lon, lat):
            return i
    nearest = min(((metres_to_ring(ring, lon, lat), i) for i, ring in enumerate(rings)), default=None)
    return nearest[1] if nearest and nearest[0] <= NEAR_M else None


def buildings(answer: dict, lat: float, lon: float) -> list[dict]:
    """GeoJSON features for the closed building ways in an Overpass `out geom` answer."""
    ways = [e for e in answer.get("elements", []) if e.get("type") == "way" and len(e.get("geometry", [])) >= 4]
    rings = [[[round(p["lon"], 7), round(p["lat"], 7)] for p in way["geometry"]] for way in ways]
    shop = shop_building(rings, lat, lon)
    features = []
    for i, (way, ring) in enumerate(zip(ways, rings)):
        if ring[0] != ring[-1]:
            continue
        height, guessed = height_of(way.get("tags", {}))
        features.append({"type": "Feature", "id": way["id"],
                         "properties": {"h": height, "guessed": guessed, "shop": i == shop},
                         "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return features


def squares(town: dict, box: tuple[float, float, float, float]) -> list[dict]:
    """GeoJSON squares for the flood model's cells in the box that hold water in at least one flood size."""
    south, west, north, east = box
    size = town["cell_deg"]
    keys = [f"d{rp}" for rp in town["return_periods"]]
    features = []
    for cell_south, cell_west, *depths in town["cells"]:
        if not (south - size < cell_south < north and west - size < cell_west < east) or not any(depths):
            continue
        n, e = round(cell_south + size, 7), round(cell_west + size, 7)
        ring = [[cell_west, cell_south], [e, cell_south], [e, n], [cell_west, n], [cell_west, cell_south]]
        props = {key: depth or 0 for key, depth in zip(keys, depths)}
        features.append({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return features


def with_depths(building: dict, water: list[dict], keys: list[str]) -> dict:
    """The building with the depths of the square under its middle (0 where the model has no water), so the page can
    draw each building's walls wet up to the water line."""
    ring = building["geometry"]["coordinates"][0][:-1]
    lon, lat = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    square = next((w for w in water if contains(w["geometry"]["coordinates"][0], lon, lat)), None)
    depths = {key: square["properties"][key] if square else 0 for key in keys}
    return {**building, "properties": {**building["properties"], **depths}}


def bake(area: str, place_id: str, radius_m: float, post=overpass_post) -> dict:
    premises = json.loads((AREAS / area / "premises.json").read_text())
    shop = next((p for p in premises if p["id"] == place_id), None)
    if shop is None:
        raise SystemExit(f"no place {place_id!r} in {area}")
    box = box_around(shop["lat"], shop["lon"], radius_m)
    south, west, north, east = box
    query = f"[out:json][timeout:{QUERY_TIMEOUT_S}];way[building]({south},{west},{north},{east});out geom;"
    town = json.loads((AREAS / area / "town.json").read_text())
    sections = json.loads((AREAS / area / "sections.json").read_text())["sections"]
    section_name = next((s["name"] for s in sections if s["id"] == shop["section"]), "")
    water = squares(town, box)
    keys = [f"d{rp}" for rp in town["return_periods"]]
    houses = [with_depths(b, water, keys) for b in buildings(post(query), shop["lat"], shop["lon"])]
    return {
        "place": {**{key: shop[key] for key in ("id", "name", "kind", "sector", "section", "lat", "lon", "depth_m")},
                  "section_name": section_name},
        "flood_sizes": [str(rp) for rp in town["return_periods"]],
        "buildings": {"type": "FeatureCollection", "features": houses},
        "water": {"type": "FeatureCollection", "features": water},
        "credit": CREDIT,
        "fetched_on": date.today().isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--area", default="shah-alam")
    args.add_argument("--place", default=DEFAULT_PLACE)
    args.add_argument("--radius-m", type=float, default=DEFAULT_RADIUS_M)
    opts = args.parse_args(argv)
    baked = bake(opts.area, opts.place, opts.radius_m)
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{opts.place}.json"
    out.write_text(json.dumps(baked, separators=(",", ":")))
    found = baked["buildings"]["features"]
    print(f"{out.relative_to(ROOT)}: {len(found)} buildings ({sum(f['properties']['guessed'] for f in found)} heights "
          f"guessed, shop building {'found' if any(f['properties']['shop'] for f in found) else 'NOT found'}), "
          f"{len(baked['water']['features'])} wet squares")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
