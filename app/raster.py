"""Flood depth from the JRC GeoTIFFs, read with the standard library only (struct, zlib, array, os.pread).

A port of DepthRaster in tools/build_data.py, which used numpy and PIL, adding bounds checks, several grids and the
return periods. Only the layout JRC ships is read: little-endian classic TIFF, one float32 sample, deflate, no
predictor, square tiles, a pixel scale with one tie point, WGS 84 lat/lon with pixel-is-area. Anything else is refused
naming the tag, because a misread file gives depths that look right and are wrong.

Two kinds of error, so that nothing mistakes one for the other. RasterError, which is an Exception and not a
ValueError, means the data: a file in another layout, a damaged or cut-short one, or one that cannot be read (an
OSError is turned into it). ValueError means a bad argument, such as a block size or a view. The app answers the
first with a 503; the second is the caller's mistake.

A header is not trusted. Each tag may claim only so many values, checked before any is read or decoded (MAX_TILES,
MAX_GEO_KEYS, MAX_TAG_VALUES), and a tag listed twice is refused, so a header cannot make the reader do the work of
a file the size it claims.

What the files we hold say (ID211_N10_E100_RP{10,20,50}_depth.tif, read 3 Oct 2026, the 20 and 50 on 4 Oct; they
agree, and so do the files of the other two grids):
- GeoKeys: 1024 GTModelType = 2 (geographic), 1025 GTRasterType = 1 (pixel is area), 2048 GeographicType = 4326
  (WGS 84), 2049 GeogCitation = "unknown", 2054 GeogAngularUnits = 9102 (degree), and the WGS 84 ellipsoid again in
  2057 and 2059 (6378137 m, 1/298.257223563). GDAL_NODATA is "-9999".
- 11999 x 11999 squares in 47 x 47 tiles of 256 px. Tiles with no water are not stored (offset and byte count 0).
- The pixel scale differs between x (0.0008333333356347339) and y (0.0008333333333325754). Rows here use y. The build
  used x for both, which moves no premise or square of the built areas (the parity tests check this).
- No square inside the image is 0, a trace or negative: the smallest depth is 0.10 m (every stored tile of the nine
  files scanned, 4 Oct 2026). The wet squares nest: none is wet at 1 in 10 and dry at 1 in 20, or wet at 1 in 20 and
  dry at 1 in 50. Depths mostly rise with the return period, but not always: about half a percent of the wet squares
  are a little deeper in the smaller flood, as the model gives them. Zeros sit only in the padding of the partial right
  and bottom tiles, which the build could read through an index past the edge; here such an index is outside the grid.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import struct
import sys
import threading
import zlib
from array import array
from collections import Counter, OrderedDict
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("banjir")

RETURN_PERIODS = (10, 20, 50)   # years; JRC v2.1 also has 75, 100, 200 and 500, which the app does not show
NODATA_BELOW = -9998.0       # JRC no data is -9999
TILE_CACHE_TILES = 48        # decoded tiles kept per set: 48 x 256 x 256 x 4 bytes, about 13 MB
BLOCK_CELLS = 24             # squares a side in a block the map loads
MAX_BLOCK_CELLS = 64
MAX_VIEW_SQUARES = 100_000   # squares in a view_cells box (about 28 km a side at 90 m); the real grid has 144 million
MAX_TILE_PX = 512
MAX_TILES = 1 << 18          # entries in TileOffsets and in TileByteCounts: 512 x 512 tiles. The real files have 2,209
MAX_GEO_KEYS = 64            # keys in the GeoKeyDirectory. The real files have 7
MAX_TAG_VALUES = 64          # values in any other tag the reader keeps
MAX_LOADED_SETS = 4          # folders depth_set() keeps loaded at once: the app uses one, tests a few
DEFLATE = (8, 32946)         # Adobe deflate and the older code for it; both are zlib streams
RASTER_DIR = Path(__file__).resolve().parent / "data" / "rasters"
FILE_NAME = re.compile(r"^ID\d+_(?P<grid>[NS]\d{1,2}_[EW]\d{1,3})_RP(?P<rp>\d+)_depth\.tif$")

WIDTH, HEIGHT, BITS, COMPRESSION, SAMPLES, PREDICTOR = 256, 257, 258, 259, 277, 317
TILE_WIDTH, TILE_LENGTH, TILE_OFFSETS, TILE_BYTES, SAMPLE_FORMAT = 322, 323, 324, 325, 339
PIXEL_SCALE, TIE_POINT, TRANSFORM, GEO_KEYS, NODATA = 33550, 33922, 34264, 34735, 42113
TAG_NAMES = {
    WIDTH: "ImageWidth", HEIGHT: "ImageLength", BITS: "BitsPerSample", COMPRESSION: "Compression",
    SAMPLES: "SamplesPerPixel", PREDICTOR: "Predictor", TILE_WIDTH: "TileWidth", TILE_LENGTH: "TileLength",
    TILE_OFFSETS: "TileOffsets", TILE_BYTES: "TileByteCounts", SAMPLE_FORMAT: "SampleFormat",
    PIXEL_SCALE: "ModelPixelScale", TIE_POINT: "ModelTiepoint", TRANSFORM: "ModelTransformation",
    GEO_KEYS: "GeoKeyDirectory", NODATA: "GDAL_NODATA",
}
TAG_LIMITS = {TILE_OFFSETS: MAX_TILES, TILE_BYTES: MAX_TILES, GEO_KEYS: 4 + 4 * MAX_GEO_KEYS}   # others: MAX_TAG_VALUES
FIELD_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i", 11: "f", 12: "d"}
GEO_RULES = (   # key, name, value needed, value when the key is absent
    (1024, "GTModelType", 2, None),         # geographic lat/lon
    (1025, "GTRasterType", 1, 1),           # pixel is area: the tie point is a square's corner
    (2048, "GeographicType", 4326, None),   # WGS 84
)

Depths = dict[str, float | None]
Cell = list   # [south, west, depth10, depth20, depth50]: the town.json `cells` format


class RasterError(Exception):
    """Depth data this module will not use: a file in another layout, a damaged or cut-short one, or one that cannot
    be read. Not a ValueError: a bad argument (a block size, a view) raises that, so neither passes for the other."""


def depth_value(value: float) -> float | None:
    """The build's rule: no data (NODATA_BELOW and under), NaN, zero and below are dry; else metres to 2 decimals.

    One difference: a trace that rounds to 0.00 (0.004) is dry too. The build kept it as 0.0 while its wet-square test
    treated 0.0 as dry, so one square was wet to depths() and dry to block(). The smallest depth in the files we hold
    is 0.10 m and no built value is 0.0 (a test checks), so no square or premise changes.

    `value` is the stored float32 widened to a Python float, so 0.155 (stored as 0.15500000119) rounds to 0.16, as the
    build's numpy read did."""
    if value <= NODATA_BELOW or not 0 < value < math.inf:
        return None
    metres = round(value, 2)
    return metres if metres > 0 else None


