"""Tiny GeoTIFFs laid out like the JRC flood depth files, for tests of app/raster.py. Standard library only.

The default file is ROWS x COLS squares of PIXEL degrees from ORIGIN (west, north), stored as 3 x 2 deflate tiles of
16 px (three across and two down, so a reader that swaps the two counts, or the width and the height, reads the wrong
tile), little-endian float32, with the JRC GeoKeys. The bottom-left tile is left out (an empty tile). The right and
bottom tiles are partial, and their padding holds water (PADDING), so a reader that strays past the image edge reads
a depth that cannot be right. Row 0 holds the special values: no data, 0, a negative, rounding cases, NaN and a trace
that rounds to 0.00.

    write_depth_set(folder)                       # ID211_N10_E100_RP{10,20,50}_depth.tif
    write_depth_tiff(path, depth_values(), tags={339: (SHORT, (1,))})   # a variant to reject
    write_depth_tiff(path, depth_values(), ifd_first=True)              # laid out like the real files

Two layouts. By default the tile data comes first and the image directory last. With `ifd_first` the directory is at
byte 8, its out-of-line values follow, then the tile data, and the last tile ends at the last byte of the file: the
real files' layout, where a bounds check that is off by one byte refuses a good file.
"""
import math
import struct
import zlib
from collections.abc import Callable
from pathlib import Path


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


ROWS, COLS, TILE = 30, 40, 16
ACROSS, DOWN = ceil_div(COLS, TILE), ceil_div(ROWS, TILE)    # 3 x 2 tiles, the last of each row and column partial
ORIGIN = (100.0, 10.0)        # west edge, north edge
PIXEL = 0.25                  # exact in binary, so square edges are exact
EMPTY_TILE = (DOWN - 1) * ACROSS   # bottom-left (3): no bytes stored (offset 0, count 0), as GDAL writes sparse files
PADDING = 9.99                # past the image edge inside partial tiles
NODATA = -9999.0
TRACE = 0.004                 # rounds to 0.00: JRC's smallest depth is 0.10 m, but a reader must treat it as dry
RETURN_PERIODS = (10, 20, 50)
RP_EXTRA = {10: 0.0, 20: 0.5, 50: 1.0}
SPECIAL = {(0, 0): NODATA, (0, 1): 0.0, (0, 2): -0.5, (0, 3): 1.234, (0, 4): 1.236, (0, 5): 0.155, (0, 6): math.nan,
           (0, 7): TRACE}
ONLY_50 = (1, 0)              # water at 1 in 50 only: 0.42 m
GEO_KEYS = {1024: 2, 1025: 1, 2048: 4326}   # geographic, pixel is area, WGS 84: what the JRC files say

ASCII, SHORT, LONG, RATIONAL, DOUBLE = 2, 3, 4, 5, 12
FORMATS = {SHORT: "H", LONG: "I", RATIONAL: "I", DOUBLE: "d"}
HEADER_BYTES = 8              # the magic number and the offset of the first image directory


def depth_values(rp: int = 10, shift: float = 0.0) -> list[list[float]]:
    """ROWS x COLS depths for one return period: r + c/100 + 0.1 + RP_EXTRA[rp] + shift, except the SPECIAL squares."""
    special = {**SPECIAL, ONLY_50: 0.42 if rp == 50 else NODATA}
    return [[special.get((r, c), r + c / 100 + 0.1 + RP_EXTRA[rp] + shift) for c in range(COLS)] for r in range(ROWS)]


def geo_keys(keys: dict[int, int] = GEO_KEYS) -> tuple[int, ...]:
    """A GeoKeyDirectory (tag 34735) of short keys stored in the directory itself."""
    entries = [value for key in sorted(keys) for value in (key, 0, 1, keys[key])]
    return (1, 1, 0, len(keys), *entries)


