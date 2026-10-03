"""One-off data build: public raw files -> small JSON the app serves.

Study area: Taman Sri Muda and the neighbouring sections of Shah Alam, Selangor.

Inputs (read only, in ../05_Raw_Data_Sources):
  - JRC global river flood depth v2.1 GeoTIFFs (CC BY 4.0)
  - shah_alam/overpass_sri_muda_*.json: OpenStreetMap businesses and roads, as fetched (ODbL)
  - shah_alam/pps.json, optional: flood relief centres from a source we can cite. Without it the
    app shows no shelters rather than guessing.

Run from 11_Platform_Draft:  .venv/bin/python tools/build_data.py
"""
from __future__ import annotations

import json
import math
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT.parent / "05_Raw_Data_Sources"
AREA = RAW / "shah_alam"
OUT = ROOT / "app" / "data"

RETURN_PERIODS = (10, 100, 500)
# (west, south, east, north): the box the OpenStreetMap files were fetched for
VIEW = (101.515, 3.008, 101.550, 3.042)
EATERIES = {"restaurant", "cafe", "fast_food", "food_court"}
NODATA_BELOW = -9998.0
VEHICLE_ROADS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "service", "living_street", "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
}
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(3.025))

Depths = dict[str, float | None]


class DepthRaster:
    """Reads single pixels from a sparse, deflate-tiled float32 GeoTIFF."""

    def __init__(self, path: Path) -> None:
        tags = Image.open(path).tag_v2
        self.tile = tags[322]
        self.across = -(-tags[256] // self.tile)
        self.offsets, self.counts = tags[324], tags[325]
        self.px = tags[33550][0]
        tie = tags[33922]
        self.x0, self.y0 = tie[3], tie[4]
        self.raw = path.read_bytes()

    @lru_cache(maxsize=64)
    def _tile(self, i: int) -> np.ndarray | None:
        if self.counts[i] == 0:
            return None
        chunk = self.raw[self.offsets[i]:self.offsets[i] + self.counts[i]]
        return np.frombuffer(zlib.decompress(chunk), "<f4").reshape(self.tile, self.tile)

    def cell(self, lon: float, lat: float) -> tuple[int, int]:
        return int((self.y0 - lat) / self.px), int((lon - self.x0) / self.px)

    def at_cell(self, row: int, col: int) -> float | None:
        tile = self._tile((row // self.tile) * self.across + col // self.tile)
        if tile is None:
            return None
        value = float(tile[row % self.tile, col % self.tile])
        return None if value <= NODATA_BELOW or value <= 0 else round(value, 2)

    def at(self, lon: float, lat: float) -> float | None:
        return self.at_cell(*self.cell(lon, lat))


def to_m(lon: float, lat: float) -> tuple[float, float]:
    """Flat local metres. Good to well under a metre across a 4 km area."""
    return lon * M_PER_DEG_LON, lat * M_PER_DEG_LAT


def to_lonlat(x: float, y: float) -> tuple[float, float]:
    return x / M_PER_DEG_LON, y / M_PER_DEG_LAT


def nearest_on_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[float, tuple[float, float]]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    q = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def load_roads() -> list[dict]:
    roads = []
    for way in json.loads((AREA / "overpass_sri_muda_roads.json").read_text())["elements"]:
        tags = way["tags"]
        if tags["highway"] in VEHICLE_ROADS and len(way["geometry"]) >= 2:
            roads.append({"name": tags.get("name"), "kind": tags["highway"],
                          "pts": [to_m(pt["lon"], pt["lat"]) for pt in way["geometry"]]})
    return roads


def load_businesses() -> list[dict]:
    """Shops, crafts, eateries and pharmacies. Banks, clinics and fuel stations in the fetch are left out."""
    rows = []
    for el in json.loads((AREA / "overpass_sri_muda_pois.json").read_text())["elements"]:
        tags = el["tags"]
        kind = tags.get("shop") or tags.get("craft") or tags.get("amenity")
        if not ("shop" in tags or "craft" in tags or kind in EATERIES | {"pharmacy"}):
            continue
        at = el if el["type"] == "node" else el["center"]
        rows.append({"id": f"{el['type']}-{el['id']}", "name": tags.get("name"), "kind": kind,
                     "sector": "eatery" if kind in EATERIES else "shop", "is_chain": "brand" in tags,
                     "lon": at["lon"], "lat": at["lat"], "edited": el["timestamp"][:10]})
    return rows


def load_shelters() -> list[dict]:
    path = AREA / "pps.json"
    return json.loads(path.read_text())["located"] if path.exists() else []


def nearest_road(p: tuple[float, float], roads: list[dict]) -> tuple[dict, float, tuple[float, float]]:
    best = None
    for road in roads:
        for a, b in zip(road["pts"], road["pts"][1:]):
            dist, q = nearest_on_segment(p, a, b)
            if best is None or dist < best[1]:
                best = (road, dist, q)
    assert best is not None, "no roads in the OSM extract"
    return best


def build() -> tuple[list[dict], dict]:
    rasters = {rp: DepthRaster(RAW / "jrc_glofas_v2_1" / f"ID211_N10_E100_RP{rp}_depth.tif") for rp in RETURN_PERIODS}
    assert rasters[10].x0 <= VIEW[0] and rasters[10].y0 >= VIEW[3], "the depth tile does not cover the study area"

    def depths(lon: float, lat: float) -> Depths:
        return {str(rp): rasters[rp].at(lon, lat) for rp in RETURN_PERIODS}

    roads = load_roads()
    shelters = load_shelters()

    premises = []
    for row in load_businesses():
        lon, lat = row["lon"], row["lat"]
        here = to_m(lon, lat)
        road, road_dist, road_pt = nearest_road(here, roads)
        shelter = min(shelters, key=lambda s: math.dist(here, to_m(s["lon"], s["lat"])), default=None)
        premises.append({
            "id": row["id"],
            "name": row["name"] or "Unnamed (no name on the map)",
            "sector": row["sector"], "kind": row["kind"], "is_chain": row["is_chain"],
            "lat": lat, "lon": lon,
            "map_last_edited": row["edited"],
            "depth_m": depths(lon, lat),
            "road": {"name": road["name"] or "a road with no name", "kind": road["kind"],
                     "distance_m": round(road_dist), "depth_m": depths(*to_lonlat(*road_pt))},
            "shelter": shelter and {"name": shelter["name"],
                                    "distance_m": round(math.dist(here, to_m(shelter["lon"], shelter["lat"])))},
        })
    premises.sort(key=lambda p: (p["sector"], p["name"]))

    ref = rasters[RETURN_PERIODS[0]]
    row_top, col_left = ref.cell(VIEW[0], VIEW[3])
    row_bot, col_right = ref.cell(VIEW[2], VIEW[1])
    cells = []
    for r in range(row_top, row_bot + 1):
        for c in range(col_left, col_right + 1):
            d = [rasters[rp].at_cell(r, c) for rp in RETURN_PERIODS]
            if any(d):
                cells.append([round(ref.y0 - (r + 1) * ref.px, 6), round(ref.x0 + c * ref.px, 6), *d])
    town = {
        "view": VIEW, "cell_deg": ref.px, "return_periods": RETURN_PERIODS,
        "cells": cells,  # [south, west, depth10, depth100, depth500]
        "shelters": [{"name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in shelters],
    }
    return premises, town


def main() -> None:
    premises, town = build()
    wet = {rp: sum(1 for p in premises if p["depth_m"][str(rp)]) for rp in RETURN_PERIODS}
    assert premises and len({p["id"] for p in premises}) == len(premises), "no businesses, or a repeated id"
    assert wet[10] <= wet[100] <= wet[500], wet   # a bigger flood never wets fewer shops
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "premises.json").write_text(json.dumps(premises, indent=1, ensure_ascii=False))
    (OUT / "town.json").write_text(json.dumps(town, separators=(",", ":")))
    print(f"{len(premises)} premises, {len(town['cells'])} flood cells, wet counts {wet}")


if __name__ == "__main__":
    main()