# --- the TIFF header ---

def _why(error: OSError) -> str:
    """The operating system's words for a read that failed, such as "No such file or directory"."""
    return error.strerror or type(error).__name__


def _pread(fd: int, size: int, length: int, offset: int, what: str) -> bytes:
    """Exactly `length` bytes from `offset`, or RasterError when the file is too short to hold them."""
    data = os.pread(fd, length, offset) if offset + length <= size else b""
    if len(data) != length:
        raise RasterError(f"{what} lies past the end of the file")
    return data


def _tag_values(fd: int, size: int, tag: int, kind: int, count: int, value: bytes) -> tuple:
    """One directory entry decoded: numbers as a tuple, text as a 1-tuple holding a str. A count over the tag's
    limit is refused first, before anything is read or unpacked."""
    label = f"tag {tag} {TAG_NAMES[tag]}"
    code = FIELD_TYPES.get(kind)
    if code is None or count == 0:
        raise RasterError(f"{label} has field type {kind} and {count} values; need numbers or text")
    limit = TAG_LIMITS.get(tag, MAX_TAG_VALUES)
    if count > limit:
        raise RasterError(f"{label} claims {count} values; at most {limit} are read")
    length = count * struct.calcsize(code)   # _pread refuses anything past the end of the file
    data = value[:length] if length <= 4 else _pread(fd, size, length, struct.unpack("<I", value)[0], label)
    if code == "s":
        return (data.split(b"\0", 1)[0].decode("latin-1"),)
    return struct.unpack(f"<{count}{code}", data)


