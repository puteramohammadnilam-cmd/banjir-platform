"""Read the input GeoTIFFs the index tools use (WorldCover, its NDVI composite, SoilGrids, WorldPop), standard library
only. app/raster.py reads the app's own files and only their one layout; this reader takes a wider set, still refusing
anything else naming the tag, because a misread file gives values that look right and are wrong.

    source = FileSource(path)                       # a whole file on disk
    source = PieceSource(folder)                    # byte ranges of a remote file saved by tools/fetch_indexes.py
    image = open_image(source)
    values = read_window(source, image, top, left, rows, cols, band=0)   # an array, row by row

Read: little-endian classic TIFF; 8 bit unsigned, 16 bit signed or unsigned, 32 bit float samples; one or more samples
per pixel, interleaved (PlanarConfiguration 1) or one plane each (2); tiles or strips; no compression, LZW (5) or deflate
(8, 32946); no predictor (1), horizontal differencing (2, integers) or the floating point predictor (3, with one
sample a pixel or one plane per sample: with interleaved samples libtiff sums its bytes a pixel apart, which is not
undone here); a pixel scale with one tie point on WGS 84 lat/lon (GeoKeys 1024 = 2, 2048 = 4326), pixel is area or
point. Big-endian files, BigTIFF, JPEG and a ModelTransformation are refused.

PieceSource keeps a remote file as the byte ranges actually fetched (HTTP Range), one file per range plus pieces.json
(url, size, and each range's offset, length and SHA-256), so a build runs offline from exactly the bytes downloaded:
each piece is checked against its SHA-256 the first time it is read, and one that does not match is refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
import zlib
from array import array
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import accumulate
from pathlib import Path

WIDTH, HEIGHT, BITS, COMPRESSION, PHOTOMETRIC, STRIP_OFFSETS = 256, 257, 258, 259, 262, 273
SAMPLES, ROWS_PER_STRIP, STRIP_BYTES, PLANAR, PREDICTOR = 277, 278, 279, 284, 317
TILE_WIDTH, TILE_LENGTH, TILE_OFFSETS, TILE_BYTES, SAMPLE_FORMAT = 322, 323, 324, 325, 339
PIXEL_SCALE, TIE_POINT, TRANSFORM, GEO_KEYS, NODATA = 33550, 33922, 34264, 34735, 42113
TAG_NAMES = {
    WIDTH: "ImageWidth", HEIGHT: "ImageLength", BITS: "BitsPerSample", COMPRESSION: "Compression",
    PHOTOMETRIC: "PhotometricInterpretation", STRIP_OFFSETS: "StripOffsets", SAMPLES: "SamplesPerPixel",
    ROWS_PER_STRIP: "RowsPerStrip", STRIP_BYTES: "StripByteCounts", PLANAR: "PlanarConfiguration",
    PREDICTOR: "Predictor", TILE_WIDTH: "TileWidth", TILE_LENGTH: "TileLength", TILE_OFFSETS: "TileOffsets",
    TILE_BYTES: "TileByteCounts", SAMPLE_FORMAT: "SampleFormat", PIXEL_SCALE: "ModelPixelScale",
    TIE_POINT: "ModelTiepoint", TRANSFORM: "ModelTransformation", GEO_KEYS: "GeoKeyDirectory", NODATA: "GDAL_NODATA",
}
FIELD_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}
MAX_VALUES = 1 << 22          # values any one tag may claim: offsets of a 2048 x 2048 tile image, with room
SAMPLE_CODES = {(8, 1): "B", (16, 1): "H", (16, 2): "h", (32, 3): "f"}   # (bits, SampleFormat) -> array typecode
NO_COMPRESSION, LZW = 1, 5
DEFLATE = (8, 32946)
AREA, POINT = 1, 2            # GTRasterType
LZW_CLEAR, LZW_END = 256, 257


class TiffError(Exception):
    """A file this module will not read, said in plain words, naming the tag where one is at fault."""


# --- byte sources ---

class FileSource:
    """A whole file on disk."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.name = self.path.name
        self.size = self.path.stat().st_size

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or offset + length > self.size:
            raise TiffError(f"{self.name}: bytes {offset} to {offset + length} lie past the end of the file")
        with self.path.open("rb") as stream:
            stream.seek(offset)
            return stream.read(length)


