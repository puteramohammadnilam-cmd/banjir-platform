"""Build the "low ground" map layer: land within 1, 2, 3 or 5 m of the level of the nearest mapped river, from the
height-above-river crop tools/build_elevation.py made (Copernicus GLO-30 and OpenStreetMap rivers). Standard library only.

    .venv/bin/python tools/build_lowground.py [--name shah-alam] [--dem DIR]

Run from 11_Platform_Draft. Reads {name}_above_river.tif in app/data/dem (or --dem) and writes beside it:
  {name}_lowground_{level}m.png   one indexed PNG per level (1, 2, 3 and 5 m) on the tif's own squares: a square at or
                                  below the level is shaded in one of four tones by how high it sits (index 1: up to
                                  1 m, the darkest; 2: over 1 to 2 m; 3: over 2 to 3 m; 4: over 3 to 5 m); a square
                                  above the level, and one with no data (beyond 3 km of a mapped river), is index 0,
                                  transparent
  {name}_lowground.json           the levels, the tones, the grid, bounds, sizes and SHA-256 of the PNGs, and the credit
and rewrites the "Low ground map layer" part at the end of SOURCES.txt there (everything before it is kept as it is).

Method: each square takes the LOWEST height above the river of the 3 x 3 squares around it (about 90 m; the window
app/elevation.py uses), since the satellite surface holds roofs and trees; a square with no data of its own stays
without shading. A square below the river's level (a negative
height) is in the lowest tone. Heights are compared as stored (0.1 m steps). The same input gives the same bytes.

What it is not: a flood forecast or a flood extent. It ignores banks, bunds, drains, pumps and how much water a river
can carry, and land that is not shaded can still flood from rain or blocked drains.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from array import array
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import raster  # noqa: E402
import build_ffpi as bf  # noqa: E402  (its OKLCH colours)
import grid_ops as go  # noqa: E402
import png_write  # noqa: E402

DEM_DIR = ROOT / "app" / "data" / "dem"
NAME = "shah-alam"
LEVELS = (1, 2, 3, 5)               # metres: one PNG each; a square at or below the level is shaded
TOP_EDGES = (1.0, 2.0, 3.0, 5.0)    # the tones' upper edges: index k + 1 covers (TOP_EDGES[k - 1], TOP_EDGES[k]]
EDGE_SLACK = 1e-4                   # stored float32 tenths (2.0 holds as 2.0, 1.9 as 1.8999...) stay on their side
TONES_OKLCH = ((0.38, 0.055, 175), (0.52, 0.06, 175), (0.66, 0.055, 175), (0.80, 0.045, 175))   # teal-grey, lowest first
CREDIT = "Ground height: Copernicus GLO-30; rivers © OpenStreetMap contributors"
SOURCES_HEADING = "Low ground map layer"


def tones() -> list[dict]:
    """The four tones, lowest ground (darkest) first, as the JSON and app/static/js/lowground.js give them."""
    lows = (None,) + TOP_EDGES[:-1]
    return [{"index": i + 1, "above_m": lows[i], "up_to_m": TOP_EDGES[i], "colour": bf.oklch_hex(*lch), "oklch": list(lch)}
            for i, lch in enumerate(TONES_OKLCH)]


def tone_of(height: float, level: float) -> int:
    """The PNG index of a square at `height` m above the river on the layer for `level`: 0 above the level or no data."""
    if height <= go.NODATA_BELOW or height > level + EDGE_SLACK:
        return 0
    return next(i + 1 for i, edge in enumerate(TOP_EDGES) if height <= edge + EDGE_SLACK)


def read_heights(path: Path) -> tuple[go.Grid, array]:
    """The tif's grid and its heights, row by row (no data as go.NODATA)."""
    crop = raster.DepthFile.open(path, path.stem)
    g = crop.grid
    keep = lambda v: v if raster.NODATA_BELOW < v < float("inf") else go.NODATA  # noqa: E731
    values = array("d", (crop.value_at(r, c, keep) for r in range(g.rows) for c in range(g.cols)))
    return go.Grid(g.x0, g.y0, g.px, g.py, g.rows, g.cols), values


def lowest_heights(heights: Sequence[float], grid: go.Grid) -> array:
    """Each square's lowest height in the 3 x 3 squares around it; no data where the square itself has none, so the
    shading stops where the crop's heights above a river do."""
    lowest = go.min_filter3(heights, grid.rows, grid.cols)
    return array("d", (go.NODATA if own <= go.NODATA_BELOW else low for own, low in zip(heights, lowest)))


