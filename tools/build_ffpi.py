"""Build the Shah Alam Flash Flood Potential Index (FFPI): a 1 to 10 rating of each 30 m square's susceptibility to
flash floods, after Smith (2003) as used by Mohd Yassin et al. (2023, Planning Malaysia 21(2)) for Shah Alam.

    .venv/bin/python tools/build_ffpi.py [--raw DIR] [--out DIR] [--qa]

Run from 11_Platform_Draft after tools/fetch_indexes.py. Reads only saved files (index_inputs.py) and writes, in
app/data/indexes (or --out):
  shah-alam_ffpi.tif    float32 scores 1.0 to 10.0 in 0.1 steps, no data -9999 (permanent water, or no input), on the
                        grid of app/data/dem (1 arc second, the city box plus 2 km), in the layout app/raster.py reads;
                        every value is read back through app/raster.py and the build stops unless each matches
  shah-alam_ffpi.png    the four classes as an indexed PNG on the same squares, transparent outside the city outline,
                        over permanent water and on no data, for the map
  shah-alam_ffpi.json   classes, breaks, legend colours, grid, bounds, credit and the method in words
  SOURCES.txt           inputs (with SHA-256) and outputs
With --qa the four factor ratings are also written as GeoTIFFs to <raw>/indexes/built/ (not committed).

Method (each factor rated 1 to 10 with Table 2 of Mohd Yassin et al. 2023; Scenario 2 of their Table 3):
  FFPI = (1.5 M + L + S + 0.5 V) / 4, rounded half up to 0.1.
  M slope: Horn's slope of the GLO-30 surface after taking the lowest height of the 3 x 3 squares around each square
    (about 90 m, the window app/elevation.py uses for ground height), which drops most roofs and trees. Rating k covers
    slopes above 3(k - 1) % up to 3k %; 27 to 30 %, which the table leaves out, continues the steps and rates 10.
  L land cover: ESA WorldCover 2021 10 m pixels counted into each square by pixel centre. A square more than half
    permanent water is no data. The table's land uses are the US NLCD's, whose developed classes go by impervious share:
    so a square at least a fifth built-up rates 8 (20-49 %), 9 (50-79 %) or 10 (80 % and over) by its built-up share;
    under a fifth, each pixel rates by its class (built-up as developed open space, 7) and the square takes the mean.
  S soil: SoilGrids 2.0 sand, silt and clay, the 0-5 and 5-15 cm layers weighted by thickness (0-15 cm), in a USDA
    texture class, rated by the table (silty clay, which it leaves out, as clay). SoilGrids has no value under towns:
    at such a square the built-up share counts as impervious (10) and the rest takes the nearest SoilGrids value.
  V vegetation: fractional cover from the WorldCover 2021 NDVI composite's median band, ((NDVI - 0.2) / (0.86 - 0.2))
    squared, kept to 0..1 (Carlson & Ripley 1997), averaged over the square's 10 m pixels; 90-100 % rates 1, each 10 %
    less one more, under 10 % rates 10. 0.86 sits near the top of the grid's own values (99.5th percentile 0.848).
  Classes: equal steps of the 1-10 scale, as the paper names four levels but not their limits: low below 3.25, medium
    from 3.25, high from 5.5, extreme from 7.75 (a score on a break goes up).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import raster  # noqa: E402
import build_elevation as be  # noqa: E402
import geotiff_write  # noqa: E402
import grid_ops as go  # noqa: E402
import index_inputs as ii  # noqa: E402
import png_write  # noqa: E402
import ffpi_text  # noqa: E402

OUT_DIR = ROOT / "app" / "data" / "indexes"
CLASSES = ("low", "medium", "high", "extreme")
BREAKS = (3.25, 5.5, 7.75)
SCALE = (1, 10)
DECIMALS = 1
WEIGHTS = (1.5, 1.0, 1.0, 0.5)          # M, L, S, V
DIVISOR = 4
LEGEND_OKLCH = ((0.91, 0.045, 50), (0.80, 0.10, 50), (0.67, 0.145, 50), (0.52, 0.135, 50))
GAMUT_SLACK = 1e-4
TILE = 256
SLOPE_STEP = 3.0                         # percent per rating step
BUILT, WATER = 50, 80
WATER_MAJORITY = 0.5
LAND_RATINGS = {10: 3, 20: 5, 30: 6, 40: 6, 50: None, 60: 7, 70: 7, 80: 1, 90: 2, 95: 2, 100: 7}
DEVELOPED = ((0.8, 10), (0.5, 9), (0.2, 8))   # built-up share at or above -> rating, as NLCD's high, medium, low
OPEN_DEVELOPED = 7
TEXTURES = ("sand", "loamy sand", "sandy loam", "loam", "silt loam", "silt", "sandy clay loam", "clay loam",
            "silty clay loam", "sandy clay", "silty clay", "clay")
SOIL_RATINGS = {"sand": 2, "sandy loam": 3, "silt loam": 4, "loamy sand": 4, "silt": 5, "loam": 6,
                "sandy clay loam": 7, "silty clay loam": 7, "clay loam": 8, "sandy clay": 8, "clay": 9,
                "silty clay": 9}
IMPERVIOUS = 10
NDVI_BARE, NDVI_FULL = 0.2, 0.86


class BuildError(Exception):
    """Input or output this tool will not accept, said in plain words."""


# --- ratings ---

def slope_rating(percent: float) -> int:
    return min(10, max(1, math.ceil(percent / SLOPE_STEP)))


def land_rating(counts: dict[int, int]) -> float | None:
    """The square's L from its WorldCover pixel counts; None when it has none or is mostly permanent water."""
    total = sum(counts.values())
    if total == 0 or counts.get(WATER, 0) / total > WATER_MAJORITY:
        return None
    built = counts.get(BUILT, 0) / total
    for share, rating in DEVELOPED:
        if built >= share:
            return float(rating)
    return sum((OPEN_DEVELOPED if k == BUILT else LAND_RATINGS[k]) * n for k, n in counts.items()) / total