class PieceSource:
    """Byte ranges of a remote file, kept in `folder`: r{offset}-{length}.bin and pieces.json. With `getter`
    (url, offset, length) -> bytes, a range not held yet is fetched and saved; without one, it is an error."""

    def __init__(self, folder: str | Path, url: str | None = None,
                 getter: Callable[[str, int, int], bytes] | None = None, size: int | None = None) -> None:
        self.folder, self.getter = Path(folder), getter
        manifest = self.folder / "pieces.json"
        held = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        self.url = url or held.get("url")
        self.size = size or held.get("size")
        self.pieces = [(p["offset"], p["length"]) for p in held.get("pieces", [])]
        self.hashes = {(p["offset"], p["length"]): p.get("sha256") for p in held.get("pieces", [])}
        self.checked: set[tuple[int, int]] = set()   # pieces whose bytes matched their SHA-256 once
        self.name = (self.url or str(self.folder)).rsplit("/", 1)[-1]

    def read(self, offset: int, length: int) -> bytes:
        for start, count in self.pieces:
            if start <= offset and offset + length <= start + count:
                return self._piece(start, count)[offset - start:offset - start + length]
        if self.getter is None:
            raise TiffError(f"{self.name}: bytes {offset} to {offset + length} were not downloaded")
        self.fetch([(offset, length)])
        return self.read(offset, length)

    def fetch(self, ranges: list[tuple[int, int]], join_gap: int = 0) -> int:
        """Fetch the ranges not held yet, joining neighbours no more than join_gap bytes apart into one request.
        Returns the bytes fetched."""
        wanted = sorted(r for r in ranges if not any(s <= r[0] and r[0] + r[1] <= s + n for s, n in self.pieces))
        joined: list[list[int]] = []
        for start, count in wanted:
            if joined and start <= joined[-1][0] + joined[-1][1] + join_gap:
                joined[-1][1] = max(joined[-1][1], start + count - joined[-1][0])
            else:
                joined.append([start, count])
        for start, count in joined:
            data = self.getter(self.url, start, count)
            if len(data) != count:
                raise TiffError(f"{self.name}: asked for {count} bytes at {start}, got {len(data)}")
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / f"r{start}-{count}.bin").write_bytes(data)
            self.pieces.append((start, count))
            self.hashes[(start, count)] = hashlib.sha256(data).hexdigest()
            self.checked.add((start, count))
        self._save()
        return sum(count for _, count in joined)

    def _piece(self, start: int, count: int) -> bytes:
        """A saved piece's bytes, refused unless they match the SHA-256 that pieces.json gives for it."""
        name = f"r{start}-{count}.bin"
        data = (self.folder / name).read_bytes()
        if (start, count) not in self.checked:
            want = self.hashes.get((start, count))
            if not want:
                raise TiffError(f"{self.name}: {name} has no SHA-256 in pieces.json")
            if hashlib.sha256(data).hexdigest() != want:
                raise TiffError(f"{self.name}: {name} does not match its SHA-256 in pieces.json")
            self.checked.add((start, count))
        return data

    def _save(self) -> None:
        pieces = [{"offset": s, "length": n, "sha256": self.hashes[(s, n)]} for s, n in sorted(self.pieces)]
        doc = {"url": self.url, "size": self.size, "pieces": pieces}
        (self.folder / "pieces.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


# --- the header ---

def _entry_values(source, tag: int, kind: int, count: int, inline: bytes) -> tuple:
    label = f"tag {tag} {TAG_NAMES.get(tag, '')}".rstrip()
    code = FIELD_TYPES.get(kind)
    if code is None:
        raise TiffError(f"{source.name}: {label} has field type {kind}; need numbers or text")
    if count > MAX_VALUES:
        raise TiffError(f"{source.name}: {label} claims {count} values; at most {MAX_VALUES} are read")
    length = count * struct.calcsize(code)
    data = inline[:length] if length <= 4 else source.read(struct.unpack("<I", inline)[0], length)
    if code == "s":
        return (data.split(b"\0", 1)[0].decode("latin-1"),)
    return struct.unpack(f"<{count}{code}", data)


def read_tags(source) -> dict[int, tuple]:
    """Every tag of the first image directory whose values this module can decode; others are left out."""
    head = source.read(0, 8)
    if head[:4] != b"II*\x00":
        kind = "BigTIFF" if head[:4] in (b"II+\x00", b"MM\x00+") else "big-endian" if head[:2] == b"MM" else repr(head[:4])
        raise TiffError(f"{source.name}: header is {kind}; need a little-endian classic TIFF (II, 42)")
    start = struct.unpack_from("<I", head, 4)[0]
    count = struct.unpack("<H", source.read(start, 2))[0]
    table = source.read(start + 2, 12 * count)
    tags = {}
    for i in range(count):
        tag, kind, n, inline = struct.unpack_from("<HHI4s", table, 12 * i)
        if tag in TAG_NAMES:
            tags[tag] = _entry_values(source, tag, kind, n, inline)
    return tags


def _need(source, tags: dict, tag: int, ok: Callable[[tuple], bool], need: str, default: tuple | None = None) -> tuple:
    found = tags.get(tag, default)
    if found is None or not ok(found):
        shown = "missing" if found is None else str(found[0] if len(found) == 1 else found[:6])
        raise TiffError(f"{source.name}: tag {tag} {TAG_NAMES[tag]} is {shown}; need {need}")
    return found


def _geo_keys(source, tags: dict) -> dict[int, int]:
    keys = _need(source, tags, GEO_KEYS, lambda v: len(v) >= 4 and len(v) >= 4 + 4 * v[3], "a GeoKey directory")
    inline = {keys[i]: keys[i + 3] for i in range(4, 4 + 4 * keys[3], 4) if keys[i + 1] == 0}
    for key, name, want in ((1024, "GTModelType", 2), (2048, "GeographicType", 4326)):
        if inline.get(key) != want:
            raise TiffError(f"{source.name}: tag {GEO_KEYS} {TAG_NAMES[GEO_KEYS]}: key {key} {name} is "
                            f"{inline.get(key, 'missing')}; need {want}")
    if inline.get(1025, AREA) not in (AREA, POINT):
        raise TiffError(f"{source.name}: tag {GEO_KEYS} {TAG_NAMES[GEO_KEYS]}: key 1025 GTRasterType is "
                        f"{inline[1025]}; need 1 or 2")
    return inline


@dataclass(frozen=True)
class Image:
    """The first image of a file: its size, sample layout, blocks and where its squares are."""

    name: str
    width: int
    height: int
    samples: int
    code: str                  # array typecode of one sample
    compression: int
    predictor: int
    planar: int
    block_w: int
    block_h: int
    offsets: tuple[int, ...] = field(repr=False)
    counts: tuple[int, ...] = field(repr=False)
    west: float                # outer edges of the image (pixel is area), degrees
    north: float
    px: float
    py: float
    nodata: float | None

    @property
    def across(self) -> int:
        return -(-self.width // self.block_w)

    @property
    def per_plane(self) -> int:
        return self.across * -(-self.height // self.block_h)


def _layout(source, tags: dict) -> tuple[str, int, int, int]:
    """(typecode, samples, compression, predictor), after refusing what this module does not read."""
    samples = _need(source, tags, SAMPLES, lambda v: 1 <= v[0] <= 8, "1 to 8 samples", default=(1,))[0]
    bits = _need(source, tags, BITS, lambda v: len(set(v)) == 1 and len(v) in (1, samples), "one size for all samples")
    fmt = _need(source, tags, SAMPLE_FORMAT, lambda v: len(set(v)) == 1, "one format for all samples", default=(1,))
    code = SAMPLE_CODES.get((bits[0], fmt[0]))
    if code is None:
        raise TiffError(f"{source.name}: tag {BITS} {TAG_NAMES[BITS]} {bits[0]} with tag {SAMPLE_FORMAT} "
                        f"{TAG_NAMES[SAMPLE_FORMAT]} {fmt[0]}; need uint8, int16, uint16 or float32")
    compression = _need(source, tags, COMPRESSION, lambda v: v[0] in (NO_COMPRESSION, LZW, *DEFLATE),
                        "1, 5 (LZW), 8 or 32946 (deflate)", default=(1,))[0]
    predictor = _need(source, tags, PREDICTOR, lambda v: v[0] in (1, 2, 3), "1, 2 or 3", default=(1,))[0]
    if (predictor == 3) != (code == "f") and predictor != 1:
        raise TiffError(f"{source.name}: tag {PREDICTOR} {TAG_NAMES[PREDICTOR]} {predictor} does not suit "
                        f"{'float' if code == 'f' else 'integer'} samples")
    return code, samples, compression, predictor


def _blocks(source, tags: dict, width: int, height: int) -> tuple[int, int, tuple, tuple]:
    """(block width, block height, offsets, byte counts) of a tiled or a stripped image."""
    if TILE_WIDTH in tags:
        tile = _need(source, tags, TILE_WIDTH, lambda v: v[0] > 0 and v[0] % 16 == 0, "a multiple of 16")[0]
        down = _need(source, tags, TILE_LENGTH, lambda v: v[0] > 0 and v[0] % 16 == 0, "a multiple of 16")[0]
        return tile, down, _need(source, tags, TILE_OFFSETS, bool, "tile offsets"), \
            _need(source, tags, TILE_BYTES, bool, "tile byte counts")
    rows = _need(source, tags, ROWS_PER_STRIP, lambda v: v[0] > 0, "rows per strip", default=(height,))[0]
    return width, min(rows, height), _need(source, tags, STRIP_OFFSETS, bool, "strip offsets"), \
        _need(source, tags, STRIP_BYTES, bool, "strip byte counts")


def open_image(source) -> Image:
    """The first image of the file, checked (see the module docstring)."""
    tags = read_tags(source)
    width = _need(source, tags, WIDTH, lambda v: v[0] > 0, "a width")[0]
    height = _need(source, tags, HEIGHT, lambda v: v[0] > 0, "a height")[0]
    code, samples, compression, predictor = _layout(source, tags)
    planar = _need(source, tags, PLANAR, lambda v: v[0] in (1, 2), "1 or 2", default=(1,))[0]
    if predictor == 3 and planar == 1 and samples > 1:   # its bytes are summed a pixel apart: not read here
        raise TiffError(f"{source.name}: tag {PREDICTOR} {TAG_NAMES[PREDICTOR]} 3 with {samples} interleaved samples; "
                        "need one sample a pixel, or one plane per sample")
    block_w, block_h, offsets, counts = _blocks(source, tags, width, height)
    planes = samples if planar == 2 else 1
    blocks = -(-width // block_w) * -(-height // block_h) * planes
    if len(offsets) != blocks or len(counts) != blocks:
        raise TiffError(f"{source.name}: {len(offsets)} block offsets and {len(counts)} byte counts; need {blocks}")
    if TRANSFORM in tags:
        raise TiffError(f"{source.name}: tag {TRANSFORM} {TAG_NAMES[TRANSFORM]} is set; need a scale and tie point")
    px, py, _ = _need(source, tags, PIXEL_SCALE, lambda v: len(v) == 3 and v[0] > 0 and v[1] > 0, "pixel sizes")
    tie = _need(source, tags, TIE_POINT, lambda v: len(v) == 6 and v[:2] == (0, 0), "one tie point at pixel (0, 0)")
    point = _geo_keys(source, tags).get(1025, AREA) == POINT
    west, north = (tie[3] - px / 2, tie[4] + py / 2) if point else (tie[3], tie[4])
    nodata = tags.get(NODATA, (None,))[0]
    return Image(source.name, width, height, samples, code, compression, predictor, planar, block_w, block_h,
                 offsets, counts, west, north, px, py, float(nodata) if nodata not in (None, "") else None)


# --- decoding ---

def lzw_decode(data: bytes) -> bytes:
    """TIFF LZW: codes from 9 to 12 bits, most significant bit first, one code early in widening."""
    out, table = bytearray(), [bytes([i]) for i in range(256)] + [b"", b""]
    width, bits, nbits, pos, previous = 9, 0, 0, 0, None
    while True:
        while nbits < width:
            if pos >= len(data):
                return bytes(out)
            bits, nbits, pos = (bits << 8) | data[pos], nbits + 8, pos + 1
        nbits -= width
        code = (bits >> nbits) & ((1 << width) - 1)
        if code == LZW_END:
            return bytes(out)
        if code == LZW_CLEAR:
            table, width, previous = table[:258], 9, None
            continue
        if code < len(table):
            entry = table[code]
            if previous is not None:
                table.append(previous + entry[:1])
        elif code == len(table) and previous is not None:
            entry = previous + previous[:1]
            table.append(entry)
        else:
            raise TiffError(f"LZW code {code} is not in the table ({len(table)} entries)")
        out += entry
        previous = entry
        width = 12 if len(table) + 1 >= 2048 else 11 if len(table) + 1 >= 1024 else 10 if len(table) + 1 >= 512 else 9


def _inflate(image: Image, data: bytes, index: int) -> bytes:
    if image.compression in DEFLATE:
        try:
            return zlib.decompress(data)
        except zlib.error as error:
            raise TiffError(f"{image.name}: block {index} is not deflate data ({error})") from None
    return lzw_decode(data) if image.compression == LZW else data


def _undo_difference(values: array, row: int, stride: int, mask: int) -> array:
    """Horizontal differencing undone, row by row and sample by sample, wrapping at the sample's size."""
    out = array(values.typecode, values)
    for start in range(0, len(values), row):
        for s in range(stride):
            part = out[start + s:start + row:stride]
            out[start + s:start + row:stride] = array(values.typecode, accumulate(part, lambda a, b: (a + b) & mask))
    return out


def undo_float_predictor(data: bytes, width: int, samples: int = 1) -> bytes:
    """TIFF's floating point predictor undone: bytes summed back per row, then each value's four byte planes, most
    significant first, put back together little-endian. Right for one sample a pixel only (open_image refuses more)."""
    count = width * samples
    row_bytes, out = count * 4, bytearray(len(data))
    for start in range(0, len(data), row_bytes):
        row = bytes(accumulate(data[start:start + row_bytes], lambda a, b: (a + b) & 0xFF))
        for plane in range(4):
            out[start + 3 - plane:start + row_bytes:4] = row[plane * count:(plane + 1) * count]
    return bytes(out)


def decode_block(source, image: Image, index: int) -> array:
    """One block's samples (interleaved when PlanarConfiguration is 1), predictor undone, as an array."""
    if not image.counts[index]:
        fill = image.nodata if image.nodata is not None else 0
        return array(image.code, [int(fill) if image.code != "f" else fill]) * _block_len(image)
    data = _inflate(image, source.read(image.offsets[index], image.counts[index]), index)
    samples = image.samples if image.planar == 1 else 1
    size = struct.calcsize(image.code)
    want = _block_len(image) * size
    if len(data) < want:
        rows = len(data) // (image.block_w * samples * size)   # a short last strip
        if rows * image.block_w * samples * size != len(data) or image.block_w != image.width:
            raise TiffError(f"{image.name}: block {index} inflates to {len(data)} bytes; need {want}")
        data += bytes(want - len(data))
    if image.predictor == 3:
        data = undo_float_predictor(data[:want], image.block_w, samples)
    values = array(image.code, data[:want])
    if sys.byteorder == "big":
        values.byteswap()
    if image.predictor == 2:
        unsigned = array(image.code.upper(), values.tobytes()) if image.code == "h" else values
        values = array(image.code, _undo_difference(unsigned, image.block_w * samples, samples,
                                                    (1 << (8 * size)) - 1).tobytes())
    return values


def _block_len(image: Image) -> int:
    return image.block_w * image.block_h * (image.samples if image.planar == 1 else 1)


def read_window(source, image: Image, top: int, left: int, rows: int, cols: int, band: int = 0,
                cache: dict | None = None) -> array:
    """Band `band` of the rows x cols pixels from (top, left), row by row. Each block is decoded once (kept in
    `cache` when one is given, keyed by block index)."""
    if top < 0 or left < 0 or top + rows > image.height or left + cols > image.width or rows <= 0 or cols <= 0:
        raise ValueError(f"window {rows} x {cols} at ({top}, {left}) is not inside {image.height} x {image.width}")
    if not 0 <= band < image.samples:
        raise ValueError(f"band {band} of {image.samples}")
    out = array(image.code, bytes(rows * cols * struct.calcsize(image.code)))
    stride, offset = (image.samples, band) if image.planar == 1 else (1, 0)
    plane = band * image.per_plane if image.planar == 2 else 0
    cache = {} if cache is None else cache
    for bi in range(top // image.block_h, (top + rows - 1) // image.block_h + 1):
        for bj in range(left // image.block_w, (left + cols - 1) // image.block_w + 1):
            index = plane + bi * image.across + bj
            if index not in cache:
                cache[index] = decode_block(source, image, index)
            _copy(cache[index], image, (bi, bj), (top, left, rows, cols), (stride, offset), out)
    return out


def _copy(block: array, image: Image, at: tuple[int, int], window: tuple[int, int, int, int],
          step: tuple[int, int], out: array) -> None:
    (bi, bj), (top, left, rows, cols), (stride, offset) = at, window, step
    c_lo, c_hi = max(left, bj * image.block_w), min(left + cols, (bj + 1) * image.block_w)
    for r in range(max(top, bi * image.block_h), min(top + rows, (bi + 1) * image.block_h)):
        start = ((r - bi * image.block_h) * image.block_w + c_lo - bj * image.block_w) * stride + offset
        out[(r - top) * cols + c_lo - left:(r - top) * cols + c_hi - left] = \
            block[start:start + (c_hi - c_lo) * stride:stride]


def blocks_for(image: Image, top: int, left: int, rows: int, cols: int, band: int = 0) -> list[int]:
    """Indices of the blocks a window touches: what to download before reading it."""
    plane = band * image.per_plane if image.planar == 2 else 0
    return [plane + bi * image.across + bj
            for bi in range(top // image.block_h, (top + rows - 1) // image.block_h + 1)
            for bj in range(left // image.block_w, (left + cols - 1) // image.block_w + 1)]


def pixel_window(image: Image, box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """(top, left, rows, cols) of the pixels whose centres lie in a (west, south, east, north) box, kept inside the
    image."""
    west, south, east, north = box
    left = max(0, math.ceil((west - image.west) / image.px - 0.5))
    right = min(image.width - 1, math.floor((east - image.west) / image.px - 0.5))
    top = max(0, math.ceil((image.north - north) / image.py - 0.5))
    bottom = min(image.height - 1, math.floor((image.north - south) / image.py - 0.5))
    return top, left, bottom - top + 1, right - left + 1
