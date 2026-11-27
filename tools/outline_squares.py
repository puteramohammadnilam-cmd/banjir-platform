"""The river model's squares inside each of an area's outlines (a city's sections or a state's districts), counted and
drawn straight from the JRC flood depth files, row by row. Standard library only.

    .venv/bin/python tools/outline_squares.py --sections FILE --out DIR [--rasters DIR] [--counts-only]

Fast enough for a whole state: Johor's box holds about 5 million squares, while app/raster.py view_cells reads at
most 100,000 at once and tools/area_sections.py's square-by-square test is far too slow there. For each outline, in the
order tools/sections_io.py gives:
  counts    cells (every 90 m square whose centre is in the outline, wet or dry: the denominator of the wet share) and
            wet_cells {"10", "20", "50"} (water at that flood size, app/raster.py depth_value's rule)
  pictures  one indexed PNG per flood size and theme, {id}_rp{rp}_{light|dark}.png, on the depth grid's own squares and
            cut to the outline: a square of the outline with water takes the map's depth step (the squares' colours in
            app/static/js/map-gl-data.js depthRamp: under 0.5 m, 0.5 to 1, 1 to 2, 2 to 3, 3 m and over), everything
            else is transparent
and DIR/flood_pictures.json: each outline's bounds, size, counts and the files' bytes and SHA-256.

A square belongs to the first outline, in that order, that holds its centre, as in tools/area_sections.py. Inside is
decided along the row's centre latitude by app/geo.py's ray rule (an edge counts when it spans the latitude by the
half-open rule; a centre counts when an odd number of edges cross east of it), so a centre exactly on an outline's edge
can fall on either side, where app/geo.py counts it inside; real outlines' vertices never sit on square centres.
ponytail: the even-odd rule runs over every ring of an outline at once, which is right for holes and for the separate
parts of a MultiPolygon; parts that overlap each other would cancel out (OSM boundaries have none).

The pictures are on a lat/lon grid; the map stretches each between its corners, which near the equator stays within
about 20 m of true across a district (a square is 90 m). The same input gives the same bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import geo, raster  # noqa: E402
import png_write  # noqa: E402
import sections_io  # noqa: E402

RPS = tuple(str(rp) for rp in raster.RETURN_PERIODS)
STEPS_M = (0.5, 1, 2, 3)   # depthRamp's stops after 0: index 1 is under 0.5 m, 5 is 3 m and over
PALETTES = {               # depthRamp's colours, shallow first (tests/test_outline_squares.py holds them equal)
    "light": ("#a9d8ff", "#6cb8f0", "#2f86d6", "#1d5fae", "#0b3478"),
    "dark": ("#1a6aa8", "#2f9be0", "#62c3f5", "#a8e2ff", "#e6f7ff"),
}
CACHE_TILES = 256          # tiles kept while walking: a row of tiles across a state, for all three flood sizes
CREDIT = "Water: European Commission JRC global river flood hazard maps v2.1, CC BY 4.0."

Span = tuple[int, int]     # columns from the first up to, not including, the second
Edge = tuple[float, float, float, float]


def depth_class(metres: float) -> int:
    """The picture index of a wet square: 1 under 0.5 m up to 5 at 3 m and over, depthRamp's steps."""
    return 1 + sum(metres >= step for step in STEPS_M)


def _centre_y(grid: raster.Grid, row: int) -> float:
    return grid.y0 - (row + 0.5) * grid.py   # as Grid.centre works it out


def _centre_x(grid: raster.Grid, col: int) -> float:
    return grid.x0 + (col + 0.5) * grid.px


