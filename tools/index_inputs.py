"""The index tools' inputs, read onto one grid: the GLO-30 crop of app/data/dem (the area's box plus 2 km). Standard
library only; everything is read from files fetched earlier (tools/fetch_indexes.py), never from the network.

Each area the tools build for is a Place (PLACES, picked with --area): Shah Alam on GLO-30's own 1 arc second squares
(about 31 m), and Johor, a whole state, on 3 arc second squares (about 92 m) that each hold the lowest of the nine
GLO-30 heights inside them (tools/build_elevation.py --step 3), so a state's files stay small enough for the repo and
for these tools. The functions below default to Shah Alam.

    grid = grid_window()                            # or grid_window(PLACES["johor"])
    surface = load_surface(grid)                    # metres, from app/data/dem/shah-alam_surface.tif
    cover = load_worldcover(grid, raw)              # {WorldCover class: pixel count per square}
    vegetation = load_vegetation(grid, raw)         # mean fractional vegetation cover per square, 0 to 1
    soil = load_soil(grid, raw)                     # SoilGrids sand/silt/clay %, 0-15 cm, and where it had no value
    people = load_population(grid, raw)             # WorldPop people per square

Place words are fine here: this is a tool, not app code.
"""
from __future__ import annotations

import json
import math
import os
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import raster  # noqa: E402
import build_elevation as be  # noqa: E402
import grid_ops as go  # noqa: E402
import tiff_read as tr  # noqa: E402
from rawpaths import RAW_SOURCES  # noqa: E402

MARGIN_KM = be.MARGIN_KM
ARC_SECOND = 1 / 3600
DEM_DIR = ROOT / "app" / "data" / "dem"


@dataclass(frozen=True)
class Place:
    """One area the index tools build for. Paths are inside its raw folder."""

    name: str                 # the area id, and the stem of its files
    raw_folder: str           # its folder in the raw sources
    bbox: tuple               # west, south, east, north: tools/build_elevation.py's --bbox
    step: int                 # arc seconds per square: 1 (GLO-30's own) or 3 (each the lowest of 3 x 3 GLO-30 squares)
    outline: str              # GeoJSON of what the pictures are cut to: every feature's outline
    roads: str                # Overpass answer of the vehicle roads (tools/build_section_scores.py)
    sections: str | None = None   # GeoJSON of the sections, None for tools/sections_io.py's default (Shah Alam's)
    expected: int | None = None   # how many sections it must hold
    hotspots: tuple = ()      # sections named as flood hotspots, for the score's comparison

    @property
    def window(self) -> int:
        """Squares on each side for "the lowest height of the 3 x 3 squares" (about 90 m): 1 on GLO-30's own squares,
        0 on 3 arc second squares, which already hold the lowest of the nine GLO-30 heights inside them."""
        return 1 if self.step == 1 else 0

    def dem_file(self, layer: str = "surface") -> Path:
        return DEM_DIR / f"{self.name}_{layer}.tif"


PLACES = {place.name: place for place in (
    Place("shah-alam", "shah_alam", (101.43, 2.95, 101.59, 3.23), 1, "mbsa_sections/city_outline.geojson",
          "city_osm/roads.json", hotspots=("seksyen-16", "seksyen-17", "seksyen-18", "seksyen-36", "seksyen-25")),
    Place("johor", "johor", (102.46, 1.26, 104.55, 2.84), 3, "districts/districts.geojson",
          "indexes/osm_roads/roads_johor.json", sections="districts/districts.geojson", expected=10),
)}
SHAH_ALAM = PLACES["shah-alam"]
NAME = SHAH_ALAM.name
CITY_BBOX = SHAH_ALAM.bbox
DEM_FILE = SHAH_ALAM.dem_file()
WORLDCOVER_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
NDVI_BAND = 1                 # the composite's bands are NDVI p90, p50, p10
NDVI_NODATA = 255
SOIL_DEPTHS = (("0-5cm", 5.0), ("5-15cm", 10.0))   # (layer, thickness in cm): weights of the 0-15 cm mean
SOIL_PROPERTIES = ("sand", "silt", "clay")
WORLDPOP_FILE = "mys_ppp_2020_constrained.tif"
BAND_ROWS = 4096              # 10 m source rows read at a time: a state's window would not fit in memory at once


def raw_root(place: Place = SHAH_ALAM) -> Path:
    """$BANJIR_RAW_DIR/<raw folder> when set, else ../05_Raw_Data_Sources/<raw folder> (shah_alam by default)."""
    raw = Path(os.environ["BANJIR_RAW_DIR"]) if os.environ.get("BANJIR_RAW_DIR") else RAW_SOURCES
    return raw / place.raw_folder


