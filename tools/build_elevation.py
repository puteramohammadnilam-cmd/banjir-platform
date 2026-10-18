"""Build one area's elevation crops: Copernicus GLO-30 tiles and OpenStreetMap rivers -> two small GeoTIFFs.

    .venv/bin/python tools/build_elevation.py fetch --name shah-alam --bbox 101.43 2.95 101.59 3.23 \\
        --raw ../05_Raw_Data_Sources/copernicus_glo30
    .venv/bin/python tools/build_elevation.py build --name shah-alam --bbox 101.43 2.95 101.59 3.23 \\
        --raw ../05_Raw_Data_Sources/copernicus_glo30

Run from 11_Platform_Draft. `fetch` downloads the GLO-30 tiles the box needs that the raw folder does not hold yet
(AWS open bucket copernicus-dem-30m, over https) and asks Overpass once for the rivers (rivers_{name}.json). `build`
writes app/data/dem/{name}_surface.tif and {name}_above_river.tif (or into --out), reads every value back through
app/raster.py and stops unless each one is byte for byte what was written. Standard library only.

The two files cover the box plus MARGIN_KM on each side, on the GLO-30 grid (1 arc second, about 31 m), as float32
256 px deflate tiles in the layout app/raster.py reads (tools/geotiff_write.py), with no data -9999:
  - surface:     the GLO-30 height, metres above the EGM2008 geoid (about mean sea level). It is a surface model:
                 roofs, trees and bridges are in it, not only the ground.
  - above_river: surface minus the level of the nearest mapped river, within CAP_M (no data beyond). Negatives are kept.
Both are worked out from the heights as stored and then rounded to DECIMALS (0.1 m), which deflate packs into well
under half the bytes. The app gives 0.1 m and the page whole metres; GLO-30 is good to a few metres at best.
Method for above_river, on a window wide enough that every output square sees every river within CAP_M:
  1. Rivers: OpenStreetMap waterway=river|canal lines, and river or canal water areas (natural=water with water=river
     or canal, or the older waterway=riverbank), drawn onto the grid: a line marks each square it passes through
     (sampled every half square), an area each square whose centre lies inside it (even-odd, so islands stay out).
  2. River level at each river square: the LEVEL_PERCENTILE th percentile (linear, as numpy's default) of the surface
     at the river squares within LEVEL_RADIUS_M of it: the low values are the water, the high ones banks, trees and
     bridges.
  3. Nearest river square: a multi-source search outward from every river square over the 8 neighbours, nearest first
     (Dijkstra's order on the straight-line distance to the river square a neighbour came from), so each square takes
     the river square nearest it in a straight line, kept only within CAP_M. A plain breadth-first search would hand
     a square the first river square to reach it, often a diagonal one farther away.

GLO-30 COG layout read here (both Shah Alam tiles, read 4 Oct 2026): little-endian classic TIFF, float32, deflate with
the floating point predictor (3), 1024 px tiles, GTRasterType 2 (pixel is point: the tie point is a square's centre,
which falls on a whole arc second), WGS 84, no GDAL_NODATA. Anything else is refused naming the tag.

Credit: (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the
European Union and ESA; rivers (c) OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import struct
import sys
import urllib.parse
import urllib.request
import zlib
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from app import raster  # noqa: E402
import geotiff_write  # noqa: E402

MARGIN_KM = 2.0
CAP_M = 3000.0
LEVEL_RADIUS_M = 150.0
LEVEL_PERCENTILE = 10
DECIMALS = 1
NODATA = -9999.0
OUT_TILE = 256
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_AT_EQUATOR = 111_320.0
ALIGNED = 1e-6                # how far, in squares, a tile's square centre may sit from a whole arc second
DEM_DIR = ROOT / "app" / "data" / "dem"
TILE_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "MyFlood-build-elevation/1.0 (flood risk research prototype; one-off data fetch)"
RIVER_LINES = {"river", "canal"}
RIVER_WATER = {"river", "canal"}
PREDICTOR_FLOAT = 3
POINT, AREA = 2, 1            # GTRasterType
NEIGHBOURS = tuple((dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc)


class BuildError(Exception):
    """Input this tool will not use, said in plain words."""


# --- the GLO-30 tiles ---

def tile_name(lat_floor: int, lon_floor: int) -> str:
    """The GLO-30 COG name of the 1 x 1 degree tile whose south-west corner is (lat_floor, lon_floor)."""
    ns, ew = ("N" if lat_floor >= 0 else "S"), ("E" if lon_floor >= 0 else "W")
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def tiles_for(box: Sequence[float]) -> list[str]:
    """Names of the tiles a (west, south, east, north) box touches, north to south then west to east."""
    west, south, east, north = box
    return [tile_name(lat, lon) for lat in range(math.floor(north), math.floor(south) - 1, -1)
            for lon in range(math.floor(west), math.floor(east) + 1)]


@dataclass(frozen=True)
class Cog:
    """The full-resolution image of one GLO-30 COG: where its squares are, and its tiles."""

    path: Path
    width: int
    height: int
    tile: int
    across: int
    offsets: tuple[int, ...]
    counts: tuple[int, ...]
    predictor: int
    gx0: int          # the first column's centre, in whole squares east of 0 degrees
    gy0: int          # the first row's centre, in whole squares north of 0 degrees
    px: float
    py: float

    @classmethod
    def open(cls, path: Path) -> Cog:
        try:
            tags, size = raster._read_tags(path)
            predictor = _check_cog(tags)
            across, offsets, counts = raster._tile_table(tags, size)
        except raster.RasterError as error:
            raise BuildError(f"{path.name}: {error}") from None
        (px, py, _), tie = tags[raster.PIXEL_SCALE], tags[raster.TIE_POINT]
        kind = _geo_key(tags, 1025, AREA)
        x0, y0 = (tie[3], tie[4]) if kind == POINT else (tie[3] + px / 2, tie[4] - py / 2)   # first square's centre
        gx0, gy0 = _whole_squares(x0 / px, path), _whole_squares(y0 / py, path)
        return cls(path, tags[raster.WIDTH][0], tags[raster.HEIGHT][0], tags[raster.TILE_WIDTH][0], across, offsets,
                   counts, predictor, gx0, gy0, px, py)

    def tile_values(self, index: int) -> array:
        """One tile inflated and its predictor undone: tile x tile float32 values, row by row."""
        with self.path.open("rb") as stream:
            stream.seek(self.offsets[index])
            data = zlib.decompress(stream.read(self.counts[index]))
        if len(data) != self.tile * self.tile * 4:
            raise BuildError(f"{self.path.name}: tile {index} does not inflate to {self.tile} x {self.tile} values")
        if self.predictor == PREDICTOR_FLOAT:
            data = undo_float_predictor(data, self.tile)
        values = array("f", data)
        if sys.byteorder == "big":
            values.byteswap()
        return values


def _geo_key(tags: dict, key: int, default: int | None = None) -> int | None:
    keys = tags.get(raster.GEO_KEYS, (1, 1, 0, 0))
    inline = {keys[i]: keys[i + 3] for i in range(4, 4 + 4 * keys[3], 4) if keys[i + 1] == 0}
    return inline.get(key, default)


def _whole_squares(value: float, path: Path) -> int:
    if abs(value - round(value)) > ALIGNED:
        raise BuildError(f"{path.name}: square centres are not on whole squares from 0 degrees")
    return round(value)


def _check_cog(tags: dict) -> int:
    """The predictor, after refusing anything but the GLO-30 COG layout (the module docstring), naming the tag."""
    expect = raster._expect
    expect(tags, raster.BITS, lambda v: set(v) == {32}, "32 (float32)")
    expect(tags, raster.SAMPLE_FORMAT, lambda v: set(v) == {3}, "3 (IEEE float)", default=(1,))
    expect(tags, raster.SAMPLES, lambda v: v == (1,), "1 (one band)", default=(1,))
    expect(tags, raster.COMPRESSION, lambda v: v[0] in raster.DEFLATE, "8 or 32946 (deflate)", default=(1,))
    predictor = expect(tags, raster.PREDICTOR, lambda v: v[0] in (1, PREDICTOR_FLOAT), "1 or 3", default=(1,))[0]
    tile = expect(tags, raster.TILE_WIDTH, lambda v: v[0] > 0, "a tiled file")
    expect(tags, raster.TILE_LENGTH, lambda v: v == tile, "square tiles")
    expect(tags, raster.PIXEL_SCALE, lambda v: len(v) == 3 and all(0 < s < math.inf for s in v[:2]), "pixel sizes")
    expect(tags, raster.TIE_POINT, lambda v: len(v) == 6 and v[:3] == (0, 0, 0), "one tie point, at pixel (0, 0)")
    if raster.TRANSFORM in tags:
        raise raster.RasterError("a ModelTransformation is set; need a pixel scale and tie point only")
    for key, need in ((1024, (2,)), (2048, (4326,)), (1025, (AREA, POINT))):
        if _geo_key(tags, key, AREA if key == 1025 else None) not in need:
            raise raster.RasterError(f"GeoKey {key} is {_geo_key(tags, key)}; need one of {need}")
    return predictor


def undo_float_predictor(data: bytes, width: int) -> bytes:
    """TIFF's floating point predictor undone, row by row: the bytes are summed back (mod 256), then each value's four
    bytes, stored as four planes from the most significant, are put back together little-endian."""
    row_bytes, out = width * 4, bytearray(len(data))
    for start in range(0, len(data), row_bytes):
        row = bytes(accumulate(data[start:start + row_bytes], lambda a, b: (a + b) & 0xFF))
        for plane in range(4):   # plane 0 holds the most significant byte, which goes last in little-endian
            out[start + 3 - plane:start + row_bytes:4] = row[plane * width:(plane + 1) * width]
    return bytes(out)


# --- the window: squares in whole arc seconds ---

@dataclass(frozen=True)
class Window:
    """Squares on the GLO-30 grid: row 0 is the north row (centre gy0), column 0 the west column (centre gx0)."""

    gx0: int
    gy0: int
    rows: int
    cols: int
    px: float
    py: float

    @classmethod
    def around(cls, box: Sequence[float], px: float, py: float) -> Window:
        """Every square whose centre lies in the (west, south, east, north) box, edges included."""
        west, south, east, north = box
        gx0, gx1 = math.ceil(west / px - ALIGNED), math.floor(east / px + ALIGNED)
        gy0, gy1 = math.floor(north / py + ALIGNED), math.ceil(south / py - ALIGNED)
        return cls(gx0, gy0, gy0 - gy1 + 1, gx1 - gx0 + 1, px, py)

    def inner(self, other: Window) -> tuple[int, int]:
        """(row, col) in this window of `other`'s north-west square; `other` must lie inside."""
        row, col = self.gy0 - other.gy0, other.gx0 - self.gx0
        if row < 0 or col < 0 or row + other.rows > self.rows or col + other.cols > self.cols:
            raise BuildError("the output window is not inside the window worked on")
        return row, col

    def metres(self) -> tuple[float, float]:
        """(east-west, north-south) size of a square in metres, at the window's middle latitude."""
        lat = (self.gy0 - (self.rows - 1) / 2) * self.py
        return self.px * M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(lat)), self.py * M_PER_DEG_LAT

    def pixel(self, lon: float, lat: float) -> tuple[float, float]:
        """(column, row) of a point as fractions: whole numbers at square centres."""
        return lon / self.px - self.gx0, self.gy0 - lat / self.py

    def origin(self) -> tuple[float, float]:
        """(west, north) edges, for a pixel-is-area tie point."""
        return (self.gx0 - 0.5) * self.px, (self.gy0 + 0.5) * self.py


