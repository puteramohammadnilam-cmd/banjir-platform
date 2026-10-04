"""tools/tiff_read.py on small made-up files, no network: a round trip through tools/geotiff_write.py, uint8 with three
interleaved samples and horizontal differencing, int16 strips in LZW (the TIFF 6.0 spec's own code sequence first),
pixel-is-point tie points, saved byte ranges, and refusals that name the tag."""
import struct
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import geotiff_write as gw  # noqa: E402
import tiff_read as tr  # noqa: E402

ORIGIN, PX = (101.0, 4.0), 1 / 16


def floats(rows=20, cols=24):
    return [[r * 100 + c + 0.25 for c in range(cols)] for r in range(rows)]


def test_a_geotiff_write_file_reads_back_value_for_value(tmp_path):
    values = floats()
    path = gw.write_tiff(tmp_path / "f.tif", values, tile=16, origin=ORIGIN, pixel=(PX, PX), padding=-9999.0)
    source = tr.FileSource(path)
    image = tr.open_image(source)
    assert (image.width, image.height, image.code, image.samples, image.nodata) == (24, 20, "f", 1, -9999.0)
    assert (image.west, image.north, image.px) == (101.0, 4.0, PX)
    got = tr.read_window(source, image, 0, 0, 20, 24)
    assert list(got) == [v for row in values for v in row]
    part = tr.read_window(source, image, 15, 14, 3, 4)   # across a tile corner
    assert list(part) == [values[r][c] for r in range(15, 18) for c in range(14, 18)]


def difference(row: list[int], stride: int, mask: int) -> list[int]:
    return [(row[i] - (row[i - stride] if i >= stride else 0)) & mask for i in range(len(row))]


def uint8_rgb_tiff(tmp_path, nodata=b"255\0") -> tuple[Path, list[list[tuple[int, int, int]]]]:
    rows, cols, tile = 16, 32, 16
    pixels = [[((r * 7 + c) % 256, (r + 3 * c) % 250, 255 if (r, c) == (2, 5) else (r * c) % 256)
               for c in range(cols)] for r in range(rows)]
    chunks = {}
    for t in range(2):
        data = b""
        for r in range(rows):
            flat = [v for c in range(t * tile, (t + 1) * tile) for v in pixels[r][c]]
            data += bytes(difference(flat, 3, 0xFF))
        chunks[t] = zlib.compress(data)
    tags = {258: (gw.SHORT, (8, 8, 8)), 277: (gw.SHORT, (3,)), 339: (gw.SHORT, (1, 1, 1)), 317: (gw.SHORT, (2,)),
            42113: (gw.ASCII, nodata)}
    path = gw.write_tiff(tmp_path / "u8.tif", [[0.0] * cols for _ in range(rows)], tile=tile, origin=ORIGIN,
                         pixel=(PX, PX), padding=0.0, chunks=chunks, tags=tags)
    return path, pixels


def test_uint8_with_three_samples_and_differencing_reads_each_band(tmp_path):
    path, pixels = uint8_rgb_tiff(tmp_path)
    source = tr.FileSource(path)
    image = tr.open_image(source)
    assert (image.code, image.samples, image.predictor, image.nodata) == ("B", 3, 2, 255.0)
    for band in range(3):
        got = tr.read_window(source, image, 1, 10, 4, 12, band=band)
        assert list(got) == [pixels[r][c][band] for r in range(1, 5) for c in range(10, 22)], band