def edge_rows(geometry: dict, grid: raster.Grid) -> dict[int, list[Edge]]:
    """Each row of `grid` whose centre latitude an edge of the geometry spans (half-open, as geo._ray_inside), with the
    edges that span it."""
    rows: dict[int, list[Edge]] = defaultdict(list)
    for polygon in geo.polygons_of(geometry):
        for ring in polygon:
            for (x1, y1), (x2, y2) in zip((p[:2] for p in ring), (p[:2] for p in ring[1:])):
                if y1 == y2:
                    continue
                low, high = min(y1, y2), max(y1, y2)
                first = max(0, math.floor((grid.y0 - high) / grid.py - 0.5))
                last = min(grid.rows - 1, math.floor((grid.y0 - low) / grid.py - 0.5) + 1)
                for row in range(first, last + 1):
                    if (y1 > _centre_y(grid, row)) != (y2 > _centre_y(grid, row)):
                        rows[row].append((x1, y1, x2, y2))
    return rows


def _first_col(grid: raster.Grid, x: float) -> int:
    """The first column whose centre is at or east of x, kept to 0 to grid.cols."""
    col = min(grid.cols, max(0, math.ceil((x - grid.x0) / grid.px - 0.5)))
    while col > 0 and _centre_x(grid, col - 1) >= x:
        col -= 1
    while col < grid.cols and _centre_x(grid, col) < x:
        col += 1
    return col


def row_spans(edges: Sequence[Edge], grid: raster.Grid, row: int) -> list[Span]:
    """The columns of one row whose centres are inside, from the edges spanning that row's centre latitude."""
    y = _centre_y(grid, row)
    xs = sorted((x2 - x1) * (y - y1) / (y2 - y1) + x1 for x1, y1, x2, y2 in edges)   # geo._ray_inside's crossing
    if len(xs) % 2:
        raise ValueError(f"row {row}: an odd number of edge crossings; is every ring closed?")
    spans = [(_first_col(grid, xs[k]), _first_col(grid, xs[k + 1])) for k in range(0, len(xs), 2)]
    return [(a, b) for a, b in spans if a < b]


def subtract(spans: Sequence[Span], taken: Sequence[Span]) -> list[Span]:
    """The parts of `spans` outside `taken` (both sorted, neither overlapping itself)."""
    out = []
    for a, b in spans:
        for t_a, t_b in taken:
            if t_b <= a or t_a >= b:
                continue
            if t_a > a:
                out.append((a, t_a))
            a = max(a, t_b)
            if a >= b:
                break
        if a < b:
            out.append((a, b))
    return out


def _merge(spans: Sequence[Span]) -> list[Span]:
    merged: list[Span] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def claim(outlines: Sequence[dict], grid: raster.Grid) -> list[dict[int, list[Span]]]:
    """Per outline, {row: spans} of the squares whose centre it holds, a square going to the first outline that does."""
    edges = [edge_rows(outline["geometry"], grid) for outline in outlines]
    claimed: list[dict[int, list[Span]]] = [{} for _ in outlines]
    for row in sorted({row for found in edges for row in found}):
        taken: list[Span] = []
        for i, found in enumerate(edges):
            spans = subtract(row_spans(found.get(row, ()), grid, row), taken)
            if spans:
                claimed[i][row] = spans
                taken = _merge([*taken, *spans])
    return claimed


def _one_grid(depth_set: raster.DepthSet, outlines: Sequence[dict]) -> tuple[raster.Grid, tuple[raster.DepthFile, ...]]:
    """The loaded grid holding every outline's box, and its files in RPS order; ValueError when there is none."""
    corners = [(box[0], box[3]) for box in (o["bbox"] for o in outlines)] + [(o["bbox"][2], o["bbox"][1]) for o in outlines]
    found = {depth_set.locate(*corner)[0] if depth_set.locate(*corner) else None for corner in corners}
    if len(found) != 1 or None in found:
        raise ValueError("the outlines are not all inside one loaded depth grid")
    grid = found.pop()
    return grid, next(files for files in depth_set.layers if files[0].grid is grid)


