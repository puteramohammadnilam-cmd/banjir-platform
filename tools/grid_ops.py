"""Operations on a north-up lat/lon grid of squares, for the index tools. Standard library only.

A grid's values are one flat array, row by row, row 0 at the north edge and column 0 at the west edge; square (r, c)
is index r * cols + c. No data is NODATA (-9999) in float arrays.

    Grid(west, north, px, py, rows, cols)         the squares; centre(r, c) is (lon, lat)
    min_filter3, mean_filter3                      3 x 3 lowest and mean, edges and no data left out
    slope_percent                                  Horn's method, in percent
    polygon_mask, first_holder                     squares whose centre lies in a GeoJSON area (scan lines, even-odd)
    draw_lines, line_metres                        squares a line passes through; metres of line in each square
    distance_to                                    straight-line metres to the nearest marked square, up to a cap
    disc_rows, disc_sum                            a sum over the squares within a radius, by row prefix sums
    fractions_from                                 counts of a finer class raster's pixels in each square
    sample_nearest                                 a coarser raster's value at each square's centre
"""
from __future__ import annotations

import math
import sys
from array import array
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_elevation as be  # noqa: E402

NODATA = -9999.0
NODATA_BELOW = -9998.0
M_PER_DEG_LAT = be.M_PER_DEG_LAT
M_PER_DEG_LON_AT_EQUATOR = be.M_PER_DEG_LON_AT_EQUATOR


@dataclass(frozen=True)
class Grid:
    """Squares of px x py degrees from the (west, north) corner."""

    west: float
    north: float
    px: float
    py: float
    rows: int
    cols: int

    @property
    def size(self) -> int:
        return self.rows * self.cols

    def centre(self, row: int, col: int) -> tuple[float, float]:
        return self.west + (col + 0.5) * self.px, self.north - (row + 0.5) * self.py

    def bounds(self) -> tuple[float, float, float, float]:
        return self.west, self.north - self.rows * self.py, self.west + self.cols * self.px, self.north

    def metres(self) -> tuple[float, float]:
        """(east-west, north-south) size of a square in metres, at the grid's middle latitude."""
        lat = self.north - self.rows * self.py / 2
        return self.px * M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(lat)), self.py * M_PER_DEG_LAT

    def row_weight(self, row: int) -> float:
        """A square's area in this row relative to one at the equator: the cosine of its centre's latitude."""
        return math.cos(math.radians(self.north - (row + 0.5) * self.py))

    def pixel(self, lon: float, lat: float) -> tuple[float, float]:
        """(column, row) as fractions: whole numbers at square centres."""
        return (lon - self.west) / self.px - 0.5, (self.north - lat) / self.py - 0.5


def _neighbours(values: Sequence[float], rows: int, cols: int, i: int) -> list[float]:
    r, c = divmod(i, cols)
    return [values[rr * cols + cc] for rr in range(max(0, r - 1), min(rows, r + 2))
            for cc in range(max(0, c - 1), min(cols, c + 2)) if values[rr * cols + cc] > NODATA_BELOW]


def min_filter3(values: Sequence[float], rows: int, cols: int) -> array:
    """The lowest value of the 3 x 3 squares around each square (fewer at the edges), no data left out."""
    return array("d", (min(near, default=NODATA) for near in
                       (_neighbours(values, rows, cols, i) for i in range(rows * cols))))


def mean_filter3(values: Sequence[float], rows: int, cols: int) -> array:
    """The mean of the 3 x 3 squares around each square (fewer at the edges), no data left out."""
    return array("d", (sum(near) / len(near) if near else NODATA for near in
                       (_neighbours(values, rows, cols, i) for i in range(rows * cols))))


def slope_percent(values: Sequence[float], rows: int, cols: int, dx: float, dy: float) -> array:
    """Horn's (1981) slope, 100 x rise over run. A neighbour past the grid's edge takes the nearest square inside it,
    one with no data the centre's value; a square with no data has no slope (NODATA)."""
    out = array("d", [NODATA]) * (rows * cols)
    for r in range(rows):
        for c in range(cols):
            z = values[r * cols + c]
            if z <= NODATA_BELOW:
                continue
            n = [[_at(values, rows, cols, r + dr, c + dc, z) for dc in (-1, 0, 1)] for dr in (-1, 0, 1)]
            gx = ((n[0][2] + 2 * n[1][2] + n[2][2]) - (n[0][0] + 2 * n[1][0] + n[2][0])) / (8 * dx)
            gy = ((n[2][0] + 2 * n[2][1] + n[2][2]) - (n[0][0] + 2 * n[0][1] + n[0][2])) / (8 * dy)
            out[r * cols + c] = 100 * math.hypot(gx, gy)
    return out


