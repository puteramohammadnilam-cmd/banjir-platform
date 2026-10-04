"""Re-sample an area built on the old flood sizes (1 in 10, 100, 500) at the new ones, when its OpenStreetMap inputs
were not kept, so tools/build_area.py cannot rebuild it (Kota Tinggi, plan WS-A).

    .venv/bin/python tools/resample_area.py --area kota-tinggi \\
        --old-rasters ../05_Raw_Data_Sources/jrc_glofas_v2_1

Run from 11_Platform_Draft. It reads premises.json and town.json from app/data/areas/{area} (or --from) and writes them
back (or into --out), changing only the depths:
  - each business's depth_m: read again at its lat/lon, as the build does;
  - town.json cells: the view's wet squares, as the build does, and return_periods;
  - each road's depth_m: the old build kept the road's name, kind, distance and depths, not the point on the road. That
    point lies within distance_m of the business, so its square's centre lies within distance_m + ROAD_SLACK_M. Of those
    squares, the ones whose depths in the old files are exactly the stored old depths are the candidates. When they all
    give the same depths at the new sizes those are used; when none matches, or they disagree, it stops and names the
    business, rather than guess.

It first checks that the old files are the ones the area was built from: every business's old depths and the town's
squares must come out of them exactly. Nothing is written unless every business passes.
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
sys.path.insert(0, str(ROOT / "tools"))
from app import areas, raster  # noqa: E402
import build_area as ba  # noqa: E402

OLD_PERIODS = (10, 100, 500)
ROAD_SLACK_M = 90   # a square is about 92 m a side, so its centre is at most about 65 m from any point in it

Depths = dict[str, float | None]


class ResampleError(ValueError):
    """An area this tool will not re-sample, or a business it cannot re-sample without guessing."""


def load_old(folder: str | Path) -> raster.DepthSet:
    """The JRC files of the old sizes in a folder, as a DepthSet whose files are in OLD_PERIODS order. Use old_depths
    and view_cells on it: its depths() would label them with the new sizes."""
    root = Path(folder).absolute()
    found: dict[str, dict[int, Path]] = {}
    for path in sorted(root.glob("*.tif")):
        match = raster.FILE_NAME.match(path.name)
        if match and int(match["rp"]) in OLD_PERIODS:
            found.setdefault(match["grid"], {})[int(match["rp"])] = path
    cache = raster.TileCache()
    layers = []
    for name in sorted(found):
        missing = [str(rp) for rp in OLD_PERIODS if rp not in found[name]]
        if missing:
            raise raster.RasterError(f"grid {name}: no old file for return period {', '.join(missing)} in {root}")
        layers.append(tuple(raster.DepthFile.open(found[name][rp], name, cache) for rp in OLD_PERIODS))
    return raster.DepthSet(str(root), tuple(layers), "old", cache)


def _files_at(depth_set: raster.DepthSet, lon: float, lat: float):
    """(the grid's files, row, col) of the square holding a point, or None."""
    found = depth_set.locate(lon, lat)
    if found is None:
        return None
    grid, row, col = found
    return next(files for files in depth_set.layers if files[0].grid is grid), row, col


def _layer(depth_set: raster.DepthSet, grid: raster.Grid) -> tuple[raster.DepthFile, ...]:
    """The files of the set's grid laid out exactly as `grid`, which another set opened."""
    for files in depth_set.layers:
        if files[0].grid == grid:
            return files
    raise ResampleError(f"grid {grid.name} is not loaded at the new sizes")


def old_depths(old_set: raster.DepthSet, lon: float, lat: float) -> Depths | None:
    """{"10": m, "100": m, "500": m} at a point from the old files, as the old build stored them."""
    found = _files_at(old_set, lon, lat)
    if found is None:
        return None
    files, row, col = found
    return {str(rp): f.at_cell(row, col) for rp, f in zip(OLD_PERIODS, files)}


def _candidates(premise: dict, view: Sequence[float], old_set: raster.DepthSet) -> tuple[raster.Grid, list]:
    """The grid, and the squares within reach of the business whose old depths are the road's stored ones."""
    proj = ba.Projection.for_view(view)
    here = proj.to_m(premise["lon"], premise["lat"])
    reach = premise["road"]["distance_m"] + ROAD_SLACK_M
    files, row, col = _files_at(old_set, premise["lon"], premise["lat"])
    grid = files[0].grid
    rows = math.ceil(reach / (grid.py * ba.M_PER_DEG_LAT)) + 1
    cols = math.ceil(reach / (grid.px * proj.m_per_deg_lon)) + 1
    want = [premise["road"]["depth_m"][str(rp)] for rp in OLD_PERIODS]
    found = [(r, c) for r in range(row - rows, row + rows + 1) for c in range(col - cols, col + cols + 1)
             if grid.has(r, c) and math.dist(here, proj.to_m(*grid.centre(r, c))) <= reach
             and [f.at_cell(r, c) for f in files] == want]
    return grid, found


def road_depths(premise: dict, view: Sequence[float], old_set: raster.DepthSet, new_set: raster.DepthSet) -> Depths:
    """The road's depths at the new sizes, from the squares its stored old depths and distance allow."""
    grid, found = _candidates(premise, view, old_set)
    if not found:
        raise ResampleError(f"{premise['id']}: no square within {premise['road']['distance_m'] + ROAD_SLACK_M} m has "
                            f"the old road depths {premise['road']['depth_m']}")
    files = _layer(new_set, grid)
    answers = {tuple(f.at_cell(r, c) for f in files) for r, c in found}
    if len(answers) != 1:
        raise ResampleError(f"{premise['id']}: the road is ambiguous: squares {found} share the old road depths but "
                            f"differ at the new sizes {sorted(answers, key=str)}")
    return dict(zip((str(rp) for rp in raster.RETURN_PERIODS), answers.pop()))


def resample_premise(premise: dict, view: Sequence[float], old_set: raster.DepthSet,
                     new_set: raster.DepthSet) -> dict:
    """The business with its own and its road's depths at the new sizes; every other field as it was."""
    if old_depths(old_set, premise["lon"], premise["lat"]) != premise["depth_m"]:
        raise ResampleError(f"{premise['id']}: the old files do not give the depths it was built with; use the old "
                            "files the area was built from")
    depth = new_set.depths(premise["lon"], premise["lat"])
    if depth is None:
        raise ResampleError(f"{premise['id']} is outside the loaded depth rasters")
    road = {**premise["road"], "depth_m": road_depths(premise, view, old_set, new_set)}
    return {**premise, "depth_m": depth, "road": road}


def resample(premises: list[dict], town: dict, old_set: raster.DepthSet,
             new_set: raster.DepthSet) -> tuple[list[dict], dict]:
    """(premises, town) at the new sizes, in the same order and with the same fields."""
    if town.get("return_periods") != list(OLD_PERIODS):
        raise ResampleError(f"town.json is already on return periods {town.get('return_periods')}")
    if old_set.view_cells(town["view"]) != town["cells"]:
        raise ResampleError("town.json: the old files do not give its squares; use the old files the area was built "
                            "from")
    done = [resample_premise(p, town["view"], old_set, new_set) for p in premises]
    ba.check_premises(done)
    return done, {**town, "return_periods": raster.RETURN_PERIODS, "cells": new_set.view_cells(town["view"])}


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-sample one built area at the new flood sizes.")
    parser.add_argument("--area", required=True, help="the area id, the folder name under app/data/areas")
    parser.add_argument("--old-rasters", required=True, type=Path,
                        help="folder holding the JRC files for 1 in 10, 100 and 500 years the area was built from")
    parser.add_argument("--from", dest="source", type=Path, help="folder of the built area (default app/data/areas/AREA)")
    parser.add_argument("--out", type=Path, help="output folder (default: the --from folder)")
    parser.add_argument("--rasters", type=Path, help="folder of JRC depth files at the new sizes (default app/data/rasters)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = args.source or areas.AREAS_DIR / args.area
    premises = json.loads((source / "premises.json").read_text(encoding="utf-8"))
    town = json.loads((source / "town.json").read_text(encoding="utf-8"))
    new_set = raster.DepthSet.load(args.rasters) if args.rasters else raster.depth_set()
    done, new_town = resample(premises, town, load_old(args.old_rasters), new_set)
    ba.write_area(args.out or source, done, new_town)
    wet = {rp: sum(1 for p in done if p["depth_m"][str(rp)]) for rp in raster.RETURN_PERIODS}
    print(f"{len(done)} premises, {len(new_town['cells'])} flood cells, wet counts {wet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
