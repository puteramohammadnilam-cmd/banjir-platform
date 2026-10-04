"""Per-section figures for an area built with sections: sections.json beside its premises.json and town.json.

    .venv/bin/python tools/area_sections.py --area-dir app/data/areas/shah-alam \\
        [--sections ../05_Raw_Data_Sources/shah_alam/mbsa_sections/sections.geojson] [--rasters DIR]

Run from 11_Platform_Draft after tools/build_area.py --sections. For each section, in natural order (1 to 36, then U1
to U20), sections.json holds:
  id, name, number_label, bbox [west, south, east, north], zoom (a starting zoom that fits the section in about
  1,000 px), area_km2, counts, and outline: the section's geometry simplified to within 10 m (app/geo.py) with
  coordinates rounded to 5 decimals (about 1 m).
  counts: businesses, cells (every 90 m square of the depth grid whose centre is in the section, wet or dry: the
  denominator of the wet share), wet_businesses and wet_cells {"10", "20", "50"} (water at that flood size).
A square belongs to the first section, in natural order, that holds its centre (an edge counts as inside); squares
outside every section are left out of the section and city counts and only reported. Businesses take the section
build_area gave them. "city" holds the same counts summed over the sections.

The build stops, naming the problem, if a business has no known section, if the sections' business counts do not add
up to premises.json, or if a bigger flood wets fewer businesses or squares than a smaller one anywhere.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import geo, raster  # noqa: E402
import sections_io  # noqa: E402

RPS = tuple(str(rp) for rp in raster.RETURN_PERIODS)
OUTLINE_TOLERANCE_M = 10.0
OUTLINE_DECIMALS = 5
MAP_FIT_PX = 1000
TILE_PX = 256
MIN_ZOOM, MAX_ZOOM = 12, 17


def section_zoom(box: Sequence[float]) -> int:
    """The largest web-map zoom at which the box's wider side fits in MAP_FIT_PX pixels, kept to 12 to 17."""
    span = max(box[2] - box[0], box[3] - box[1])
    zoom = math.floor(math.log2(MAP_FIT_PX * 360 / (TILE_PX * span)))
    return max(MIN_ZOOM, min(MAX_ZOOM, zoom))


def outline(geometry: dict) -> dict:
    """The geometry simplified to within OUTLINE_TOLERANCE_M, coordinates rounded to OUTLINE_DECIMALS."""
    simple = geo.simplify_geometry(geometry, OUTLINE_TOLERANCE_M)
    polygons = [[[[round(x, OUTLINE_DECIMALS), round(y, OUTLINE_DECIMALS)] for x, y in ring] for ring in polygon]
                for polygon in geo.polygons_of(simple)]
    return {"type": "Polygon", "coordinates": polygons[0]} if simple["type"] == "Polygon" else \
        {"type": "MultiPolygon", "coordinates": polygons}


def _zero() -> dict:
    return {"businesses": 0, "cells": 0, "wet_businesses": dict.fromkeys(RPS, 0), "wet_cells": dict.fromkeys(RPS, 0)}


def square_counts(town: dict, sections: list[dict], depth_set: raster.DepthSet) -> tuple[dict, dict]:
    """({section id: counts with cells and wet_cells filled}, {"cells", "wet_cells"} of squares outside every section),
    over the squares of town["view"] exactly as view_cells walks them."""
    west, south, east, north = town["view"]
    grid, top, left = depth_set.locate(west, north)
    _, bottom, right = depth_set.locate(east, south)
    wet = {}
    for cell in town["cells"]:
        _, row, col = depth_set.locate(cell[1] + grid.px / 2, cell[0] + grid.py / 2)
        wet[(row, col)] = cell[2:]
    found = {s["id"]: _zero() for s in sections}
    outside = {"cells": 0, "wet_cells": dict.fromkeys(RPS, 0)}
    for row in range(top, bottom + 1):
        for col in range(left, right + 1):
            home = geo.containing(*grid.centre(row, col), sections)
            counts = found[home["id"]] if home else outside
            counts["cells"] += 1
            for rp, depth in zip(RPS, wet.get((row, col), ())):
                counts["wet_cells"][rp] += 1 if depth else 0
    return found, outside


def add_businesses(found: dict, premises: list[dict]) -> None:
    """Count each business in its section; a business with no section, or an unknown one, stops the build."""
    stray = [p["id"] for p in premises if p.get("section") not in found]
    if stray:
        raise ValueError(f"{len(stray)} businesses have no known section: {', '.join(stray[:20])}")
    for p in premises:
        counts = found[p["section"]]
        counts["businesses"] += 1
        for rp in RPS:
            counts["wet_businesses"][rp] += 1 if p["depth_m"][rp] else 0


def city_counts(per_section: list[dict]) -> dict:
    total = _zero()
    for counts in per_section:
        total["businesses"] += counts["businesses"]
        total["cells"] += counts["cells"]
        for rp in RPS:
            total["wet_businesses"][rp] += counts["wet_businesses"][rp]
            total["wet_cells"][rp] += counts["wet_cells"][rp]
    return total


def check(result: dict, premises: list[dict]) -> None:
    """Refuse business counts that do not add up, or a bigger flood that wets less, in the city or any section."""
    if result["city"]["businesses"] != len(premises):
        raise ValueError(f"the sections hold {result['city']['businesses']} businesses, premises.json {len(premises)}")
    for name, counts in [("city", result["city"]), *((s["id"], s["counts"]) for s in result["sections"])]:
        for key in ("wet_businesses", "wet_cells"):
            values = [counts[key][rp] for rp in RPS]
            if values != sorted(values):
                raise ValueError(f"{name}: a bigger flood wets fewer {key.split('_')[1]}: {values}")


def build(premises: list[dict], town: dict, sections: list[dict], depth_set: raster.DepthSet) -> dict:
    """The sections.json content (see the module docstring)."""
    found, outside = square_counts(town, sections, depth_set)
    add_businesses(found, premises)
    rows = [{"id": s["id"], "name": s["name"], "number_label": s["number_label"],
             "bbox": [round(v, 6) for v in s["bbox"]], "zoom": section_zoom(s["bbox"]), "area_km2": s["area_km2"],
             "counts": found[s["id"]], "outline": outline(s["geometry"])} for s in sections]
    result = {"outline_tolerance_m": OUTLINE_TOLERANCE_M, "city": city_counts([r["counts"] for r in rows]),
              "outside_sections": outside, "sections": rows}
    check(result, premises)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--area-dir", required=True, type=Path, help="the folder holding premises.json and town.json")
    parser.add_argument("--sections", type=Path, help="sections.geojson (default: the raw MBSA sections file)")
    parser.add_argument("--rasters", type=Path, help="folder of JRC depth files (default app/data/rasters)")
    args = parser.parse_args(argv)
    premises = json.loads((args.area_dir / "premises.json").read_text(encoding="utf-8"))
    town = json.loads((args.area_dir / "town.json").read_text(encoding="utf-8"))
    depth_set = raster.DepthSet.load(args.rasters) if args.rasters else raster.depth_set()
    result = build(premises, town, sections_io.load_sections(args.sections), depth_set)
    (args.area_dir / "sections.json").write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False),
                                                 encoding="utf-8")
    city, outside = result["city"], result["outside_sections"]
    print(f"{len(result['sections'])} sections: {city['businesses']} businesses, {city['cells']} squares, wet "
          f"businesses {city['wet_businesses']}, wet squares {city['wet_cells']}; outside every section "
          f"{outside['cells']} squares, {outside['wet_cells']} wet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