def grid_window(place: Place = SHAH_ALAM) -> go.Grid:
    """The grid of app/data/dem's crop, worked out the way tools/build_elevation.py does."""
    size = place.step * ARC_SECOND
    part = be.Window.around(be.expand(place.bbox, MARGIN_KM * 1000), size, size)
    west, north = part.origin()
    return go.Grid(west, north, size, size, part.rows, part.cols)


def _keep_height(value: float) -> float | None:
    return value if raster.NODATA_BELOW < value < math.inf else go.NODATA


def load_surface(grid: go.Grid, path: Path = DEM_FILE) -> array:
    """The GLO-30 surface crop (metres, 0.1 m steps), checked to lie on `grid`."""
    crop = raster.DepthFile.open(path, path.stem)
    g = crop.grid
    if (g.rows, g.cols) != (grid.rows, grid.cols) or abs(g.x0 - grid.west) > 1e-9 or abs(g.y0 - grid.north) > 1e-9:
        raise ValueError(f"{path.name} is not on the index grid")
    return array("d", (crop.value_at(r, c, _keep_height) for r in range(grid.rows) for c in range(grid.cols)))


def _window_of(image: tr.Image, grid: go.Grid) -> tuple[tuple[int, int, int, int], tuple]:
    """The image's pixel window over the grid, and its (west edge, north edge, px, py, cols) for grid_ops."""
    top, left, rows, cols = tr.pixel_window(image, grid.bounds())
    return (top, left, rows, cols), (image.west + left * image.px, image.north - top * image.py, image.px,
                                     image.py, cols)


def _bands(window: tuple[int, int, int, int], src: tuple) -> list[tuple[tuple[int, int, int, int], tuple]]:
    """The window (and its src) cut into parts of up to BAND_ROWS rows, north first."""
    (top, left, rows, cols), (west, north, px, py, scols) = window, src
    return [((top + k, left, min(BAND_ROWS, rows - k), cols), (west, north - k * py, px, py, scols))
            for k in range(0, rows, BAND_ROWS)]


def _piece_sources(folder: Path) -> list[tr.PieceSource]:
    found = sorted(p.parent for p in folder.glob("*/pieces.json"))
    if not found:
        raise FileNotFoundError(f"no downloaded files in {folder}; run tools/fetch_indexes.py first")
    return [tr.PieceSource(p) for p in found]


def load_worldcover(grid: go.Grid, raw: Path) -> dict[int, array]:
    """{class: count of 10 m WorldCover pixels per square}, over the map tiles fetched."""
    counts = {k: array("H", [0]) * grid.size for k in WORLDCOVER_CLASSES}
    for source in _piece_sources(raw / "indexes" / "worldcover"):
        image = tr.open_image(source)
        window, src = _window_of(image, grid)
        if window[2] <= 0 or window[3] <= 0:
            continue
        for part, part_src in _bands(window, src):
            go.fractions_from(grid, tr.read_window(source, image, *part), part_src, WORLDCOVER_CLASSES, into=counts)
    return counts


@dataclass(frozen=True)
class Vegetation:
    """Per square: the mean fractional vegetation cover (0 to 1) of its NDVI pixels, NODATA where none had a value."""

    cover: array
    ndvi_lo: float
    ndvi_hi: float


def fvc_table(ndvi_lo: float, ndvi_hi: float) -> list[float | None]:
    """Fractional vegetation cover for each NDVI composite value 0 to 255 (NDVI = DN x 0.008 - 1): the scaled NDVI
    squared, ((NDVI - lo) / (hi - lo))^2, kept to 0..1 (Carlson & Ripley 1997); None for no data (255)."""
    table: list[float | None] = []
    for dn in range(256):
        scaled = min(1.0, max(0.0, ((dn * 0.008 - 1) - ndvi_lo) / (ndvi_hi - ndvi_lo)))
        table.append(None if dn == NDVI_NODATA else scaled * scaled)
    return table


def load_vegetation(grid: go.Grid, raw: Path, ndvi_lo: float, ndvi_hi: float) -> Vegetation:
    table = fvc_table(ndvi_lo, ndvi_hi)
    total, count = array("d", [0.0]) * grid.size, array("I", [0]) * grid.size
    for source in _piece_sources(raw / "indexes" / "vegetation"):
        image = tr.open_image(source)
        window, src = _window_of(image, grid)
        if window[2] <= 0 or window[3] <= 0:
            continue
        for part, part_src in _bands(window, src):
            go.add_means(grid, tr.read_window(source, image, *part, band=NDVI_BAND), part_src, table, total, count)
    cover = array("d", (t / n if n else go.NODATA for t, n in zip(total, count)))
    return Vegetation(cover, ndvi_lo, ndvi_hi)