def png_rows(grid: go.Grid, lowest: Sequence[float], level: float) -> list[list[int]]:
    indices = [tone_of(v, level) for v in lowest]
    return [indices[r * grid.cols:(r + 1) * grid.cols] for r in range(grid.rows)]


def write_pngs(out: Path, name: str, grid: go.Grid, lowest: Sequence[float]) -> list[Path]:
    palette = [(0, 0, 0)] + [tuple(int(t["colour"][k:k + 2], 16) for k in (1, 3, 5)) for t in tones()]
    alpha = {0: 0}
    return [png_write.write_indexed(out / f"{name}_lowground_{level}m.png", png_rows(grid, lowest, level), palette,
                                    alpha, depth=4) for level in LEVELS]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def doc_of(name: str, grid: go.Grid, source: Path, pngs: Sequence[Path]) -> dict:
    """{name}_lowground.json."""
    return {
        "version": 1, "area": name, "layer": "low_ground", "levels": list(LEVELS), "tones": tones(),
        "rule": "A square is shaded on a level's layer when the lowest height above the nearest mapped river of the "
                "3 x 3 squares around it is at or below that level; the tone says how high it sits.",
        "source": {"file": source.name, "bytes": source.stat().st_size, "sha256": sha256(source)},
        "files": {str(level): {"file": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
                  for level, p in zip(LEVELS, pngs)},
        "grid": {"west": grid.west, "north": grid.north, "px": grid.px, "py": grid.py, "rows": grid.rows,
                 "cols": grid.cols},
        "bounds": list(grid.bounds()),
        "png": {"width": grid.cols, "height": grid.rows, "transparent_index": 0,
                "masked": "Transparent above the level and beyond 3 km of a mapped river (no data)."},
        "credit": CREDIT,
        "not": "Not a flood forecast or extent: banks, bunds, drains and pumps are left out, and land that is not "
               "shaded can still flood from rain or drains.",
    }


def sources_part(doc: dict) -> str:
    lines = [SOURCES_HEADING, "=" * len(SOURCES_HEADING), "",
             "tools/build_lowground.py reads the above_river crop above and writes one indexed PNG per level (1, 2, 3",
             "and 5 m) on its squares, with a JSON of the levels, tones, bounds and these hashes. Each square takes the",
             "lowest height above the river of the 3 x 3 squares around it (about 90 m, as app/elevation.py does); a",
             "square at or below the level is shaded in four tones (up to 1 m darkest, then 1-2, 2-3 and 3-5 m), the",
             "rest and no data (beyond 3 km of a mapped river) are transparent. app/lowground.py serves them for the",
             "map. Not a flood forecast or extent: banks, bunds, drains and pumps are left out.",
             f"Source:    {doc['source']['file']}, SHA-256 {doc['source']['sha256']}",
             f"Credit:    {doc['credit']}", ""]
    for entry in doc["files"].values():
        lines += [f"File:     {entry['file']}", f"Bytes:    {entry['bytes']}", f"SHA-256:  {entry['sha256']}", ""]
    return "\n".join(lines)


def write_sources(out: Path, doc: dict) -> Path:
    """SOURCES.txt with its low ground part (re)written at the end; the text before that part is kept."""
    path = out / "SOURCES.txt"
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    kept = before.split("\n" + SOURCES_HEADING + "\n", 1)[0].rstrip("\n")
    path.write_text((kept + "\n\n" if kept else "") + sources_part(doc), encoding="utf-8")
    return path


def build(dem: Path, name: str = NAME) -> dict:
    """Write the PNGs, the JSON and SOURCES.txt's part; returns what the run made, for the report and the tests."""
    source = dem / f"{name}_above_river.tif"
    grid, heights = read_heights(source)
    lowest = lowest_heights(heights, grid)
    pngs = write_pngs(dem, name, grid, lowest)
    doc = doc_of(name, grid, source, pngs)
    json_path = dem / f"{name}_lowground.json"
    json_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"grid": grid, "lowest": lowest, "pngs": pngs, "json": json_path, "sources": write_sources(dem, doc)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default=NAME)
    parser.add_argument("--dem", type=Path, default=DEM_DIR)
    args = parser.parse_args(argv)
    found = build(args.dem, args.name)
    held = [v for v in found["lowest"] if v > go.NODATA_BELOW]
    for level, path in zip(LEVELS, found["pngs"]):
        shaded = sum(v <= level + EDGE_SLACK for v in held)
        print(f"{path.name}: {path.stat().st_size} bytes, {shaded} of {len(held)} squares with a river near shaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
