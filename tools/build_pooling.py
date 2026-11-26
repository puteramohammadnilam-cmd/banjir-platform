"""Build one area's "Rain pools" layer: where heavy rain collects when the drains cannot take it, from FABDEM bare-earth
heights (buildings and trees removed) and the OpenStreetMap drains, with the model in app/pooling_model.py.

    .venv/bin/python tools/build_pooling.py --name shah-alam --bbox 101.43 2.95 101.59 3.23 \\
        --zip ../05_Raw_Data_Sources/fabdem/N00E100-N10E110_FABDEM_V1-2.zip \\
        --drains ../05_Raw_Data_Sources/shah_alam/indexes/osm_drains/drains_shah-alam.json

Run from 11_Platform_Draft; needs numpy and tifffile (requirements-dev.txt). It works on the box plus MARGIN_KM on each
side, so water from just outside the box is counted, and writes the box only, into app/data/pooling/ (CC BY-NC-SA 4.0,
as FABDEM is; README there):
  {name}_ground.tif         FABDEM height (m above the EGM2008 geoid), as FABDEM gives it
  {name}_drains.tif         1 where the model lowered the ground by BURN_M (a mapped waterway), else 0
  {name}_down.tif           the neighbour (0-7, NEIGHBOURS order) each square overflows to; -1 where it leaves the box
  {name}_pool_{mm}.tif      standing water (m) after {mm} of rain in an hour; no data where none is shown
  {name}_pool_{mm}.png      the same in three classes (CLASSES), for the map
  {name}_pooling.json       grid, storms, assumptions, classes, credit
Each .tif is float32 in the tiled layout app/raster.py reads (tools/geotiff_write.py), no data -9999.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from app import pooling_model as pm  # noqa: E402
import geotiff_write  # noqa: E402
import png_write  # noqa: E402

OUT = ROOT / "app" / "data" / "pooling"
STORMS_MM = (40, 70, 100)    # rain in one hour
MARGIN_KM = 2.0
BURN_M = 1.0                 # mapped drains, ditches, streams, canals and rivers are lowered this much
M_PER_DEG_LAT = 110_574
M_PER_DEG_LON = 111_320
NODATA = -9999.0
OUT_TILE = 256
# standing water classes: (index, up to m, colour); index 0 is no water (transparent). Violet-blue, apart from the
# river squares' blue, flash potential's orange, low ground's teal and the score's orchid.
CLASSES = ((1, 0.3, "#a9b4ff"), (2, 1.0, "#6c6ff0"), (3, None, "#3a2aa8"))
CREDIT = ("Rain pools: our screening model on FABDEM V1-2 (Hawker and others 2022, University of Bristol, CC BY-NC-SA "
          "4.0; from Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 "
          "provided under COPERNICUS by the European Union and ESA) and OpenStreetMap drains (ODbL)")


def tile_name(lat: int, lon: int) -> str:
    return f"N{lat:02d}E{lon:03d}"


def read_tile(archive: zipfile.ZipFile, lat: int, lon: int) -> tuple[np.ndarray, float, float, float, float]:
    """(heights, west, north, px, py) of the 1 x 1 degree tile whose south-west corner is (lat, lon)."""
    name = next((n for n in archive.namelist() if tile_name(lat, lon) in n and n.endswith(".tif")), None)
    if name is None:
        raise SystemExit(f"{tile_name(lat, lon)} is not in the zip")
    with tifffile.TiffFile(io.BytesIO(archive.read(name))) as tif:
        page = tif.pages[0]
        values = page.asarray().astype(float)
        scale = page.tags["ModelPixelScaleTag"].value
        tie = page.tags["ModelTiepointTag"].value
        keys = page.tags["GeoKeyDirectoryTag"].value
    point = any(keys[i] == 1025 and keys[i + 3] == 2 for i in range(4, len(keys), 4))   # RasterPixelIsPoint
    px, py = scale[0], scale[1]
    west, north = tie[3] - (px / 2 if point else 0), tie[4] + (py / 2 if point else 0)
    values[values <= NODATA + 1] = np.nan
    return values, west, north, px, py


def mosaic(archive: zipfile.ZipFile, box) -> tuple[np.ndarray, float, float, float, float]:
    west, south, east, north = box
    lats = range(math.floor(south), math.floor(north) + 1)
    lons = range(math.floor(west), math.floor(east) + 1)
    rows = []
    for lat in reversed(lats):
        parts = [read_tile(archive, lat, lon) for lon in lons]
        rows.append(np.hstack([p[0] for p in parts]))
    first = read_tile(archive, max(lats), min(lons))
    return np.vstack(rows), first[1], first[2], first[3], first[4]


def expand(box, km: float):
    west, south, east, north = box
    dlat = km * 1000 / M_PER_DEG_LAT
    dlon = km * 1000 / (M_PER_DEG_LON * math.cos(math.radians((south + north) / 2)))
    return west - dlon, south - dlat, east + dlon, north + dlat


def window(box, west0: float, north0: float, px: float, py: float) -> tuple[int, int, int, int]:
    """(top, left, rows, cols) of the squares whose centres lie in the box."""
    west, south, east, north = box
    left = math.ceil((west - west0) / px - 0.5)
    right = math.floor((east - west0) / px - 0.5)
    top = math.ceil((north0 - north) / py - 0.5)
    bottom = math.floor((north0 - south) / py - 0.5)
    return top, left, bottom - top + 1, right - left + 1


def burn(ground: np.ndarray, drains_path: Path, west: float, north: float, px: float, py: float) -> np.ndarray:
    """Lower the squares under every mapped waterway by BURN_M; the mask of those squares."""
    answer = json.loads(drains_path.read_text(encoding="utf-8"))
    rows, cols = ground.shape
    mask = np.zeros_like(ground, dtype=bool)
    for way in answer.get("elements", []):
        points = [(p["lon"], p["lat"]) for p in way.get("geometry", []) if p]
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            steps = max(1, int(max(abs(x1 - x0) / px, abs(y1 - y0) / py) * 2))
            for k in range(steps + 1):
                x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
                r, c = int((north - y) / py), int((x - west) / px)
                if 0 <= r < rows and 0 <= c < cols:
                    mask[r, c] = True
    ground[mask] -= BURN_M
    return mask


def codes(down: np.ndarray, shape: tuple[int, int], inner: tuple[int, int, int, int]) -> np.ndarray:
    """The inner window's overflow directions as NEIGHBOURS indices; -1 where it leaves the inner window."""
    rows, cols = shape
    top, left, n_rows, n_cols = inner
    out = np.full((n_rows, n_cols), -1.0)
    for r in range(n_rows):
        for c in range(n_cols):
            to = down[(top + r) * cols + left + c]
            if to < 0:
                continue
            tr, tc = divmod(int(to), cols)
            dr, dc = tr - (top + r), tc - (left + c)
            if 0 <= tr - top < n_rows and 0 <= tc - left < n_cols:
                out[r, c] = pm.NEIGHBOURS.index((dr, dc))
    return out


