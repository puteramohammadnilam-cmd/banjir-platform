"""Tiny GeoTIFFs laid out like the JRC flood depth files, for tests of app/raster.py. Standard library only.

The default file is ROWS x COLS squares of PIXEL degrees from ORIGIN (west, north), stored as 3 x 2 deflate tiles of
16 px (three across and two down, so a reader that swaps the two counts, or the width and the height, reads the wrong
tile), little-endian float32, with the JRC GeoKeys. The bottom-left tile is left out (an empty tile). The right and
bottom tiles are partial, and their padding holds water (PADDING), so a reader that strays past the image edge reads
a depth that cannot be right. Row 0 holds the special values: no data, 0, a negative, rounding cases, NaN and a trace
that rounds to 0.00.

    write_depth_set(folder)                       # ID211_N10_E100_RP{10,100,500}_depth.tif
    write_depth_tiff(path, depth_values(), tags={339: (SHORT, (1,))})   # a variant to reject
    write_depth_tiff(path, depth_values(), ifd_first=True)              # laid out like the real files

Two layouts. By default the tile data comes first and the image directory last. With `ifd_first` the directory is at
byte 8, its out-of-line values follow, then the tile data, and the last tile ends at the last byte of the file: the
real files' layout, where a bounds check that is off by one byte refuses a good file.
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import geotiff_write as gw  # noqa: E402  the writer, shared with tools/build_elevation.py
from geotiff_write import (ASCII, DOUBLE, FORMATS, GEO_KEYS, HEADER_BYTES, LONG, RATIONAL, SHORT,  # noqa: E402,F401
                           ceil_div, geo_keys, pack)


ROWS, COLS, TILE = 30, 40, 16
ACROSS, DOWN = ceil_div(COLS, TILE), ceil_div(ROWS, TILE)    # 3 x 2 tiles, the last of each row and column partial
ORIGIN = (100.0, 10.0)        # west edge, north edge
PIXEL = 0.25                  # exact in binary, so square edges are exact
EMPTY_TILE = (DOWN - 1) * ACROSS   # bottom-left (3): no bytes stored (offset 0, count 0), as GDAL writes sparse files
PADDING = 9.99                # past the image edge inside partial tiles
NODATA = -9999.0
TRACE = 0.004                 # rounds to 0.00: JRC's smallest depth is 0.10 m, but a reader must treat it as dry
RETURN_PERIODS = (10, 100, 500)
RP_EXTRA = {10: 0.0, 100: 0.5, 500: 1.0}
SPECIAL = {(0, 0): NODATA, (0, 1): 0.0, (0, 2): -0.5, (0, 3): 1.234, (0, 4): 1.236, (0, 5): 0.155, (0, 6): math.nan,
           (0, 7): TRACE}
ONLY_500 = (1, 0)             # water at 1 in 500 only: 0.42 m


def depth_values(rp: int = 10, shift: float = 0.0) -> list[list[float]]:
    """ROWS x COLS depths for one return period: r + c/100 + 0.1 + RP_EXTRA[rp] + shift, except the SPECIAL squares."""
    special = {**SPECIAL, ONLY_500: 0.42 if rp == 500 else NODATA}
    return [[special.get((r, c), r + c / 100 + 0.1 + RP_EXTRA[rp] + shift) for c in range(COLS)] for r in range(ROWS)]


def tile_bytes(values: list[list[float]], index: int, tile: int = TILE) -> bytes:
    """One tile as little-endian float32, with PADDING past the image edge."""
    return gw.tile_bytes(values, index, tile, PADDING)


def tiff_bytes(values: list[list[float]], *, tile: int = TILE, origin=ORIGIN, pixel=(PIXEL, PIXEL),
               empty=(EMPTY_TILE,), **options) -> bytes:
    """A whole file (geotiff_write.tiff_bytes with this module's defaults). `tags` replaces tags, or removes them when
    the value is None; `chunks` replaces the stored bytes of a tile by index; `header` replaces the first four bytes;
    `ifd_first` is the real files' layout."""
    return gw.tiff_bytes(values, tile=tile, origin=origin, pixel=pixel, padding=PADDING, empty=empty, **options)


def entry_at(data: bytes, tag: int) -> int:
    """The byte where the first directory entry numbered `tag` starts."""
    start = struct.unpack_from("<I", data, 4)[0]
    for at in range(start + 2, start + 2 + 12 * struct.unpack_from("<H", data, start)[0], 12):
        if struct.unpack_from("<H", data, at)[0] == tag:
            return at
    raise KeyError(tag)


def claim_count(data: bytes, tag: int, count: int) -> bytes:
    """The file with the directory entry of `tag` claiming `count` values. Nothing else changes, so the claim can be
    far more than the file holds: what a damaged or hostile header looks like."""
    at = entry_at(data, tag)
    return data[:at + 4] + struct.pack("<I", count) + data[at + 8:]


def renumber(data: bytes, old: int, new: int) -> bytes:
    """The file with the directory entry numbered `old` renumbered `new`: a second entry for a tag already there."""
    at = entry_at(data, old)
    return data[:at] + struct.pack("<H", new) + data[at + 2:]


def write_depth_tiff(path, values: list[list[float]], **options) -> Path:
    path = Path(path)
    path.write_bytes(tiff_bytes(values, **options))
    return path


def write_depth_set(folder, grid: str = "N10_E100", *, origin=ORIGIN, pixel=(PIXEL, PIXEL), shift: float = 0.0,
                    rps=RETURN_PERIODS, **options) -> Path:
    """One grid's return period files, named like the JRC ones (ID211_{grid}_RP{rp}_depth.tif). Returns the folder.
    Other options (such as ifd_first=True) go to every file."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for rp in rps:
        write_depth_tiff(folder / f"ID211_{grid}_RP{rp}_depth.tif", depth_values(rp, shift), origin=origin,
                         pixel=pixel, **options)
    return folder
