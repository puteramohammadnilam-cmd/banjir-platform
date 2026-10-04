"""Write an indexed (palette) PNG, standard library only (struct, zlib).

    write_indexed(path, rows, palette, alpha, depth=4)

`rows` is a list of rows of palette indices, north first; `palette` a list of (r, g, b); `alpha` {index: 0..255} for
the entries that are not fully opaque (a tRNS chunk up to the highest such index; the others stay opaque). Bit depth 1,
2, 4 or 8; each row is packed most significant bits first, padded to a whole byte, and stored with filter type 0
(none, as the PNG book advises for palette images), deflated at level 9 in one IDAT chunk. The same input gives the
same bytes.
"""
from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
PALETTE_COLOUR = 3


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def pack_row(indices: Sequence[int], depth: int) -> bytes:
    """One row's indices packed `depth` bits each, most significant first, the last byte padded with zeros."""
    per_byte = 8 // depth
    out = bytearray()
    for start in range(0, len(indices), per_byte):
        byte = 0
        for k, index in enumerate(indices[start:start + per_byte]):
            byte |= index << (8 - depth * (k + 1))
        out.append(byte)
    return bytes(out)


def png_bytes(rows: Sequence[Sequence[int]], palette: Sequence[tuple[int, int, int]], alpha: dict[int, int],
              depth: int = 4) -> bytes:
    if depth not in (1, 2, 4, 8) or len(palette) > (1 << depth) or not rows:
        raise ValueError(f"{len(palette)} palette entries do not fit bit depth {depth}, or there are no rows")
    width = len(rows[0])
    if any(len(row) != width for row in rows) or any(not 0 <= i < len(palette) for row in rows for i in row):
        raise ValueError("rows differ in length or hold an index outside the palette")
    header = struct.pack(">IIBBBBB", width, len(rows), depth, PALETTE_COLOUR, 0, 0, 0)
    plte = b"".join(bytes(rgb) for rgb in palette)
    trns = bytes(alpha.get(i, 255) for i in range(max(alpha) + 1)) if alpha else b""
    data = zlib.compress(b"".join(b"\x00" + pack_row(row, depth) for row in rows), 9)
    return (SIGNATURE + chunk(b"IHDR", header) + chunk(b"PLTE", plte) + (chunk(b"tRNS", trns) if trns else b"")
            + chunk(b"IDAT", data) + chunk(b"IEND", b""))


def write_indexed(path: str | Path, rows: Sequence[Sequence[int]], palette: Sequence[tuple[int, int, int]],
                  alpha: dict[int, int], depth: int = 4) -> Path:
    path = Path(path)
    path.write_bytes(png_bytes(rows, palette, alpha, depth))
    return path