def ndvi_histogram(grid: go.Grid, raw: Path) -> list[int]:
    """How many NDVI p50 pixels over the grid hold each value 0 to 255: for the bare and full cover end points."""
    counts = [0] * 256
    for source in _piece_sources(raw / "indexes" / "vegetation"):
        image = tr.open_image(source)
        window, src = _window_of(image, grid)
        if window[2] > 0 and window[3] > 0:
            for part, _ in _bands(window, src):
                for dn in tr.read_window(source, image, *part, band=NDVI_BAND):
                    counts[dn] += 1
    return counts


@dataclass(frozen=True)
class Soil:
    """SoilGrids on its own grid: sand, silt and clay in percent (0-15 cm, adding to 100) where it has a value, and
    `held` 1 there, 0 at a gap (SoilGrids gives 0 under towns and water)."""

    sand: array
    silt: array
    clay: array
    held: bytearray
    src: tuple          # (west edge, north edge, px, py, cols)


def _soil_layer(raw: Path, prop: str) -> tuple[array, tuple]:
    """One property's 0-15 cm thickness-weighted mean in g/kg, 0 where either layer is 0 (a gap)."""
    layers = []
    for depth, _ in SOIL_DEPTHS:
        source = tr.FileSource(raw / "indexes" / "soilgrids" / f"{prop}_{depth}_mean.tif")
        image = tr.open_image(source)
        layers.append((tr.read_window(source, image, 0, 0, image.height, image.width),
                       (image.west, image.north, image.px, image.py, image.width)))
    (top, src), (below, src2) = layers
    if src != src2:
        raise ValueError(f"SoilGrids {prop}: the two layers are not on one grid")
    weights = [t for _, t in SOIL_DEPTHS]
    mean = array("d", ((a * weights[0] + b * weights[1]) / sum(weights) if a > 0 and b > 0 else 0.0
                       for a, b in zip(top, below)))
    return mean, src


def load_soil(raw: Path) -> Soil:
    found = {prop: _soil_layer(raw, prop) for prop in SOIL_PROPERTIES}
    srcs = {src for _, src in found.values()}
    if len(srcs) != 1:
        raise ValueError("SoilGrids sand, silt and clay are not on one grid")
    sand, silt, clay = (found[p][0] for p in SOIL_PROPERTIES)
    held = bytearray(1 if s > 0 and t > 0 and c > 0 else 0 for s, t, c in zip(sand, silt, clay))
    total = [s + t + c for s, t, c in zip(sand, silt, clay)]
    pct = [array("d", (100 * v / n if h else 0.0 for v, n, h in zip(values, total, held)))
           for values in (sand, silt, clay)]
    return Soil(*pct, held, srcs.pop())


def load_population(grid: go.Grid, raw: Path) -> array:
    """WorldPop 2020 constrained people in each square: the people of the 3 arc second pixel holding the square's
    centre, shared by area among the squares it holds (so a section's squares add up to its people); 0 where WorldPop
    has no people (no data: not a settled area)."""
    source = tr.FileSource(raw / "indexes" / "worldpop" / WORLDPOP_FILE)
    image = tr.open_image(source)
    window, src = _window_of(image, grid)
    people = tr.read_window(source, image, *window)
    cleaned = array("d", (v if 0 < v < math.inf else 0.0 for v in people))
    per_pixel = go.sample_nearest(grid, cleaned, src, fill=0.0)
    share = (grid.px * grid.py) / (image.px * image.py)   # a square's area over a pixel's, at the same latitude
    return array("d", (people * share for people in per_pixel))


def osm_lines(path: Path, kinds: set[str], key: str) -> list[list[tuple[float, float]]]:
    """(lon, lat) lines of the ways in an Overpass `out geom` answer whose tag `key` is one of `kinds`."""
    answer = json.loads(path.read_text(encoding="utf-8"))
    lines = [[(float(p["lon"]), float(p["lat"])) for p in e.get("geometry") or [] if p is not None]
             for e in answer.get("elements", []) if e.get("type") == "way" and e.get("tags", {}).get(key) in kinds]
    return [line for line in lines if len(line) > 1]