def lzw_encode(data: bytes) -> bytes:
    """A plain TIFF LZW encoder, after libtiff: Clear first, a code wider once the next free entry passes the widest
    code, Clear again when the table reaches 4094 entries, and the last code counted before End of Information."""
    fresh = lambda: ({bytes([i]): i for i in range(256)}, 258)   # noqa: E731
    table, free = fresh()
    codes, width, w = [(256, 9)], 9, b""

    def added(width: int) -> int:
        nonlocal table, free
        free += 1
        if free == 4094:
            codes.append((256, width))
            table, free = fresh()
            return 9
        return width + 1 if free > (1 << width) - 1 else width

    for byte in data:
        if w + bytes([byte]) in table:
            w += bytes([byte])
            continue
        codes.append((table[w], width))
        table[w + bytes([byte])] = free
        width, w = added(width), bytes([byte])
    if w:
        codes.append((table[w], width))
        width = added(width)
    codes.append((257, width))
    bits = "".join(format(code, f"0{size}b") for code, size in codes)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def pack_codes(codes, width=9) -> bytes:
    bits = "".join(format(c, f"0{width}b") for c in codes)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def test_lzw_decodes_the_spec_example():
    """TIFF 6.0, section 13: the pixels 7 7 7 8 8 7 7 6 6 are coded Clear 7 258 8 8 258 6 6 EndOfInformation."""
    assert tr.lzw_decode(pack_codes([256, 7, 258, 8, 8, 258, 6, 6, 257])) == bytes([7, 7, 7, 8, 8, 7, 7, 6, 6])


def test_lzw_widens_its_codes_one_early_and_starts_again_after_a_clear():
    data = bytes((i * 7919 >> 3) % 251 for i in range(30000)) + bytes(range(256)) * 40
    assert tr.lzw_decode(lzw_encode(data)) == data