def texture_class(sand: float, silt: float, clay: float) -> str:
    """The USDA soil texture class of a sand, silt and clay mix in percent (the NRCS triangle's rules)."""
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52) or (clay < 7 and silt < 50):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and sand <= 45:
        return "clay loam" if sand > 20 else "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    return "silty clay" if silt >= 40 else "clay"


def vegetation_rating(cover: float) -> int:
    return max(1, 10 - math.floor(100 * cover / 10))


def ffpi(m: float, l: float, s: float, v: float) -> float:
    return (WEIGHTS[0] * m + WEIGHTS[1] * l + WEIGHTS[2] * s + WEIGHTS[3] * v) / DIVISOR


def round_score(score: float) -> float:
    """Half up to 0.1 (the 1e-9 keeps 6.35, stored as 6.3499..., going up)."""
    return math.floor(score * 10 + 0.5 + 1e-9) / 10


def class_of(score: float, breaks: Sequence[float] = BREAKS, classes: Sequence[str] = CLASSES) -> str:
    return classes[sum(score >= b for b in breaks)]


# --- colours ---

def oklch_hex(lightness: float, chroma: float, hue: float) -> str:
    """#rrggbb of an OKLCH colour (Ottosson's OKLab), refused when outside the sRGB gamut."""
    a, b = chroma * math.cos(math.radians(hue)), chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
              -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
              -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)
    if any(not -GAMUT_SLACK <= c <= 1 + GAMUT_SLACK for c in linear):
        raise ValueError(f"oklch({lightness} {chroma} {hue}) is outside the sRGB gamut")
    encode = [min(1.0, max(0.0, c)) for c in linear]
    encode = [12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in encode]
    return "#" + "".join(f"{round(c * 255):02x}" for c in encode)


def legend() -> list[dict]:
    return [{"class": name, "colour": oklch_hex(*lch), "oklch": list(lch)} for name, lch in zip(CLASSES, LEGEND_OKLCH)]


# --- factor grids ---

@dataclass(frozen=True)
class Factors:
    """The four ratings per square, NODATA where a factor has none."""

    m: array
    l: array
    s: array
    v: array


@dataclass(frozen=True)
class Layers:
    """What both index tools take from the inputs, on the grid."""

    grid: go.Grid
    ground: array             # metres: the lowest surface height of the 3 x 3 squares
    slope: array              # percent, from `ground`
    cover: dict               # WorldCover class -> pixel count per square
    built: array              # built-up share per square (0 to 1), NODATA without cover
    land: array               # L, NODATA on permanent water or without cover
    vegetation: ii.Vegetation