def expand(box: Sequence[float], metres: float) -> tuple[float, float, float, float]:
    """The box grown by `metres` on each side, using the cosine of its middle latitude for degrees of longitude."""
    west, south, east, north = box
    dlat = metres / M_PER_DEG_LAT
    dlon = metres / (M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians((south + north) / 2)))
    return west - dlon, south - dlat, east + dlon, north + dlat


def mosaic(cogs: Sequence[Cog], window: Window) -> array:
    """The window's surface heights, row by row, from whichever tile holds each square; NODATA where none does."""
    out = array("f", [NODATA]) * (window.rows * window.cols)
    for cog in cogs:
        if (cog.px, cog.py) != (window.px, window.py):
            raise BuildError(f"{cog.path.name}: its squares differ in size from the other tiles'")
        to_r, to_c = cog.gy0 - window.gy0, window.gx0 - cog.gx0   # window (r, c) is the image's (r + to_r, c + to_c)
        rows = range(max(0, -to_r), min(window.rows, cog.height - to_r))
        cols = range(max(0, -to_c), min(window.cols, cog.width - to_c))
        if rows and cols:
            _copy_tiles(cog, window, (to_r, to_c), rows, cols, out)
    return out


def _copy_tiles(cog: Cog, window: Window, shift: tuple[int, int], rows: range, cols: range, out: array) -> None:
    """Copy the image's squares at window rows x cols into `out`, decoding each tile they touch once."""
    to_r, to_c, size = *shift, cog.tile
    for ti in range((rows[0] + to_r) // size, (rows[-1] + to_r) // size + 1):
        for tj in range((cols[0] + to_c) // size, (cols[-1] + to_c) // size + 1):
            values = cog.tile_values(ti * cog.across + tj)
            c_lo, c_hi = max(cols[0], tj * size - to_c), min(cols[-1] + 1, (tj + 1) * size - to_c)
            for r in range(max(rows[0], ti * size - to_r), min(rows[-1] + 1, (ti + 1) * size - to_r)):
                start = (r + to_r - ti * size) * size + c_lo + to_c - tj * size
                out[r * window.cols + c_lo:r * window.cols + c_hi] = values[start:start + c_hi - c_lo]


# --- rivers from OpenStreetMap ---

def river_shapes(answer: dict) -> tuple[list[list[tuple[float, float]]], list[list[list[tuple[float, float]]]]]:
    """(lines, areas) from an Overpass `out geom` answer: lines as lists of (lon, lat), areas as lists of rings."""
    lines, areas = [], []
    for element in answer.get("elements", []):
        tags = element.get("tags", {})
        if element.get("type") == "way" and tags.get("waterway") in RIVER_LINES:
            lines.append(_points(element.get("geometry")))
        elif _is_river_water(tags) and element.get("type") == "way":
            areas.append([_points(element.get("geometry"))])
        elif _is_river_water(tags) and element.get("type") == "relation":
            areas.append([_points(m.get("geometry")) for m in element.get("members", []) if m.get("type") == "way"])
    return [line for line in lines if len(line) > 1], [rings for rings in areas if any(len(r) > 2 for r in rings)]


def _is_river_water(tags: dict) -> bool:
    return (tags.get("natural") == "water" and tags.get("water") in RIVER_WATER) or tags.get("waterway") == "riverbank"


def _points(geometry) -> list[tuple[float, float]]:
    return [(float(p["lon"]), float(p["lat"])) for p in geometry or [] if p is not None]


def draw_rivers(window: Window, lines: Iterable, areas: Iterable) -> bytearray:
    """1 at every river square of the window, 0 elsewhere (method step 1)."""
    mask = bytearray(window.rows * window.cols)
    for line in lines:
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            _draw_segment(window, mask, window.pixel(x0, y0), window.pixel(x1, y1))
    for rings in areas:
        _fill_rings(window, mask, [[window.pixel(x, y) for x, y in ring] for ring in rings if len(ring) > 1])
    return mask


def _mark(window: Window, mask: bytearray, col: int, row: int) -> None:
    if 0 <= row < window.rows and 0 <= col < window.cols:
        mask[row * window.cols + col] = 1


def _draw_segment(window: Window, mask: bytearray, start: tuple[float, float], end: tuple[float, float]) -> None:
    steps = max(1, math.ceil(2 * max(abs(end[0] - start[0]), abs(end[1] - start[1]))))
    for k in range(steps + 1):
        f = k / steps
        _mark(window, mask, round(start[0] + f * (end[0] - start[0])), round(start[1] + f * (end[1] - start[1])))


def _fill_rings(window: Window, mask: bytearray, rings: list[list[tuple[float, float]]]) -> None:
    """Every square whose centre lies inside the rings, even-odd: the rings' edges taken together."""
    edges = [(a, b) for ring in rings for a, b in zip(ring, ring[1:] + ring[:1]) if a[1] != b[1]]
    if not edges:
        return
    low, high = max(0, math.ceil(min(y for e in edges for _, y in e))), min(window.rows - 1,
                                                                           math.floor(max(y for e in edges for _, y in e)))
    for row in range(low, high + 1):
        xs = sorted(a[0] + (row - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) for a, b in edges
                    if (a[1] <= row < b[1]) or (b[1] <= row < a[1]))
        for left, right in zip(xs[::2], xs[1::2]):
            for col in range(max(0, math.ceil(left)), min(window.cols - 1, math.floor(right)) + 1):
                mask[row * window.cols + col] = 1


# --- river levels and the nearest river ---

def percentile(values: Sequence[float], pct: float) -> float:
    """The pct th percentile with linear interpolation between the two nearest ranks (numpy's default)."""
    ordered = sorted(values)
    at = (len(ordered) - 1) * pct / 100
    low = math.floor(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def disc(radius_m: float, dx_m: float, dy_m: float) -> list[tuple[int, int]]:
    """(row, col) offsets of the squares whose centres lie within radius_m of a square's centre, itself included."""
    reach_r, reach_c = int(radius_m // dy_m), int(radius_m // dx_m)
    return [(dr, dc) for dr in range(-reach_r, reach_r + 1) for dc in range(-reach_c, reach_c + 1)
            if (dr * dy_m) ** 2 + (dc * dx_m) ** 2 <= radius_m ** 2]


def river_levels(surface: Sequence[float], mask: bytearray, rows: int, cols: int,
                 offsets: Sequence[tuple[int, int]], pct: float = LEVEL_PERCENTILE) -> dict[int, float]:
    """{square index: river level} for each river square with a surface value (method step 2)."""
    levels = {}
    for i in (i for i, is_river in enumerate(mask) if is_river and surface[i] > raster.NODATA_BELOW):
        row, col = divmod(i, cols)
        near = [surface[j] for dr, dc in offsets
                if 0 <= row + dr < rows and 0 <= col + dc < cols
                and mask[j := (row + dr) * cols + col + dc] and surface[j] > raster.NODATA_BELOW]
        levels[i] = percentile(near, pct)
    return levels


def nearest_river(sources: Iterable[int], rows: int, cols: int, dx_m: float, dy_m: float, cap_m: float) -> array:
    """For each square, the index of the river square the search in step 3 finds nearest, or -1 where none lies within
    cap_m in a straight line."""
    found, best = array("l", [-1]) * (rows * cols), array("d", [math.inf]) * (rows * cols)
    heap = []
    for i in sources:
        found[i], best[i] = i, 0.0
        heap.append((0.0, i))
    heapq.heapify(heap)
    while heap:
        reach, i = heapq.heappop(heap)
        if reach > best[i]:   # reached again since, from a nearer river square
            continue
        (row, col), (s_row, s_col) = divmod(i, cols), divmod(found[i], cols)
        for dr, dc in NEIGHBOURS:
            r, c = row + dr, col + dc
            if 0 <= r < rows and 0 <= c < cols:
                j, metres = r * cols + c, math.hypot((r - s_row) * dy_m, (c - s_col) * dx_m)
                if metres < best[j] and metres <= cap_m:
                    found[j], best[j] = found[i], metres
                    heapq.heappush(heap, (metres, j))
    return found


def above_river(surface: Sequence[float], levels: dict[int, float], nearest: Sequence[int]) -> array:
    """Surface minus the nearest river square's level; NODATA where there is none or no surface."""
    out = array("f", [NODATA]) * len(surface)
    for i, source in enumerate(nearest):
        if source >= 0 and source in levels and surface[i] > raster.NODATA_BELOW:
            out[i] = surface[i] - levels[source]
    return out


# --- output ---

def crop(values: Sequence[float], window: Window, part: Window) -> list[list[float]]:
    """The rows of `part`, a window inside `window`, as lists of floats rounded to DECIMALS (no data kept as NODATA)."""
    top, left = window.inner(part)
    return [[round(v, DECIMALS) if v > raster.NODATA_BELOW else NODATA
             for v in values[(top + r) * window.cols + left:(top + r) * window.cols + left + part.cols]]
            for r in range(part.rows)]


def write_checked(path: Path, rows: list[list[float]], part: Window) -> str:
    """Write one crop, read every value back through app/raster.py and refuse unless each is byte for byte what was
    written. Returns the file's SHA-256."""
    geotiff_write.write_tiff(path, rows, tile=OUT_TILE, origin=part.origin(), pixel=(part.px, part.py),
                             padding=NODATA, level=9)
    opened = raster.DepthFile.open(path, path.stem)
    for r, row in enumerate(rows):
        written = struct.pack(f"<{len(row)}f", *row)
        read = struct.pack(f"<{len(row)}f", *(opened.value_at(r, c, float) for c in range(len(row))))
        if read != written:
            raise BuildError(f"{path.name}: row {r} reads back differently from what was written")
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- commands ---

def overpass_query(box: Sequence[float]) -> str:
    west, south, east, north = box
    bbox = f"{south:.4f},{west:.4f},{north:.4f},{east:.4f}"
    return (f'[out:json][timeout:120];(way["waterway"~"^(river|canal)$"]({bbox});'
            f'way["natural"="water"]["water"~"^(river|canal)$"]({bbox});'
            f'relation["natural"="water"]["water"~"^(river|canal)$"]({bbox});'
            f'way["waterway"="riverbank"]({bbox});node["natural"="peak"]({bbox}););out geom;')


def _get(url: str, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as answer:   # noqa: S310  fixed https hosts only
        return answer.read()


def fetch(args: argparse.Namespace) -> None:
    """Download what `build` needs into the raw folder: missing tiles, then the rivers (one Overpass request)."""
    raw = Path(args.raw)
    raw.mkdir(parents=True, exist_ok=True)
    work = expand(args.bbox, (args.margin_km * 1000) + CAP_M + LEVEL_RADIUS_M)
    for name in tiles_for(work):
        target = raw / f"{name}.tif"
        if not target.exists():
            target.write_bytes(_get(TILE_URL.format(name=name)))
        print(f"{target.name}: {target.stat().st_size} bytes")
    rivers = raw / f"rivers_{args.name}.json"
    rivers.write_bytes(_get(OVERPASS_URL, urllib.parse.urlencode({"data": overpass_query(work)}).encode()))
    print(f"{rivers.name}: {rivers.stat().st_size} bytes, {len(json.loads(rivers.read_bytes())['elements'])} elements")


def build(args: argparse.Namespace) -> dict:
    """Write and check the two crops; returns what the run found, for the report and the tests."""
    raw, out = Path(args.raw), Path(args.out)
    work_box = expand(args.bbox, (args.margin_km * 1000) + CAP_M + LEVEL_RADIUS_M)
    cogs = [Cog.open(raw / f"{name}.tif") for name in tiles_for(work_box)]
    work, part = (Window.around(box, cogs[0].px, cogs[0].py)
                  for box in (work_box, expand(args.bbox, args.margin_km * 1000)))
    surface = mosaic(cogs, work)
    lines, areas = river_shapes(json.loads((raw / f"rivers_{args.name}.json").read_text(encoding="utf-8")))
    mask = draw_rivers(work, lines, areas)
    dx_m, dy_m = work.metres()
    levels = river_levels(surface, mask, work.rows, work.cols, disc(LEVEL_RADIUS_M, dx_m, dy_m))
    nearest = nearest_river(levels, work.rows, work.cols, dx_m, dy_m, CAP_M)
    heights = above_river(surface, levels, nearest)
    out.mkdir(parents=True, exist_ok=True)
    found = {"window": part, "lines": len(lines), "areas": len(areas), "river_squares": len(levels), "files": {}}
    for layer, values in (("surface", surface), ("above_river", heights)):
        path = out / f"{args.name}_{layer}.tif"
        rows = crop(values, work, part)
        found["files"][path.name] = {"bytes": None, "sha256": write_checked(path, rows, part),
                                     "no_data": sum(v <= raster.NODATA_BELOW for row in rows for v in row)}
        found["files"][path.name]["bytes"] = path.stat().st_size
    return found


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--name", required=True, help="file name stem, such as shah-alam")
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--raw", required=True, help="folder for the GLO-30 tiles and the rivers answer")
    parser.add_argument("--out", default=str(DEM_DIR), help="where build writes (default app/data/dem)")
    parser.add_argument("--margin-km", type=float, default=MARGIN_KM)
    args = parser.parse_args(argv)
    west, south, east, north = args.bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        parser.error("--bbox must be west south east north, west below east and south below north")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "fetch":
        fetch(args)
        return
    found = build(args)
    part = found["window"]
    print(f"{part.rows} x {part.cols} squares; {found['lines']} river lines, {found['areas']} water areas, "
          f"{found['river_squares']} river squares in the window worked on")
    for name, info in found["files"].items():
        print(f"{name}: {info['bytes']} bytes, SHA-256 {info['sha256']}, {info['no_data']} squares of no data; "
              "read back byte for byte")


if __name__ == "__main__":
    main()