def int16_strip_tiff(tmp_path, values, rows_per_strip=3) -> Path:
    rows, cols = len(values), len(values[0])
    chunks = {}
    for s in range(-(-rows // rows_per_strip)):
        raw = b""
        for r in range(s * rows_per_strip, min(rows, (s + 1) * rows_per_strip)):
            raw += struct.pack(f"<{cols}H", *difference([v & 0xFFFF for v in values[r]], 1, 0xFFFF))
        chunks[s] = lzw_encode(raw)
    stored = [chunks[s] for s in sorted(chunks)]
    offsets, at = [], 8
    for chunk in stored:
        offsets.append(at)
        at += len(chunk) + len(chunk) % 2
    tags = {256: (gw.SHORT, (cols,)), 257: (gw.SHORT, (rows,)), 258: (gw.SHORT, (16,)), 259: (gw.SHORT, (5,)),
            262: (gw.SHORT, (1,)), 273: (gw.LONG, tuple(offsets)), 277: (gw.SHORT, (1,)),
            278: (gw.SHORT, (rows_per_strip,)), 279: (gw.LONG, tuple(len(c) for c in stored)),
            317: (gw.SHORT, (2,)), 339: (gw.SHORT, (2,)), 33550: (gw.DOUBLE, (PX, PX, 0.0)),
            33922: (gw.DOUBLE, (0.0, 0.0, 0.0, ORIGIN[0], ORIGIN[1], 0.0)), 34735: (gw.SHORT, gw.geo_keys()),
            42113: (gw.ASCII, b"-32768\0")}
    data = b"".join(c + bytes(len(c) % 2) for c in stored)
    ifd, outside = gw.directory(tags, 8 + len(data))
    path = tmp_path / "i16.tif"
    path.write_bytes(b"II*\x00" + struct.pack("<I", 8 + len(data) + len(outside)) + data + outside + ifd)
    return path


def test_int16_strips_in_lzw_with_differencing_keep_their_signs(tmp_path):
    values = [[(r - 4) * 1000 + c * 37 - (32768 if (r, c) == (6, 0) else 0) for c in range(9)] for r in range(8)]
    values[6][0] = -32768
    source = tr.FileSource(int16_strip_tiff(tmp_path, values))
    image = tr.open_image(source)
    assert (image.code, image.block_w, image.block_h, image.compression, image.nodata) == ("h", 9, 3, 5, -32768.0)
    got = tr.read_window(source, image, 0, 0, 8, 9)
    assert list(got) == [v for row in values for v in row]   # the last strip holds 2 rows of 3


def test_a_pixel_is_point_tie_point_sits_at_the_first_square_centre(tmp_path):
    keys = gw.geo_keys({1024: 2, 1025: 2, 2048: 4326})
    path = gw.write_tiff(tmp_path / "p.tif", floats(4, 4), tile=16, origin=ORIGIN, pixel=(PX, PX), padding=0.0,
                         tags={34735: (gw.SHORT, keys)})
    image = tr.open_image(tr.FileSource(path))
    assert (image.west, image.north) == (ORIGIN[0] - PX / 2, ORIGIN[1] + PX / 2)


@pytest.mark.parametrize("tags, words", [
    ({259: (gw.SHORT, (7,))}, "tag 259 Compression"),
    ({317: (gw.SHORT, (2,))}, "tag 317 Predictor"),
    ({258: (gw.SHORT, (64,))}, "tag 258 BitsPerSample"),
    ({34264: (gw.DOUBLE, (1.0,) * 16)}, "tag 34264 ModelTransformation"),
    ({34735: (gw.SHORT, gw.geo_keys({1024: 2, 1025: 1, 2048: 4269}))}, "key 2048 GeographicType"),
])
def test_other_layouts_are_refused_naming_the_tag(tmp_path, tags, words):
    path = gw.write_tiff(tmp_path / "x.tif", floats(4, 4), tile=16, origin=ORIGIN, pixel=(PX, PX), padding=0.0,
                         tags=tags)
    with pytest.raises(tr.TiffError, match=words):
        tr.open_image(tr.FileSource(path))


@pytest.mark.parametrize("head, words", [(b"II+\x00", "BigTIFF"), (b"MM\x00*", "big-endian")])
def test_bigtiff_and_big_endian_files_are_refused(tmp_path, head, words):
    path = gw.write_tiff(tmp_path / "x.tif", floats(4, 4), tile=16, origin=ORIGIN, pixel=(PX, PX), padding=0.0,
                         header=head)
    with pytest.raises(tr.TiffError, match=words):
        tr.open_image(tr.FileSource(path))


def test_saved_byte_ranges_read_offline_exactly_as_the_file(tmp_path):
    path = gw.write_tiff(tmp_path / "f.tif", floats(40, 40), tile=16, origin=ORIGIN, pixel=(PX, PX), padding=0.0,
                         ifd_first=True)                  # the header first, as in a cloud optimised GeoTIFF
    whole, asked = path.read_bytes(), []

    def getter(url, start, length):
        asked.append((start, length))
        return whole[start:start + length]

    online = tr.PieceSource(tmp_path / "pieces", url="https://example.org/f.tif", getter=getter, size=len(whole))
    online.fetch([(0, 512)])
    image = tr.open_image(online)
    online.fetch([(image.offsets[i], image.counts[i]) for i in tr.blocks_for(image, 0, 0, 20, 40)], join_gap=8)
    assert len(asked) == 2                                   # the head, then two rows of tiles in one request
    offline = tr.PieceSource(tmp_path / "pieces")
    assert offline.url == "https://example.org/f.tif"
    got = tr.read_window(offline, tr.open_image(offline), 0, 0, 20, 40)
    assert list(got) == list(tr.read_window(tr.FileSource(path), image, 0, 0, 20, 40))
    with pytest.raises(tr.TiffError, match="not downloaded"):
        tr.read_window(offline, tr.open_image(offline), 39, 39, 1, 1)


def test_the_pixel_window_of_a_box_holds_the_pixels_whose_centres_are_in_it(tmp_path):
    path = gw.write_tiff(tmp_path / "f.tif", floats(20, 24), tile=16, origin=ORIGIN, pixel=(PX, PX), padding=0.0)
    image = tr.open_image(tr.FileSource(path))
    assert tr.pixel_window(image, (101.0, 3.5, 101.25, 4.0)) == (0, 0, 8, 4)
    assert tr.pixel_window(image, (101.04, 3.0, 101.1, 3.97)) == (0, 1, 16, 1)
    assert tr.blocks_for(image, 0, 0, 20, 24) == [0, 1, 2, 3]