def _used_entries(table: bytes, count: int) -> list[tuple[int, int, int, bytes]]:
    """(tag, field type, value count, the entry's last 4 bytes) for each entry of a tag this module keeps. A tag
    listed twice is refused: a limit on one entry's count means little if a header may repeat the entry."""
    entries = [struct.unpack_from("<HHI4s", table, 12 * i) for i in range(count)]
    used = [entry for entry in entries if entry[0] in TAG_NAMES]
    twice = sorted(tag for tag, n in Counter(entry[0] for entry in used).items() if n > 1)
    if twice:
        raise RasterError(f"tag {twice[0]} {TAG_NAMES[twice[0]]} is listed twice in the image directory")
    return used


def _read_tags(path: str | Path) -> tuple[dict[int, tuple], int]:
    """(tags, file size): the tags this module uses, from the first image directory. Others are skipped undecoded."""
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        head = _pread(fd, size, 8, 0, "the header")
        if head[:4] != b"II*\x00":
            raise RasterError(f"header {head[:4]!r}; need a little-endian classic TIFF (II, 42)")
        start = struct.unpack_from("<I", head, 4)[0]
        count = struct.unpack("<H", _pread(fd, size, 2, start, "the image directory"))[0]
        table = _pread(fd, size, 12 * count, start + 2, "the image directory")
        return {tag: _tag_values(fd, size, tag, kind, n, value)
                for tag, kind, n, value in _used_entries(table, count)}, size
    finally:
        os.close(fd)


def _whole(values: tuple) -> bool:
    return all(isinstance(n, int) and n >= 0 for n in values)


def _expect(tags: dict[int, tuple], tag: int, ok: Callable[[tuple], bool], need: str,
            default: tuple | None = None) -> tuple:
    """The tag's values when `ok` accepts them (a missing tag counts as `default`); else RasterError naming the tag."""
    found = tags.get(tag, default)
    if found is None or not ok(found):
        shown = "missing" if found is None else str(found[0] if len(found) == 1 else found[:6])
        raise RasterError(f"tag {tag} {TAG_NAMES[tag]} is {shown}; need {need}")
    return found


def _check_layout(tags: dict[int, tuple]) -> None:
    """Refuse anything but the layout JRC ships, naming the tag."""
    _expect(tags, BITS, lambda v: set(v) == {32}, "32 (float32)")
    _expect(tags, SAMPLE_FORMAT, lambda v: set(v) == {3}, "3 (IEEE float)", default=(1,))
    _expect(tags, SAMPLES, lambda v: v == (1,), "1 (one band)", default=(1,))
    _expect(tags, COMPRESSION, lambda v: v[0] in DEFLATE, "8 or 32946 (deflate)", default=(1,))
    _expect(tags, PREDICTOR, lambda v: v == (1,), "1 (no predictor)", default=(1,))
    _expect(tags, WIDTH, lambda v: _whole(v) and v[0] > 0, "a width in pixels")
    _expect(tags, HEIGHT, lambda v: _whole(v) and v[0] > 0, "a height in pixels")
    tile = _expect(tags, TILE_WIDTH, lambda v: _whole(v) and 0 < v[0] <= MAX_TILE_PX,
                   f"a tiled file, tiles of 1 to {MAX_TILE_PX} px")
    _expect(tags, TILE_LENGTH, lambda v: v == tile, f"square tiles, {tile[0]} px like tag {TILE_WIDTH}")
    _expect(tags, PIXEL_SCALE, lambda v: len(v) == 3 and all(0 < s < math.inf for s in v[:2]),
            "positive x and y pixel sizes")
    _expect(tags, TIE_POINT, lambda v: len(v) == 6 and v[:3] == (0, 0, 0) and all(map(math.isfinite, v[3:5])),
            "one tie point, at pixel (0, 0)")
    if TRANSFORM in tags:
        raise RasterError(f"tag {TRANSFORM} {TAG_NAMES[TRANSFORM]} is set; need a pixel scale and tie point only")
    _check_geo_keys(tags)
    _check_nodata(tags)