def tile_bytes(values: list[list[float]], index: int, tile: int = TILE) -> bytes:
    """One tile as little-endian float32, with PADDING past the image edge."""
    rows, cols = len(values), len(values[0])
    top, left = (index // ceil_div(cols, tile)) * tile, (index % ceil_div(cols, tile)) * tile
    cells = [values[r][c] if r < rows and c < cols else PADDING
             for r in range(top, top + tile) for c in range(left, left + tile)]
    return struct.pack(f"<{len(cells)}f", *cells)


def pack(kind: int, values) -> bytes:
    return values if kind == ASCII else struct.pack(f"<{len(values)}{FORMATS[kind]}", *values)


def directory(tags: dict[int, tuple[int, object]], values_at: int) -> tuple[bytes, bytes]:
    """(the image directory, the out-of-line tag values): entries sorted by tag, a value of more than 4 bytes kept
    outside the entry, on an even byte, in the second part, which the file is to hold from byte `values_at`."""
    entries, outside = [], b""
    for tag in sorted(tags):
        kind, values = tags[tag]
        packed = pack(kind, values)
        count = len(values) // 2 if kind == RATIONAL else len(values)
        if len(packed) <= 4:
            field = packed.ljust(4, b"\0")
        else:
            field = struct.pack("<I", values_at + len(outside))
            outside += packed + bytes(len(packed) % 2)
        entries.append(struct.pack("<HHI", tag, kind, count) + field)
    return struct.pack("<H", len(entries)) + b"".join(entries) + bytes(4), outside


def base_tags(rows: int, cols: int, tile: int, origin, pixel, stored: list[bytes], offsets: list[int]) -> dict:
    return {
        256: (SHORT, (cols,)), 257: (SHORT, (rows,)), 258: (SHORT, (32,)), 259: (SHORT, (8,)), 262: (SHORT, (1,)),
        277: (SHORT, (1,)), 284: (SHORT, (1,)), 317: (SHORT, (1,)), 322: (SHORT, (tile,)), 323: (SHORT, (tile,)),
        324: (LONG, tuple(offsets)), 325: (LONG, tuple(len(chunk) for chunk in stored)), 339: (SHORT, (3,)),
        33550: (DOUBLE, (pixel[0], pixel[1], 0.0)), 33922: (DOUBLE, (0.0, 0.0, 0.0, origin[0], origin[1], 0.0)),
        34735: (SHORT, geo_keys()), 42113: (ASCII, b"-9999\0"),
    }


def place_tiles(stored: list[bytes], start: int, pad_last: bool) -> tuple[list[int], bytes]:
    """(offsets, the joined bytes) of the stored tiles laid from byte `start`. Each tile starts on an even byte; the
    last is padded to one only when `pad_last`, so that without it the data ends exactly at its last byte."""
    last = max((i for i, chunk in enumerate(stored) if chunk), default=-1)
    offsets, data = [], b""
    for i, chunk in enumerate(stored):
        offsets.append(start + len(data) if chunk else 0)
        data += chunk + (bytes(len(chunk) % 2) if pad_last or i != last else b"")
    return offsets, data


def ifd_last_file(header: bytes, stored: list[bytes], tags_at: Callable[[list[int]], dict]) -> bytes:
    """The header, the tile data, the out-of-line values and then the image directory, which the header points to."""
    offsets, data = place_tiles(stored, HEADER_BYTES, pad_last=True)
    ifd, outside = directory(tags_at(offsets), HEADER_BYTES + len(data))
    return header + struct.pack("<I", HEADER_BYTES + len(data) + len(outside)) + data + outside + ifd


def ifd_first_file(header: bytes, stored: list[bytes], tags_at: Callable[[list[int]], dict]) -> bytes:
    """The header, the image directory at byte 8, its out-of-line values and then the tile data to the last byte.

    The directory's size does not depend on the offsets in it, so it is measured once with placeholders."""
    ifd, outside = directory(tags_at([0] * len(stored)), 0)
    offsets, data = place_tiles(stored, HEADER_BYTES + len(ifd) + len(outside), pad_last=False)
    ifd, outside = directory(tags_at(offsets), HEADER_BYTES + len(ifd))
    return header + struct.pack("<I", HEADER_BYTES) + ifd + outside + data


def tiff_bytes(values: list[list[float]], *, tile: int = TILE, origin=ORIGIN, pixel=(PIXEL, PIXEL),
               empty=(EMPTY_TILE,), tags: dict | None = None, chunks: dict[int, bytes] | None = None,
               header: bytes = b"II*\x00", ifd_first: bool = False) -> bytes:
    """A whole file. `tags` replaces tags, or removes them when the value is None; `chunks` replaces the stored
    bytes of a tile by index; `header` replaces the first four bytes; `ifd_first` is the real files' layout."""
    rows, cols = len(values), len(values[0])
    count = ceil_div(rows, tile) * ceil_div(cols, tile)
    stored = [b"" if i in empty else zlib.compress(tile_bytes(values, i, tile)) for i in range(count)]
    stored = [(chunks or {}).get(i, chunk) for i, chunk in enumerate(stored)]

    def tags_at(offsets: list[int]) -> dict:
        merged = {**base_tags(rows, cols, tile, origin, pixel, stored, offsets), **(tags or {})}
        return {tag: value for tag, value in merged.items() if value is not None}

    return (ifd_first_file if ifd_first else ifd_last_file)(header, stored, tags_at)


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