def classed(depth: np.ndarray) -> list[list[int]]:
    index = np.zeros(depth.shape, dtype=int)
    for k, upto, _ in reversed(CLASSES):
        index = np.where(np.isfinite(depth) & ((depth < upto) if upto else True), k, index)
    index[~np.isfinite(depth)] = 0
    return index.tolist()


def hex_rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def write(name: str, values: np.ndarray, origin, pixel) -> None:
    rows = np.where(np.isfinite(values), values, NODATA).astype(np.float32).tolist()
    geotiff_write.write_tiff(OUT / name, rows, tile=OUT_TILE, origin=origin, pixel=pixel, padding=NODATA)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--drains", type=Path)
    args = parser.parse_args()
    box, wide = tuple(args.bbox), expand(tuple(args.bbox), MARGIN_KM)
    with zipfile.ZipFile(args.zip) as archive:
        heights, west0, north0, px, py = mosaic(archive, wide)
    top, left, rows, cols = window(wide, west0, north0, px, py)
    ground = heights[top:top + rows, left:left + cols].copy()
    bare = ground.copy()
    gwest, gnorth = west0 + left * px, north0 - top * py
    mask = burn(ground, args.drains, gwest, gnorth, px, py) if args.drains else np.zeros_like(ground, dtype=bool)
    burned = int(mask.sum())
    lat_mid = gnorth - rows * py / 2
    spacing = (py * M_PER_DEG_LAT, px * M_PER_DEG_LON * math.cos(math.radians(lat_mid)))
    print(f"grid {rows} x {cols} squares of {spacing[0]:.1f} x {spacing[1]:.1f} m; {burned} squares under drains lowered")
    prepared = pm.prepare(ground, spacing)
    print(f"{len(prepared[2].cells)} dips of {pm.MIN_DIP_M} m or more")
    itop, ileft, irows, icols = window(box, gwest, gnorth, px, py)
    inner = (itop, ileft, irows, icols)
    origin, pixel = (gwest + ileft * px, gnorth - itop * py), (px, py)
    cut = lambda a: a[itop:itop + irows, ileft:ileft + icols]
    OUT.mkdir(parents=True, exist_ok=True)
    write(f"{args.name}_ground.tif", cut(bare), origin, pixel)
    write(f"{args.name}_drains.tif", cut(mask.astype(float)), origin, pixel)
    write(f"{args.name}_down.tif", codes(prepared[1], ground.shape, inner), origin, pixel)
    palette = [(0, 0, 0)] + [hex_rgb(colour) for _, _, colour in CLASSES]
    summary = {}
    for storm in STORMS_MM:
        depth = cut(pm.ponding(ground, storm, spacing, prepared=prepared))
        write(f"{args.name}_pool_{storm}.tif", depth, origin, pixel)
        png_write.write_indexed(OUT / f"{args.name}_pool_{storm}.png", classed(depth), palette, {0: 0})
        wet = np.isfinite(depth)
        summary[f"{storm}mm"] = {"squares": int(wet.sum()), "share": round(float(wet.mean()), 4),
                               "deepest_m": round(float(np.nanmax(depth)), 2) if wet.any() else 0}
        print(f"{storm} mm: {wet.sum()} squares ({wet.mean():.1%}) with standing water")
    bounds = [origin[0], origin[1] - irows * py, origin[0] + icols * px, origin[1]]
    meta = {"version": 1, "area": args.name, "layer": "rain_pools", "storms_mm": list(STORMS_MM),
            "bounds": [round(b, 6) for b in bounds], "rows": irows, "cols": icols,
            "drains_mm": pm.DRAINS_MM, "runoff": pm.RUNOFF, "min_dip_m": pm.MIN_DIP_M, "min_depth_m": pm.MIN_DEPTH_M,
            "burn_m": BURN_M, "classes": [{"index": k, "up_to_m": upto, "colour": colour} for k, upto, colour in CLASSES],
            "summary": summary, "licence": "CC BY-NC-SA 4.0", "credit": CREDIT}
    (OUT / f"{args.name}_pooling.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