def _check_geo_keys(tags: dict[int, tuple]) -> None:
    """Lat/lon degrees on WGS 84, with the tie point at a square's corner: the GeoKeys the JRC files carry."""
    keys = _expect(tags, GEO_KEYS, lambda v: _whole(v) and len(v) >= 4 and len(v) >= 4 + 4 * v[3],
                   "a GeoKey directory")
    inline = {keys[i]: keys[i + 3] for i in range(4, 4 + 4 * keys[3], 4) if keys[i + 1] == 0}
    for key, name, need, default in GEO_RULES:
        found = inline.get(key, default)
        if found != need:
            shown = "missing" if found is None else found
            raise RasterError(f"tag {GEO_KEYS} {TAG_NAMES[GEO_KEYS]}: key {key} {name} is {shown}; need {need}")


def _check_nodata(tags: dict[int, tuple]) -> None:
    """A positive no-data value would read as water, so GDAL_NODATA must be NaN, zero or below (JRC: -9999)."""
    text = tags.get(NODATA, ("nan",))[0]
    try:
        value = float(text)
    except ValueError:
        value = math.inf
    if value > 0:
        raise RasterError(f"tag {NODATA} {TAG_NAMES[NODATA]} is {text!r}; need no data at zero or below")


def _tile_table(tags: dict[int, tuple], size: int) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
    """(tiles across, offsets, byte counts): one entry per tile, and every stored tile inside the file."""
    tile = tags[TILE_WIDTH][0]
    across, down = -(-tags[WIDTH][0] // tile), -(-tags[HEIGHT][0] // tile)
    need = f"{across * down} entries, one per tile ({across} x {down})"
    offsets = _expect(tags, TILE_OFFSETS, lambda v: len(v) == across * down and _whole(v), need)
    counts = _expect(tags, TILE_BYTES, lambda v: len(v) == across * down and _whole(v), need)
    past = next((i for i, (o, n) in enumerate(zip(offsets, counts)) if n and o + n > size), None)
    if past is not None:   # the first one: a file cut short loses its last tiles, and the first of them is the cut
        raise RasterError(f"tag {TILE_BYTES} {TAG_NAMES[TILE_BYTES]}: tile {past} ends at byte "
                          f"{offsets[past] + counts[past]}, past the end of the file ({size} bytes)")
    return across, offsets, counts


# --- grids and files ---

@dataclass(frozen=True)
class Grid:
    """A north-up lat/lon grid of squares. Row 0 touches the north edge, column 0 the west edge."""

    name: str      # "N10_E100", from the JRC file name
    x0: float      # west edge, degrees
    y0: float      # north edge, degrees
    px: float      # square width, degrees of longitude
    py: float      # square height, degrees of latitude
    rows: int
    cols: int

    def has(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols

    def cell(self, lon: float, lat: float) -> tuple[int, int] | None:
        """The (row, col) holding a point, or None outside the grid. A point on an edge goes to the square east and
        south of it, so the grid's own east and south edges are outside."""
        y, x = (self.y0 - lat) / self.py, (lon - self.x0) / self.px
        if not (0 <= y < self.rows and 0 <= x < self.cols):   # also false for NaN and infinities
            return None
        return math.floor(y), math.floor(x)

    def bounds(self, row: int, col: int) -> tuple[float, float, float, float]:
        """A square's (west, south, east, north), the order of a view box."""
        return (self.x0 + col * self.px, self.y0 - (row + 1) * self.py,
                self.x0 + (col + 1) * self.px, self.y0 - row * self.py)

    def centre(self, row: int, col: int) -> tuple[float, float]:
        """A square's centre as (lon, lat)."""
        return self.x0 + (col + 0.5) * self.px, self.y0 - (row + 0.5) * self.py

    def as_json(self) -> dict:
        """What a client needs to snap a point to a square the way cell() does."""
        west, south, east, north = self.x0, self.y0 - self.rows * self.py, self.x0 + self.cols * self.px, self.y0
        return {"name": self.name, "x0": self.x0, "y0": self.y0, "px": self.px, "py": self.py,
                "rows": self.rows, "cols": self.cols, "bounds": [west, south, east, north]}


class TileCache:
    """A bounded, thread-safe least-recently-used store of decoded tiles, shared by the files of one set."""

    def __init__(self, limit: int = TILE_CACHE_TILES) -> None:
        self.limit = limit
        self._tiles: OrderedDict[Hashable, array] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._tiles)

    def get(self, key: Hashable) -> array | None:
        with self._lock:
            tile = self._tiles.get(key)
            if tile is not None:
                self._tiles.move_to_end(key)
            return tile

    def put(self, key: Hashable, tile: array) -> array:
        with self._lock:
            self._tiles[key] = tile
            self._tiles.move_to_end(key)
            while len(self._tiles) > self.limit:
                self._tiles.popitem(last=False)
        return tile


@dataclass(frozen=True, eq=False)
class DepthFile:
    """One return period of one grid: single squares from a sparse, deflate-tiled float32 GeoTIFF."""

    path: str
    grid: Grid
    tile: int                                     # tile side, px
    across: int                                   # tiles in a row of tiles
    offsets: tuple[int, ...] = field(repr=False)
    counts: tuple[int, ...] = field(repr=False)   # 0: a tile not stored, which holds no water
    cache: TileCache = field(repr=False)

    @classmethod
    def open(cls, path: str | Path, name: str = "", cache: TileCache | None = None) -> DepthFile:
        """Read and check the file's header. RasterError names the file and the tag for any other layout, and the
        file when it cannot be read. The path is kept absolute: tiles are read later, whatever the working folder is."""
        where = Path(path).absolute()
        try:
            tags, size = _read_tags(where)
            _check_layout(tags)
            across, offsets, counts = _tile_table(tags, size)
        except RasterError as error:
            raise RasterError(f"{where.name}: {error}") from None
        except OSError as error:
            raise RasterError(f"{where.name}: cannot be read ({_why(error)})") from error
        scale, tie = tags[PIXEL_SCALE], tags[TIE_POINT]
        grid = Grid(name, x0=tie[3], y0=tie[4], px=scale[0], py=scale[1], rows=tags[HEIGHT][0], cols=tags[WIDTH][0])
        return cls(str(where), grid, tags[TILE_WIDTH][0], across, offsets, counts,
                   TileCache() if cache is None else cache)

    def at_cell(self, row: int, col: int) -> float | None:
        """Metres at one square, 2 decimals; None when dry, no data or outside the grid."""
        return self.value_at(row, col, depth_value)

    def value_at(self, row: int, col: int, convert: Callable[[float], float | None]) -> float | None:
        """`convert` of the stored value at one square (the float32 widened to a Python float); None outside the grid
        or in a tile not stored. An index outside the grid never wraps to another tile, and the padding of a partial
        tile is never read. app/elevation.py reads heights with its own `convert`, which keeps zero and negatives."""
        if not self.grid.has(row, col):
            return None
        index = (row // self.tile) * self.across + col // self.tile
        if not self.counts[index]:
            return None
        key = (self.path, index)
        tile = self.cache.get(key)
        if tile is None:
            tile = self.cache.put(key, self._decode(index))
        return convert(tile[(row % self.tile) * self.tile + col % self.tile])

    def _decode(self, index: int) -> array:
        """Read one tile with os.pread and inflate it to tile x tile float32 values."""
        want, label = self.tile * self.tile * 4, f"{Path(self.path).name}: tile {index}"
        try:
            fd = os.open(self.path, os.O_RDONLY)
            try:
                chunk = os.pread(fd, self.counts[index], self.offsets[index])
            finally:
                os.close(fd)
        except OSError as error:   # the file was moved, removed or locked since it was opened
            raise RasterError(f"{label} cannot be read ({_why(error)})") from error
        inflater = zlib.decompressobj()
        try:
            data = inflater.decompress(chunk, want + 1)
        except zlib.error as error:
            raise RasterError(f"{label} is not deflate data ({error})") from None
        if len(data) != want or not inflater.eof:
            raise RasterError(f"{label} does not inflate to {self.tile} x {self.tile} float32 values")
        values = array("f", data)
        if sys.byteorder == "big":
            values.byteswap()
        return values


# --- a folder of files ---

def _jrc_files(root: Path) -> list[tuple[str, int, Path]]:
    """(grid, return period, path) of each JRC depth file in the folder, in path order. A missing folder has none."""
    try:
        paths = sorted(root.glob("*.tif")) if root.is_dir() else []
    except OSError as error:
        raise RasterError(f"{root.name}: cannot be listed ({_why(error)})") from error
    return [(m["grid"], int(m["rp"]), path) for path in paths if (m := FILE_NAME.match(path.name))]


def _data_version(layers: tuple[tuple[DepthFile, ...], ...]) -> str:
    """12 hex digits of SHA-256 over each file's name and the SHA-256 of its bytes, in path order."""
    digest = hashlib.sha256()
    for path in sorted(f.path for files in layers for f in files):
        try:
            with open(path, "rb") as stream:
                digest.update(f"{Path(path).name} {hashlib.file_digest(stream, 'sha256').hexdigest()}\n".encode())
        except OSError as error:
            raise RasterError(f"{Path(path).name}: cannot be read ({_why(error)})") from error
    return digest.hexdigest()[:12]


def _grid_files(name: str, paths: dict[int, Path], cache: TileCache) -> tuple[DepthFile, ...]:
    """One grid's files in RETURN_PERIODS order, refused unless all three are there and share one grid."""
    missing = [str(rp) for rp in RETURN_PERIODS if rp not in paths]
    if missing:
        raise RasterError(f"grid {name}: no file for return period {', '.join(missing)}")
    files = tuple(DepthFile.open(paths[rp], name, cache) for rp in RETURN_PERIODS)
    if len({f.grid for f in files}) != 1:
        raise RasterError(f"grid {name}: the return period files do not share one grid")
    return files


def _squares(files: tuple[DepthFile, ...], rows: range, cols: range) -> list[Cell]:
    """The build's cells loop (tools/build_data.py): squares with water in any return period, row by row."""
    grid = files[0].grid
    cells = []
    for r in rows:
        for c in cols:
            d = [f.at_cell(r, c) for f in files]
            if any(d):
                cells.append([round(grid.y0 - (r + 1) * grid.py, 6), round(grid.x0 + c * grid.px, 6), *d])
    return cells


@dataclass(frozen=True, eq=False)
class DepthSet:
    """The depth files of one folder: for each grid, one file per return period."""

    folder: str
    layers: tuple[tuple[DepthFile, ...], ...]   # per grid, sorted by name; files in RETURN_PERIODS order
    data_version: str                           # 12 hex digits of SHA-256 over the files, worked out once at load
    cache: TileCache = field(repr=False)

    @classmethod
    def load(cls, folder: str | Path, cache_tiles: int = TILE_CACHE_TILES) -> DepthSet:
        """Group the folder's JRC files (ID..._{grid}_RP{rp}_depth.tif) by grid; other files are ignored. A missing
        folder gives an empty set. A grid short of a return period, or a file in another layout, raises RasterError.
        Every file is read once here, to work out the data version."""
        root = Path(folder).absolute()   # tiles are read later, whatever the working folder is then
        found = _jrc_files(root)
        keys = [(grid, rp) for grid, rp, _ in found]
        twice = sorted({f"{grid} RP{rp}" for grid, rp in keys if keys.count((grid, rp)) > 1})
        if twice:
            raise RasterError(f"two files for {', '.join(twice)} in {root}")
        cache = TileCache(cache_tiles)
        layers = tuple(_grid_files(name, {rp: path for grid, rp, path in found if grid == name}, cache)
                       for name in sorted({grid for grid, _, _ in found}))
        return cls(str(root), layers, _data_version(layers), cache)

    @property
    def grids(self) -> tuple[Grid, ...]:
        return tuple(files[0].grid for files in self.layers)

    def coverage(self) -> dict:
        """What is loaded, ready for JSON; /api/coverage adds the regions."""
        return {"data_version": self.data_version, "return_periods": list(RETURN_PERIODS),
                "block_cells": BLOCK_CELLS, "grids": [grid.as_json() for grid in self.grids]}

    def locate(self, lon: float, lat: float) -> tuple[Grid, int, int] | None:
        """The grid and the (row, col) of the square holding a point; None where no loaded grid covers it."""
        found = self._find(lon, lat)
        return None if found is None else (found[0][0].grid, found[1], found[2])

    def depths(self, lon: float, lat: float) -> Depths | None:
        """{"10": m, "20": m, "50": m} like premises.json `depth_m`, None for a dry return period; or None when no
        loaded grid covers the point."""
        found = self._find(lon, lat)
        if found is None:
            return None
        files, row, col = found
        return {str(rp): f.at_cell(row, col) for rp, f in zip(RETURN_PERIODS, files)}

    def block(self, grid: str, bi: int, bj: int, size: int = BLOCK_CELLS) -> list[Cell] | None:
        """Wet squares of block (bi, bj), `size` squares a side counted from the grid's north-west corner, in
        town.json `cells` format. A block past the grid's edge is cut there; None when no such block is loaded."""
        if not 0 < size <= MAX_BLOCK_CELLS:
            raise ValueError(f"block size {size} is outside 1 to {MAX_BLOCK_CELLS} squares")
        files = self._layer(grid)
        if files is None or bi < 0 or bj < 0:
            return None
        rows = range(bi * size, min((bi + 1) * size, files[0].grid.rows))
        cols = range(bj * size, min((bj + 1) * size, files[0].grid.cols))
        return _squares(files, rows, cols) if rows and cols else None

    def view_cells(self, view: Sequence[float]) -> list[Cell]:
        """Wet squares of a (west, south, east, north) box, exactly as tools/build_data.py built town.json: from the
        square holding the north-west corner to the one holding the south-east corner, both included.

        ValueError for a box that is empty or reversed (west not under east, south not under north, or a NaN), that is
        not inside one loaded grid, or that holds more than MAX_VIEW_SQUARES squares (counted, not visited)."""
        west, south, east, north = view
        if not (west < east and south < north):   # false for NaN as well
            raise ValueError(f"the view {tuple(view)} is empty or reversed; need west < east and south < north")
        top, bottom = self._find(west, north), self._find(east, south)
        if top is None or bottom is None or top[0] is not bottom[0]:
            raise ValueError(f"the view {tuple(view)} is not inside one loaded grid")
        rows, cols = range(top[1], bottom[1] + 1), range(top[2], bottom[2] + 1)
        squares = len(rows) * len(cols)
        if squares > MAX_VIEW_SQUARES:
            raise ValueError(f"the view covers {squares} squares; at most {MAX_VIEW_SQUARES} are read at once")
        return _squares(top[0], rows, cols)

    def _find(self, lon: float, lat: float) -> tuple[tuple[DepthFile, ...], int, int] | None:
        for files in self.layers:
            cell = files[0].grid.cell(lon, lat)
            if cell is not None:
                return files, cell[0], cell[1]
        return None

    def _layer(self, name: str) -> tuple[DepthFile, ...] | None:
        return next((files for files in self.layers if files[0].grid.name == name), None)


def raster_dir() -> Path:
    """BANJIR_RASTER_DIR when set, else app/data/rasters."""
    return Path(os.environ.get("BANJIR_RASTER_DIR") or RASTER_DIR)


_loaded: dict[str, DepthSet] = {}   # by folder, oldest first; at most MAX_LOADED_SETS
_loading = threading.Lock()


def depth_set() -> DepthSet:
    """The app's depth set for raster_dir(), loaded on first use and kept; restart the app after changing the files.

    Threads arriving together at a cold start wait for one load instead of each making their own. A load that fails
    is not kept, so the next call tries again. A folder with no depth files is logged once, and its empty set kept."""
    folder = str(raster_dir())
    found = _loaded.get(folder)
    if found is not None:   # the usual call: no lock
        return found
    with _loading:
        found = _loaded.get(folder)   # another thread may have finished the load while this one waited
        if found is None:
            found = DepthSet.load(folder)
            _warn_if_empty(found)
            _loaded[folder] = found
            while len(_loaded) > MAX_LOADED_SETS:
                del _loaded[next(iter(_loaded))]
    return found


def _warn_if_empty(loaded: DepthSet) -> None:
    """One warning when the folder gives no grid: the app then covers no point, which would otherwise pass unnoticed."""
    if loaded.grids:
        return
    why = "holds no depth files" if Path(loaded.folder).is_dir() else "does not exist"
    log.warning("The flood model folder %s %s, so no point is covered. Copy the JRC depth files there (see "
                "app/data/rasters/SOURCES.txt) and restart.", loaded.folder, why)


def _forget_sets() -> None:
    """Drop every loaded set, so the next depth_set() reads its folder afresh."""
    with _loading:
        _loaded.clear()


depth_set.cache_clear = _forget_sets   # the public reset, as functools.lru_cache has: for tests, and to reload files