def load_layers(raw: Path) -> Layers:
    grid = ii.grid_window()
    ground = go.min_filter3(ii.load_surface(grid), grid.rows, grid.cols)
    slope = go.slope_percent(ground, grid.rows, grid.cols, *grid.metres())
    cover = ii.load_worldcover(grid, raw)
    built, land = array("d", [go.NODATA]) * grid.size, array("d", [go.NODATA]) * grid.size
    for i in range(grid.size):
        counts = {k: cover[k][i] for k in cover if cover[k][i]}
        total = sum(counts.values())
        if total:
            built[i] = counts.get(BUILT, 0) / total
        rating = land_rating(counts)
        land[i] = go.NODATA if rating is None else rating
    vegetation = ii.load_vegetation(grid, raw, NDVI_BARE, NDVI_FULL)
    return Layers(grid, ground, slope, cover, built, land, vegetation)


def soil_ratings(soil: ii.Soil) -> tuple[array, array]:
    """(rating, nearest held rating) on the SoilGrids grid: the texture's rating where SoilGrids has a value, and for
    every pixel the rating of the nearest pixel with one (itself where it has one)."""
    _, north, spx, spy, cols = soil.src
    rows = len(soil.held) // cols
    rating = array("d", (SOIL_RATINGS[texture_class(a, b, c)] if h else go.NODATA
                         for a, b, c, h in zip(soil.sand, soil.silt, soil.clay, soil.held)))
    lat = math.radians(north - rows * spy / 2)
    dx, dy = spx * go.M_PER_DEG_LON_AT_EQUATOR * math.cos(lat), spy * go.M_PER_DEG_LAT
    nearest = be.nearest_river((i for i, h in enumerate(soil.held) if h), rows, cols, dx, dy, math.inf)
    if any(n < 0 for n in nearest):
        raise BuildError("SoilGrids has no value anywhere near the grid")
    return rating, array("d", (rating[n] for n in nearest))


def soil_layer(grid: go.Grid, soil: ii.Soil, built: Sequence[float]) -> array:
    """S per square: the SoilGrids pixel at its centre; at a gap, the built-up share as impervious (10) and the rest
    as the nearest SoilGrids value."""
    rating, nearest = soil_ratings(soil)
    here = go.sample_nearest(grid, rating, soil.src)
    near = go.sample_nearest(grid, nearest, soil.src)
    out = array("d", [go.NODATA]) * grid.size
    for i in range(grid.size):
        if here[i] > go.NODATA_BELOW:
            out[i] = here[i]
        elif near[i] > go.NODATA_BELOW:
            share = built[i] if built[i] > go.NODATA_BELOW else 0.0
            out[i] = share * IMPERVIOUS + (1 - share) * near[i]
    return out


def factors(layers: Layers, soil: ii.Soil) -> Factors:
    m = array("d", (slope_rating(s) if s > go.NODATA_BELOW else go.NODATA for s in layers.slope))
    v = array("d", (vegetation_rating(c) if c > go.NODATA_BELOW else go.NODATA for c in layers.vegetation.cover))
    return Factors(m, layers.land, soil_layer(layers.grid, soil, layers.built), v)


def scores(f: Factors) -> array:
    """The rounded score per square; NODATA where any factor has none."""
    return array("d", (round_score(ffpi(m, l, s, v)) if min(m, l, s, v) > go.NODATA_BELOW else go.NODATA
                       for m, l, s, v in zip(f.m, f.l, f.s, f.v)))


# --- outputs ---

def rows_of(values: Sequence[float], grid: go.Grid) -> list[list[float]]:
    return [list(values[r * grid.cols:(r + 1) * grid.cols]) for r in range(grid.rows)]


def write_tif(path: Path, grid: go.Grid, values: Sequence[float]) -> tuple[Path, str]:
    """Write float32 values, read every one back through app/raster.py and refuse unless each is byte for byte what
    was written. Returns the path and the file's SHA-256."""
    rows = rows_of(values, grid)
    geotiff_write.write_tiff(path, rows, tile=TILE, origin=(grid.west, grid.north), pixel=(grid.px, grid.py),
                             padding=go.NODATA, level=9)
    opened = raster.DepthFile.open(path, path.stem)
    for r, row in enumerate(rows):
        read = struct.pack(f"<{len(row)}f", *(opened.value_at(r, c, float) for c in range(len(row))))
        if read != struct.pack(f"<{len(row)}f", *row):
            raise BuildError(f"{path.name}: row {r} reads back differently from what was written")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def write_png(path: Path, grid: go.Grid, values: Sequence[float], shown: Sequence[int]) -> Path:
    """Class indices 1..4 where `shown` and the value is a score, else 0 (transparent)."""
    stored = [struct.unpack("<f", struct.pack("<f", v))[0] for v in values]   # as the tif holds them
    indices = [1 + CLASSES.index(class_of(v)) if shown[i] and v > go.NODATA_BELOW else 0
               for i, v in enumerate(stored)]
    palette = [(0, 0, 0)] + [tuple(int(c["colour"][k:k + 2], 16) for k in (1, 3, 5)) for c in legend()]
    alpha = {0: 0, **{i: 255 for i in range(1, len(palette))}}
    return png_write.write_indexed(path, [indices[r * grid.cols:(r + 1) * grid.cols] for r in range(grid.rows)],
                                   palette, alpha, depth=4)