def scan(depth_set: raster.DepthSet, outlines: Sequence[dict], pictures: bool = True) -> list[dict]:
    """Per outline: {id, name, counts {cells, wet_cells}, extent (top, left, bottom, right squares, inclusive; None when
    it holds no square) and, with `pictures`, classes {rp: bytearray of depth classes, row by row over the extent}}."""
    grid, files = _one_grid(depth_set, outlines)
    found = []
    for outline, rows in zip(outlines, claim(outlines, grid)):
        cols = [c for spans in rows.values() for span in spans for c in (span[0], span[1] - 1)]
        extent = (min(rows), min(cols), max(rows), max(cols)) if rows else None
        width = extent[3] - extent[1] + 1 if extent else 0
        classes = {rp: bytearray(width * (extent[2] - extent[0] + 1)) for rp in RPS} if pictures and extent else {}
        wet = dict.fromkeys(RPS, 0)
        for row, spans in rows.items():
            for a, b in spans:
                for rp, depth_file in zip(RPS, files):
                    for first, values in depth_file.row_runs(row, a, b):
                        for k, value in enumerate(values):
                            metres = raster.depth_value(value)
                            if metres:
                                wet[rp] += 1
                                if classes:
                                    classes[rp][(row - extent[0]) * width + first + k - extent[1]] = depth_class(metres)
        cells = sum(b - a for spans in rows.values() for a, b in spans)
        found.append({"id": outline["id"], "name": outline["name"], "counts": {"cells": cells, "wet_cells": wet},
                      "extent": extent, "classes": classes})
    return found


def _rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[k:k + 2], 16) for k in (1, 3, 5))


def _file_entry(path: Path) -> dict:
    data = path.read_bytes()
    return {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write_pictures(out: Path, scanned: Sequence[dict], grid: raster.Grid) -> dict:
    """The PNGs and flood_pictures.json (see the module docstring); returns the JSON's content."""
    out.mkdir(parents=True, exist_ok=True)
    rows_out = []
    for item in scanned:
        entry = {"id": item["id"], "name": item["name"], "counts": item["counts"], "bounds": None, "width": 0,
                 "height": 0, "files": {}}
        if item["extent"]:
            top, left, bottom, right = item["extent"]
            width = right - left + 1
            entry.update(width=width, height=bottom - top + 1, bounds=[
                round(grid.x0 + left * grid.px, 7), round(grid.y0 - (bottom + 1) * grid.py, 7),
                round(grid.x0 + (right + 1) * grid.px, 7), round(grid.y0 - top * grid.py, 7)])
            for rp, classes in item["classes"].items():
                rows = [classes[r * width:(r + 1) * width] for r in range(entry["height"])]
                entry["files"][rp] = {theme: _file_entry(png_write.write_indexed(
                    out / f"{item['id']}_rp{rp}_{theme}.png", rows, [(0, 0, 0), *map(_rgb, colours)], {0: 0}, depth=8))
                    for theme, colours in PALETTES.items()}
        rows_out.append(entry)
    doc = {"version": 1, "grid": grid.name, "px": grid.px, "py": grid.py, "steps_m": list(STEPS_M),
           "palettes": {theme: list(colours) for theme, colours in PALETTES.items()},
           "rule": "A square is drawn in the first outline that holds its centre, when the river model gives it water; "
                   "the colour is the map's depth step.", "credit": CREDIT, "outlines": rows_out}
    (out / "flood_pictures.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sections", type=Path, required=True, help="the outlines' GeoJSON (tools/sections_io.py)")
    parser.add_argument("--out", type=Path, required=True, help="the folder for the pictures and flood_pictures.json")
    parser.add_argument("--rasters", type=Path, help="folder of JRC depth files (default app/data/rasters)")
    parser.add_argument("--counts-only", action="store_true", help="print the counts and write nothing")
    args = parser.parse_args(argv)
    depth_set = raster.DepthSet.load(args.rasters or raster.raster_dir(), cache_tiles=CACHE_TILES)
    outlines = sections_io.load_sections(args.sections)
    scanned = scan(depth_set, outlines, pictures=not args.counts_only)
    if not args.counts_only:
        write_pictures(args.out, scanned, _one_grid(depth_set, outlines)[0])
    for item in scanned:
        print(f"{item['id']}: {item['counts']['cells']} squares, wet {item['counts']['wet_cells']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