def _at(values: Sequence[float], rows: int, cols: int, r: int, c: int, fallback: float) -> float:
    value = values[min(rows - 1, max(0, r)) * cols + min(cols - 1, max(0, c))]
    return value if value > NODATA_BELOW else fallback


# --- areas and lines ---

def _rings_of(geometry: dict) -> list[list[list[tuple[float, float]]]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else None
    if polygons is None:
        raise ValueError(f"A Polygon or MultiPolygon is needed, got {kind!r}.")
    return [[[(p[0], p[1]) for p in ring] for ring in polygon] for polygon in polygons]


def polygon_mask(grid: Grid, geometry: dict) -> bytearray:
    """1 at each square whose centre lies inside the geometry (each polygon even-odd over its rings, so holes stay
    out; polygons joined), else 0. A centre exactly on an edge may fall either way."""
    mask = bytearray(grid.size)
    for rings in _rings_of(geometry):
        edges = [(grid.pixel(*a), grid.pixel(*b)) for ring in rings for a, b in zip(ring, ring[1:])]
        edges = [(a, b) for a, b in edges if a[1] != b[1]]
        if not edges:
            continue
        low = max(0, math.ceil(min(min(a[1], b[1]) for a, b in edges)))
        high = min(grid.rows - 1, math.floor(max(max(a[1], b[1]) for a, b in edges)))
        for row in range(low, high + 1):
            xs = sorted(a[0] + (row - a[1]) * (b[0] - a[0]) / (b[1] - a[1]) for a, b in edges
                        if (a[1] <= row < b[1]) or (b[1] <= row < a[1]))
            for left, right in zip(xs[::2], xs[1::2]):
                for col in range(max(0, math.ceil(left)), min(grid.cols - 1, math.floor(right)) + 1):
                    mask[row * grid.cols + col] = 1
    return mask


def first_holder(grid: Grid, geometries: Sequence[dict]) -> array:
    """For each square, the index of the first geometry holding its centre, else -1."""
    found = array("i", [-1]) * grid.size
    for k, geometry in enumerate(geometries):
        for i, inside in enumerate(polygon_mask(grid, geometry)):
            if inside and found[i] < 0:
                found[i] = k
    return found


def _segment_steps(grid: Grid, a: tuple[float, float], b: tuple[float, float]) -> tuple[int, float, float]:
    (x0, y0), (x1, y1) = grid.pixel(*a), grid.pixel(*b)
    steps = max(1, math.ceil(4 * max(abs(x1 - x0), abs(y1 - y0))))
    return steps, x1 - x0, y1 - y0


def draw_lines(grid: Grid, lines: Iterable[Sequence[tuple[float, float]]]) -> bytearray:
    """1 at each square a line passes through (sampled every quarter square), else 0."""
    mask = bytearray(grid.size)
    for line in lines:
        for a, b in zip(line, line[1:]):
            steps, ddx, ddy = _segment_steps(grid, a, b)
            x0, y0 = grid.pixel(*a)
            for k in range(steps + 1):
                col, row = round(x0 + ddx * k / steps), round(y0 + ddy * k / steps)
                if 0 <= row < grid.rows and 0 <= col < grid.cols:
                    mask[row * grid.cols + col] = 1
    return mask


def line_metres(grid: Grid, lines: Iterable[Sequence[tuple[float, float]]]) -> array:
    """Metres of line in each square: each segment cut into quarter-square steps, each step's length given to the
    square holding its middle."""
    dx, dy = grid.metres()
    out = array("d", [0.0]) * grid.size
    for line in lines:
        for a, b in zip(line, line[1:]):
            steps, ddx, ddy = _segment_steps(grid, a, b)
            x0, y0 = grid.pixel(*a)
            step_m = math.hypot(ddx * dx, ddy * dy) / steps
            for k in range(steps):
                col, row = round(x0 + ddx * (k + 0.5) / steps), round(y0 + ddy * (k + 0.5) / steps)
                if 0 <= row < grid.rows and 0 <= col < grid.cols:
                    out[row * grid.cols + col] += step_m
    return out


def distance_to(mask: bytearray, grid: Grid, cap_m: float) -> array:
    """Straight-line metres from each square's centre to the nearest marked square's centre (0 on one), found with
    tools/build_elevation.nearest_river; math.inf where none lies within cap_m."""
    dx, dy = grid.metres()
    nearest = be.nearest_river((i for i, on in enumerate(mask) if on), grid.rows, grid.cols, dx, dy, cap_m)
    out = array("d", [math.inf]) * grid.size
    for i, source in enumerate(nearest):
        if source >= 0:
            (r, c), (sr, sc) = divmod(i, grid.cols), divmod(source, grid.cols)
            out[i] = math.hypot((r - sr) * dy, (c - sc) * dx)
    return out


# --- sums over a disc ---

def disc_rows(radius_m: float, dx: float, dy: float) -> list[tuple[int, int]]:
    """(row offset, half width in squares) of the squares whose centres lie within radius_m of a square's centre."""
    reach = int(radius_m // dy)
    return [(dr, int(math.sqrt(max(0.0, radius_m ** 2 - (dr * dy) ** 2)) // dx)) for dr in range(-reach, reach + 1)]


def disc_sum(values: Sequence[float], grid: Grid, rows_spec: Sequence[tuple[int, int]],
             only: Callable[[int], bool] = lambda i: True) -> array:
    """For each square that `only` accepts, the sum of `values` over the disc rows_spec around it (squares past the
    grid's edge count as 0); 0 elsewhere."""
    cols = grid.cols
    prefix = []
    for r in range(grid.rows):
        running, row = 0.0, array("d", [0.0])
        for c in range(cols):
            running += values[r * cols + c]
            row.append(running)
        prefix.append(row)
    out = array("d", [0.0]) * grid.size
    for i in range(grid.size):
        if not only(i):
            continue
        r, c = divmod(i, cols)
        total = 0.0
        for dr, half in rows_spec:
            if 0 <= r + dr < grid.rows:
                total += prefix[r + dr][min(cols, c + half + 1)] - prefix[r + dr][max(0, c - half)]
        out[i] = total
    return out


# --- other rasters onto the grid ---

def fractions_from(grid: Grid, values: Sequence[int], src: tuple[float, float, float, float, int],
                   classes: Sequence[int]) -> dict[int, array]:
    """{class: count of the source pixels of that class whose centres fall in each square}. `src` is the source
    window's (west edge, north edge, px, py, cols); `values` its pixels row by row. Other values are not counted."""
    west, north, spx, spy, scols = src
    srows = len(values) // scols
    to_col = [math.floor((west + (j + 0.5) * spx - grid.west) / grid.px) for j in range(scols)]
    to_row = [math.floor((grid.north - (north - (i + 0.5) * spy)) / grid.py) for i in range(srows)]
    counts = {k: array("H", [0]) * grid.size for k in classes}
    for i, row in enumerate(to_row):
        if not 0 <= row < grid.rows:
            continue
        base = row * grid.cols
        for j in range(scols):
            col = to_col[j]
            k = values[i * scols + j]
            if 0 <= col < grid.cols and k in counts:
                counts[k][base + col] += 1
    return counts


def add_means(grid: Grid, values: Sequence[int], src: tuple[float, float, float, float, int],
              table: Sequence[float | None], total: array, count: array) -> None:
    """Add table[value] of each source pixel to `total` and 1 to `count` at the square holding its centre (`src` as
    in fractions_from); a pixel whose table entry is None is skipped. The two arrays are filled in place, so tiles of
    one source can be added one after another."""
    west, north, spx, spy, scols = src
    srows = len(values) // scols
    to_col = [math.floor((west + (j + 0.5) * spx - grid.west) / grid.px) for j in range(scols)]
    for i in range(srows):
        row = math.floor((grid.north - (north - (i + 0.5) * spy)) / grid.py)
        if not 0 <= row < grid.rows:
            continue
        base = row * grid.cols
        for j in range(scols):
            col, value = to_col[j], table[values[i * scols + j]]
            if value is not None and 0 <= col < grid.cols:
                total[base + col] += value
                count[base + col] += 1


def sample_nearest(grid: Grid, values: Sequence[float], src: tuple[float, float, float, float, int],
                   fill: float = NODATA) -> array:
    """The source pixel holding each square's centre (`src` as in fractions_from); `fill` past its edge."""
    west, north, spx, spy, scols = src
    srows = len(values) // scols
    out = array("d", [fill]) * grid.size
    for r in range(grid.rows):
        for c in range(grid.cols):
            lon, lat = grid.centre(r, c)
            j, i = math.floor((lon - west) / spx), math.floor((north - lat) / spy)
            if 0 <= i < srows and 0 <= j < scols:
                out[r * grid.cols + c] = values[i * scols + j]
    return out
