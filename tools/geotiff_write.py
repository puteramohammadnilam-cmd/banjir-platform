"""Write small GeoTIFFs in the one layout app/raster.py reads. Standard library only (struct, zlib).

Little-endian classic TIFF, one float32 sample, deflate, no predictor, square tiles, a pixel scale and one tie point,
WGS 84 lat/lon with pixel-is-area (the GeoKeys the JRC files carry) and GDAL_NODATA. tests/tiff_fixture.py builds its
test files with it, and tools/build_elevation.py its elevation crops.

    write_tiff(path, values, tile=256, origin=(west, north), pixel=(px, py), padding=-9999.0, level=9)

`values` is a list of rows, north first, each a list of floats. Tiles are deflated one by one; a tile in `empty` is not
stored (offset and byte count 0), as GDAL writes sparse files. The right and bottom tiles are padded past the image
edge with `padding`.

Two layouts. By default the tile data comes first and the image directory last. With `ifd_first` the directory is at
byte 8, its out-of-line values follow, then the tile data, and the last tile ends at the last byte of the file: the
layout of the JRC files.
"""
from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from pathlib import Path

GEO_KEYS = {1024: 2, 1025: 1, 2048: 4326}   # geographic, pixel is area, WGS 84: what the JRC files say
ASCII, SHORT, LONG, RATIONAL, DOUBLE = 2, 3, 4, 5, 12
FORMATS = {SHORT: "H", LONG: "I", RATIONAL: "I", DOUBLE: "d"}
HEADER_BYTES = 8              # the magic number and the offset of the first image directory
NODATA_TEXT = b"-9999\0"


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def geo_keys(keys: dict[int, int] = GEO_KEYS) -> tuple[int, ...]:
    """A GeoKeyDirectory (tag 34735) of short keys stored in the directory itself."""
    entries = [value for key in sorted(keys) for value in (key, 0, 1, keys[key])]
    return (1, 1, 0, len(keys), *entries)


def tile_bytes(values: list[list[float]], index: int, tile: int, padding: float) -> bytes:
    """One tile as little-endian float32, with `padding` past the image edge."""
    rows, cols = len(values), len(values[0])
    top, left = (index // ceil_div(cols, tile)) * tile, (index % ceil_div(cols, tile)) * tile
    cells = [values[r][c] if r < rows and c < cols else padding
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
    """The tags of the layout app/raster.py reads. Sizes go in a SHORT up to 65535 and a LONG past it."""
    size = SHORT if max(rows, cols) <= 0xFFFF else LONG
    return {
        256: (size, (cols,)), 257: (size, (rows,)), 258: (SHORT, (32,)), 259: (SHORT, (8,)), 262: (SHORT, (1,)),
        277: (SHORT, (1,)), 284: (SHORT, (1,)), 317: (SHORT, (1,)), 322: (SHORT, (tile,)), 323: (SHORT, (tile,)),
        324: (LONG, tuple(offsets)), 325: (LONG, tuple(len(chunk) for chunk in stored)), 339: (SHORT, (3,)),
        33550: (DOUBLE, (pixel[0], pixel[1], 0.0)), 33922: (DOUBLE, (0.0, 0.0, 0.0, origin[0], origin[1], 0.0)),
        34735: (SHORT, geo_keys()), 42113: (ASCII, NODATA_TEXT),
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


def tiff_bytes(values: list[list[float]], *, tile: int, origin, pixel, padding: float, empty=(),
               tags: dict | None = None, chunks: dict[int, bytes] | None = None, header: bytes = b"II*\x00",
               ifd_first: bool = False, level: int = -1) -> bytes:
    """A whole file. `tags` replaces tags, or removes them when the value is None; `chunks` replaces the stored
    bytes of a tile by index; `header` replaces the first four bytes; `ifd_first` is the JRC files' layout; `level`
    is zlib's (-1 its default, 9 the smallest)."""
    rows, cols = len(values), len(values[0])
    count = ceil_div(rows, tile) * ceil_div(cols, tile)
    stored = [b"" if i in empty else zlib.compress(tile_bytes(values, i, tile, padding), level) for i in range(count)]
    stored = [(chunks or {}).get(i, chunk) for i, chunk in enumerate(stored)]

    def tags_at(offsets: list[int]) -> dict:
        merged = {**base_tags(rows, cols, tile, origin, pixel, stored, offsets), **(tags or {})}
        return {tag: value for tag, value in merged.items() if value is not None}

    return (ifd_first_file if ifd_first else ifd_last_file)(header, stored, tags_at)


def write_tiff(path, values: list[list[float]], **options) -> Path:
    """tiff_bytes written to `path`; returns the path."""
    path = Path(path)
    path.write_bytes(tiff_bytes(values, **options))
    return path