def ffpi_doc(grid: go.Grid) -> dict:
    """shah-alam_ffpi.json (tests/fixtures/index_contract.json, ffpi_json)."""
    return {
        "version": 1, "area": ii.NAME, "index": "ffpi",
        "scale": {"min": SCALE[0], "max": SCALE[1], "decimals": DECIMALS},
        "classes": list(CLASSES), "breaks": list(BREAKS),
        "break_rule": "A score at or above a break belongs to the class above it.",
        "legend": legend(),
        "files": {"tif": f"{ii.NAME}_ffpi.tif", "png": f"{ii.NAME}_ffpi.png"},
        "grid": {"west": grid.west, "north": grid.north, "px": grid.px, "py": grid.py, "rows": grid.rows,
                 "cols": grid.cols},
        "bounds": list(grid.bounds()), "nodata": int(go.NODATA),
        "png": {"width": grid.cols, "height": grid.rows, "transparent_index": 0,
                "index_of_class": {name: i + 1 for i, name in enumerate(CLASSES)},
                "masked": "Transparent outside the city outline and over permanent water."},
        "credit": ffpi_text.CREDIT, "method": ffpi_text.method(),
    }


def city_mask(grid: go.Grid, raw: Path) -> bytearray:
    outline = json.loads((raw / "mbsa_sections" / "city_outline.geojson").read_text(encoding="utf-8"))
    geometry = outline["features"][0]["geometry"] if "features" in outline else outline.get("geometry", outline)
    return go.polygon_mask(grid, geometry)


def write_qa(raw: Path, grid: go.Grid, f: Factors) -> None:
    folder = raw / "indexes" / "built"
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("m", "l", "s", "v"):
        geotiff_write.write_tiff(folder / f"{ii.NAME}_ffpi_{name}.tif", rows_of(getattr(f, name), grid), tile=TILE,
                                 origin=(grid.west, grid.north), pixel=(grid.px, grid.py), padding=go.NODATA, level=9)


def file_line(path: Path) -> str:
    return f"{path.name}: {path.stat().st_size} bytes, SHA-256 {hashlib.sha256(path.read_bytes()).hexdigest()}"


def write_sources(out: Path, raw: Path, written: Sequence[Path]) -> Path:
    log = json.loads((raw / "indexes" / "fetch_log.json").read_text(encoding="utf-8"))
    text = ffpi_text.sources_text(log, [file_line(p) for p in written], max(e["date"] for e in log))
    path = out / "SOURCES.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build(raw: Path, out: Path, qa: bool = False) -> dict:
    """Write the four files; returns what the run found, for the report and the tests."""
    layers = load_layers(raw)
    f = factors(layers, ii.load_soil(raw))
    values = scores(f)
    grid = layers.grid
    out.mkdir(parents=True, exist_ok=True)
    tif, _ = write_tif(out / f"{ii.NAME}_ffpi.tif", grid, values)
    png = write_png(out / f"{ii.NAME}_ffpi.png", grid, values, city_mask(grid, raw))
    doc = out / f"{ii.NAME}_ffpi.json"
    doc.write_text(json.dumps(ffpi_doc(grid), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sources = write_sources(out, raw, [tif, png, doc])
    if qa:
        write_qa(raw, grid, f)
    return {"layers": layers, "factors": f, "scores": values, "files": [tif, png, doc, sources]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw", type=Path, default=ii.raw_root(), help="the raw shah_alam folder")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--qa", action="store_true", help="also write the factor ratings to <raw>/indexes/built")
    args = parser.parse_args(argv)
    found = build(args.raw, args.out, args.qa)
    held = [v for v in found["scores"] if v > go.NODATA_BELOW]
    shares = {name: sum(class_of(v) == name for v in held) / len(held) for name in CLASSES}
    print(f"{len(held)} squares scored of {len(found['scores'])}; classes over the whole grid: "
          + ", ".join(f"{k} {v:.1%}" for k, v in shares.items()))
    for path in found["files"]:
        print(file_line(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
