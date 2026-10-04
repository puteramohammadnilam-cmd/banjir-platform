"""Plan card A1: app/raster.py reads the JRC depth GeoTIFFs with the standard library only.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_raster.py tests/test_raster_app.py
Parity with the built JSON:  .venv/bin/python -m pytest -q tests/test_raster.py -k parity -rs -s
tests/test_raster_app.py holds what the app adds around the reader: threads, cold start, the log and HTTP errors.
"""
import ast
import json
import math
import os
import re
import struct
import sys
import time
import zlib
from array import array
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import raster

ROOT = Path(__file__).resolve().parent.parent
GRID = "N10_E100"
SRI_MUDA_VIEW = (101.515, 3.008, 101.550, 3.042)   # the box tools/build_data.py built (west, south, east, north)
DRY = {"10": None, "20": None, "50": None}
TALL = (0.25, 0.5)                                 # squares twice as tall as wide
AFFINE = (0.25, 0.0, 0.0, 100.0, 0.0, -0.25, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
LIMITS = {324: 1 << 18, 325: 1 << 18, 34735: 4 + 4 * 64}   # most values a tag may claim; any other tag: 64


@pytest.fixture
def folder(tmp_path):
    return fx.write_depth_set(tmp_path / "rasters")


@pytest.fixture
def rp10(folder):
    return raster.DepthFile.open(folder / f"ID211_{GRID}_RP10_depth.tif", GRID)


@pytest.fixture
def depth_set(folder):
    return raster.DepthSet.load(folder)


@pytest.fixture
def real_layout(tmp_path):
    """A file laid out like the real ones: its directory at byte 8, then the tile data, the last tile ending at EOF."""
    return fx.write_depth_tiff(tmp_path / "first.tif", fx.depth_values(), ifd_first=True)


def old_read(row: int, col: int) -> float | None:
    """What DepthRaster.at_cell in tools/build_data.py read: no bounds check, so Python's negative indexing wraps."""
    index = ((row // fx.TILE) * fx.ACROSS + col // fx.TILE) % (fx.ACROSS * fx.DOWN)
    if index == fx.EMPTY_TILE:
        return None
    tile = struct.unpack(f"<{fx.TILE ** 2}f", fx.tile_bytes(fx.depth_values(), index))
    return tile[(row % fx.TILE) * fx.TILE + col % fx.TILE]


# --- the fixture file, values and rounding ---

def test_reads_the_grid_and_tile_layout(rp10):
    assert rp10.grid == raster.Grid(GRID, x0=100.0, y0=10.0, px=0.25, py=0.25, rows=30, cols=40)
    assert (rp10.tile, rp10.across, len(rp10.offsets)) == (16, 3, 6)   # three tiles across, two down
    assert [bool(n) for n in rp10.counts] == [i != fx.EMPTY_TILE for i in range(6)]


@pytest.mark.parametrize("cell, metres", [
    ((2, 3), 2.13), ((2, 35), 2.45), ((19, 33), 19.43), ((20, 20), 20.3),   # tiles 0, 2, 5 and 4: across is not down
    ((29, 39), 29.49), ((0, 3), 1.23), ((0, 4), 1.24),
    ((0, 5), 0.16),   # 0.155 is stored as float32 0.15500000119, so it rounds up, as the build's numpy read did
])
def test_values_are_metres_rounded_to_two_decimals(rp10, cell, metres):
    assert rp10.at_cell(*cell) == metres


@pytest.mark.parametrize("cell", [(0, 0), (0, 1), (0, 2), (0, 6), (0, 7)],
                         ids=["no data", "zero", "negative", "nan", "trace of 0.004"])
def test_no_data_zero_negatives_nan_and_a_trace_give_no_water(rp10, cell):
    assert rp10.at_cell(*cell) is None


@pytest.mark.parametrize("value, metres", [
    (-9999.0, None), (-9998.0, None), (-0.01, None), (0.0, None), (float("nan"), None), (float("inf"), None),
    (0.004, None), (0.0049, None),   # a trace that would round to 0.0: dry, as block() already treated it
    (0.005, 0.01), (0.01, 0.01),     # JRC's smallest depth is 0.10 m, so the build never met a trace
    (61.327, 61.33),
])
def test_depth_value_follows_the_build_rule(value, metres):
    assert raster.depth_value(value) == metres


def test_depths_give_the_three_return_periods(depth_set):
    assert depth_set.depths(100.875, 9.375) == {"10": 2.13, "20": 2.63, "50": 3.13}
    assert depth_set.depths(*depth_set.grids[0].centre(*fx.ONLY_50)) == {"10": None, "20": None, "50": 0.42}


def test_depths_and_block_agree_a_trace_is_dry_in_both(depth_set):
    assert depth_set.depths(*depth_set.grids[0].centre(0, 7)) == DRY
    wet = {tuple(cell[:2]) for cell in depth_set.block(GRID, 0, 0, 16)}
    assert (9.75, 102.0) in wet and (9.75, 101.75) not in wet   # the square after the trace is wet, the trace is not


def test_an_empty_tile_is_covered_but_dry(depth_set):
    assert depth_set.depths(*depth_set.grids[0].centre(20, 5)) == DRY
    assert depth_set.block(GRID, 1, 0, 16) == []


# --- edges, negative indexes and padding ---

@pytest.mark.parametrize("lon, lat, cell", [
    (100.0, 10.0, (0, 0)),                    # the north-west corner is inside
    (100.75, 9.5, (2, 3)),                    # on a square's corner: the square to the east and south
    (100.75, 9.375, (2, 3)),                  # on a west edge: east
    (100.875, 9.5, (2, 3)),                   # on a north edge: south
    (110.0 - 1e-9, 2.5 + 1e-9, (29, 39)),     # just inside the south-east corner
    (100.0 - 1e-9, 9.0, None),                # west of the west edge
    (101.0, 10.0 + 1e-9, None),               # north of the north edge
    (110.0, 9.0, None),                       # on the east edge: the square east of it is not in the grid
    (101.0, 2.5, None),                       # on the south edge: likewise south
    (float("nan"), 9.0, None), (101.0, float("inf"), None),
    (1e308, 9.0, None),                       # finite, but the column number overflows to infinity
])
def test_points_on_and_past_every_edge(depth_set, lon, lat, cell):
    assert depth_set.grids[0].cell(lon, lat) == cell
    assert (depth_set.depths(lon, lat) is None) == (cell is None)


@pytest.mark.parametrize("row, col", [
    (0, -1), (-1, 16), (-16, -16), (-1, -1),                         # negative: the build wrapped to another tile
    (0, 40), (0, 47), (29, 40), (30, 39), (30, 16), (31, 47), (31, 31),   # past the east and south edges: padding
])
def test_indexes_outside_the_grid_are_not_covered(rp10, row, col):
    assert old_read(row, col) > 0   # the build read water here: another tile's square, or padding
    assert rp10.at_cell(row, col) is None


def test_square_bounds_and_centre_round_trip(depth_set):
    grid = depth_set.grids[0]
    assert grid.bounds(2, 3) == (100.75, 9.25, 101.0, 9.5)
    assert grid.centre(2, 3) == (100.875, 9.375)
    assert all(grid.cell(*grid.centre(r, c)) == (r, c) for r in range(fx.ROWS) for c in range(fx.COLS))


# --- squares that are not square: the width is for columns and the height for rows, everywhere ---

@pytest.fixture
def tall(tmp_path):
    return raster.DepthSet.load(fx.write_depth_set(tmp_path / "tall", pixel=TALL))


def test_tall_squares_use_their_height_for_rows_and_their_width_for_columns(tall):
    grid = tall.grids[0]
    assert (grid.px, grid.py) == TALL
    assert grid.cell(100.3, 9.4) == (1, 1)             # with the width for rows too it would be row 2
    assert grid.bounds(1, 1) == (100.25, 9.0, 100.5, 9.5)
    assert grid.centre(2, 3) == (100.875, 8.75)
    assert all(grid.cell(*grid.centre(r, c)) == (r, c) for r in range(fx.ROWS) for c in range(fx.COLS))
    assert tall.depths(*grid.centre(2, 3)) == {"10": 2.13, "20": 2.63, "50": 3.13}


def test_tall_squares_give_the_json_a_client_snaps_with(tall):
    assert tall.grids[0].as_json() == {"name": GRID, "x0": 100.0, "y0": 10.0, "px": 0.25, "py": 0.5, "rows": 30,
                                       "cols": 40, "bounds": [100.0, -5.0, 110.0, 10.0]}
    assert tall.coverage()["grids"] == [tall.grids[0].as_json()]


def test_a_block_of_tall_squares_gives_each_square_its_own_south_and_west(tall):
    cells = tall.block(GRID, 0, 0, 4)
    assert (cells[0], cells[1], cells[-1]) == ([9.5, 100.75, 1.23, 1.23, 1.23],    # (0, 3)
                                               [9.0, 100.0, None, None, 0.42],     # (1, 0)
                                               [8.0, 100.75, 3.13, 3.63, 4.13])    # (3, 3)
    assert tall.view_cells((100.0, 8.0, 101.0, 10.0)) == tall.block(GRID, 0, 0, 5)


# --- formats ---

def geo(changes: dict[int, int | None]) -> dict:
    """A GeoKeyDirectory tag with keys changed, or removed when the value is None."""
    keys = {**fx.GEO_KEYS, **changes}
    return {34735: (fx.SHORT, fx.geo_keys({k: v for k, v in keys.items() if v is not None}))}


def scale(*sizes: float) -> dict:
    return {33550: (fx.DOUBLE, (*sizes, 0.0))}


def tie(*raster_point: float, x: float = 100.0, y: float = 10.0) -> dict:
    return {33922: (fx.DOUBLE, (*raster_point, x, y, 0.0))}


LAYOUTS = [
    pytest.param({"header": b"MM\x00*"}, "header", id="big-endian"),
    pytest.param({"header": b"II+\x00"}, "header", id="BigTIFF"),
    pytest.param({"tags": {258: (fx.SHORT, (64,))}}, "tag 258 BitsPerSample", id="float64"),
    pytest.param({"tags": {339: (fx.SHORT, (1,))}}, "tag 339 SampleFormat", id="integers"),
    pytest.param({"tags": {339: None}}, "tag 339 SampleFormat", id="no sample format"),
    pytest.param({"tags": {259: (fx.SHORT, (1,))}}, "tag 259 Compression", id="uncompressed"),
    pytest.param({"tags": {259: (fx.SHORT, (5,))}}, "tag 259 Compression", id="LZW"),
    pytest.param({"tags": {317: (fx.SHORT, (3,))}}, "tag 317 Predictor", id="predictor"),
    pytest.param({"tags": {277: (fx.SHORT, (2,))}}, "tag 277 SamplesPerPixel", id="two samples"),
    pytest.param({"tags": {322: None, 323: None}}, "tag 322 TileWidth", id="strips"),
    pytest.param({"tags": {323: (fx.SHORT, (32,))}}, "tag 323 TileLength", id="oblong tiles"),
    pytest.param({"tags": {322: (fx.SHORT, (1024,)), 323: (fx.SHORT, (1024,))}}, "tag 322 TileWidth", id="huge tiles"),
    pytest.param({"tags": geo({2048: 4269})}, "key 2048 GeographicType", id="NAD83"),
    pytest.param({"tags": geo({2048: None})}, "key 2048 GeographicType", id="no datum"),
    pytest.param({"tags": geo({1024: 1})}, "key 1024 GTModelType", id="projected"),
    pytest.param({"tags": geo({1025: 2})}, "key 1025 GTRasterType", id="pixel is point"),
    pytest.param({"tags": {34735: None}}, "tag 34735 GeoKeyDirectory", id="no GeoKeys"),
    pytest.param({"tags": {33550: None}}, "tag 33550 ModelPixelScale", id="no pixel size"),
    pytest.param({"tags": scale(0.25, -0.25)}, "tag 33550 ModelPixelScale", id="negative height"),
    pytest.param({"tags": scale(-0.25, 0.25)}, "tag 33550 ModelPixelScale", id="negative width"),
    pytest.param({"tags": scale(0.0, 0.25)}, "tag 33550 ModelPixelScale", id="no width"),
    pytest.param({"tags": scale(0.25, 0.0)}, "tag 33550 ModelPixelScale", id="no height"),
    pytest.param({"tags": scale(math.inf, 0.25)}, "tag 33550 ModelPixelScale", id="infinite width"),
    pytest.param({"tags": scale(0.25, math.nan)}, "tag 33550 ModelPixelScale", id="height not a number"),
    pytest.param({"tags": {33550: (fx.DOUBLE, (0.25, 0.25))}}, "tag 33550 ModelPixelScale", id="two pixel sizes"),
    pytest.param({"tags": {33922: None}}, "tag 33922 ModelTiepoint", id="no tie point"),
    pytest.param({"tags": {33922: (fx.DOUBLE, (0, 0, 0, 100, 10, 0) * 2)}}, "tag 33922 ModelTiepoint", id="two"),
    pytest.param({"tags": tie(1, 0, 0)}, "tag 33922 ModelTiepoint", id="tie point at pixel column 1"),
    pytest.param({"tags": tie(0, 1, 0)}, "tag 33922 ModelTiepoint", id="tie point at pixel row 1"),
    pytest.param({"tags": tie(0, 0, 1)}, "tag 33922 ModelTiepoint", id="tie point at height 1"),
    pytest.param({"tags": tie(0.5, 0.5, 0)}, "tag 33922 ModelTiepoint", id="tie point at a pixel centre"),
    pytest.param({"tags": tie(0, 0, 0, x=math.nan)}, "tag 33922 ModelTiepoint", id="tie point with no longitude"),
    pytest.param({"tags": tie(0, 0, 0, y=math.inf)}, "tag 33922 ModelTiepoint", id="tie point at infinite latitude"),
    pytest.param({"tags": {34264: (fx.DOUBLE, AFFINE)}}, "tag 34264 ModelTransformation", id="affine"),
    pytest.param({"tags": {42113: (fx.ASCII, b"9999\0")}}, "tag 42113 GDAL_NODATA", id="positive no-data"),
    pytest.param({"tags": {42113: (fx.ASCII, b"none\0")}}, "tag 42113 GDAL_NODATA", id="no-data not a number"),
    pytest.param({"tags": {339: (fx.RATIONAL, (3, 1))}}, "tag 339 SampleFormat has field type 5", id="odd type"),
    pytest.param({"tags": {324: (fx.LONG, (8, 8, 8))}}, "tag 324 TileOffsets", id="too few tiles"),
    pytest.param({"tags": {325: (fx.LONG, (10 ** 6,) * 6)}}, "tag 325 TileByteCounts: tile 0 ends at byte",
                 id="past end"),
]


@pytest.mark.parametrize("options, named", LAYOUTS)
def test_unsupported_layouts_are_rejected_naming_the_tag(tmp_path, options, named):
    path = fx.write_depth_tiff(tmp_path / "bad.tif", fx.depth_values(), **options)
    with pytest.raises(raster.RasterError, match=rf"^bad\.tif: .*{named}"):
        raster.DepthFile.open(path)


@pytest.mark.parametrize("cut, what", [(slice(0, 4), "the header"), (slice(0, -20), "the image directory")])
def test_a_cut_short_file_is_refused(tmp_path, cut, what):
    path = tmp_path / "short.tif"
    path.write_bytes(fx.tiff_bytes(fx.depth_values())[cut])   # the image directory is written last
    with pytest.raises(raster.RasterError, match=f"^short.tif: {what} lies past the end of the file"):
        raster.DepthFile.open(path)


def test_the_old_deflate_code_and_unused_tags_are_accepted(tmp_path):
    extra = {259: (fx.SHORT, (32946,)), 282: (fx.RATIONAL, (72, 1)), 305: (fx.ASCII, b"GDAL\0")}
    path = fx.write_depth_tiff(tmp_path / "old.tif", fx.depth_values(), tags=extra)
    assert raster.DepthFile.open(path).at_cell(2, 3) == 2.13


@pytest.mark.parametrize("chunk", [b"not deflate data", zlib.compress(bytes(100))], ids=["not deflate", "wrong size"])
def test_a_tile_that_does_not_inflate_to_a_full_tile_is_an_error(tmp_path, chunk):
    path = fx.write_depth_tiff(tmp_path / "broken.tif", fx.depth_values(), chunks={0: chunk})
    with pytest.raises(raster.RasterError, match=r"broken\.tif: tile 0"):
        raster.DepthFile.open(path).at_cell(2, 3)


# --- how a tag's values are stored: inside its 4-byte directory entry, or elsewhere in the file ---

WIDE = raster.Grid("", 100.0, 10.0, 0.25, 0.25, 30, 40)


@pytest.mark.parametrize("tags", [
    {256: (fx.LONG, (40,)), 257: (fx.LONG, (30,)), 322: (fx.LONG, (16,)), 323: (fx.LONG, (16,))},   # a LONG: 4 bytes
    {258: (fx.SHORT, (32, 32))},               # two SHORTs: 4 bytes, still inside the entry
    {258: (fx.SHORT, (32, 32, 32))},           # three: 6 bytes, so the entry holds an offset instead
    {42113: (fx.ASCII, b"0\0")}, {42113: (fx.ASCII, b"-9999\0")},   # 2 and 6 bytes of text
], ids=["LONGs", "two SHORTs", "three SHORTs", "short text", "long text"])
def test_values_are_read_whether_or_not_they_fit_in_the_entry(tmp_path, tags):
    opened = raster.DepthFile.open(fx.write_depth_tiff(tmp_path / "t.tif", fx.depth_values(), tags=tags))
    assert (opened.grid, opened.tile, opened.at_cell(2, 3)) == (WIDE, 16, 2.13)


def test_a_file_of_one_tile_keeps_its_one_offset_and_count_inside_the_entries(tmp_path):
    path = fx.write_depth_tiff(tmp_path / "one.tif", fx.depth_values(), tile=64)
    opened = raster.DepthFile.open(path)
    assert (opened.across, len(opened.offsets), opened.at_cell(29, 39), opened.at_cell(30, 0)) == (1, 1, 29.49, None)


# --- a header cannot make the reader decode more than a depth file ever holds ---

@pytest.mark.parametrize("tag", sorted(raster.TAG_NAMES), ids=raster.TAG_NAMES.get)
def test_a_header_claiming_too_many_values_is_refused_before_they_are_read(tmp_path, tag):
    whole = fx.tiff_bytes(fx.depth_values(), tags={34264: (fx.DOUBLE, AFFINE)})   # holds every tag the reader keeps
    most = LIMITS.get(tag, 64)
    for claim in (most + 1, 2 ** 32 - 1):
        path = tmp_path / "huge.tif"
        path.write_bytes(fx.claim_count(whole, tag, claim))
        message = rf"^huge\.tif: tag {tag} {raster.TAG_NAMES[tag]} claims {claim} values; at most {most} are read"
        with pytest.raises(raster.RasterError, match=message):
            raster.DepthFile.open(path)


def test_values_up_to_the_cap_are_read_and_one_more_key_is_not(tmp_path):
    keys = {**fx.GEO_KEYS, **{3000 + i: 1 for i in range(61)}}   # 64 keys: 4 + 4 * 64 = 260 values
    full = {258: (fx.SHORT, (32,) * 64), 34735: (fx.SHORT, fx.geo_keys(keys))}
    assert raster.DepthFile.open(fx.write_depth_tiff(tmp_path / "full.tif", fx.depth_values(), tags=full)).grid == WIDE
    over = {**full, 34735: (fx.SHORT, fx.geo_keys({**keys, 4000: 1}))}
    with pytest.raises(raster.RasterError, match="tag 34735 GeoKeyDirectory claims 264 values; at most 260"):
        raster.DepthFile.open(fx.write_depth_tiff(tmp_path / "over.tif", fx.depth_values(), tags=over))


def test_a_tile_table_of_exactly_the_cap_is_read(tmp_path):
    tiles, side = 1 << 18, 16 * 512      # 512 x 512 tiles of 16 px, none of them stored
    table = {256: (fx.LONG, (side,)), 257: (fx.LONG, (side,)), 324: (fx.LONG, (0,) * tiles),
             325: (fx.LONG, (0,) * tiles)}
    opened = raster.DepthFile.open(fx.write_depth_tiff(tmp_path / "big.tif", fx.depth_values(), tags=table))
    assert (opened.grid.rows, opened.grid.cols) == (side, side)
    assert (len(opened.offsets), opened.at_cell(100, 100)) == (tiles, None)


def test_a_tag_listed_twice_is_refused(tmp_path):
    path = tmp_path / "twice.tif"   # the unused tag 262 becomes a second TileOffsets, which would double the work
    path.write_bytes(fx.renumber(fx.tiff_bytes(fx.depth_values()), 262, 324))
    with pytest.raises(raster.RasterError, match=r"^twice\.tif: tag 324 TileOffsets is listed twice"):
        raster.DepthFile.open(path)


# --- the end of the file: the real files' last tile ends at their last byte ---

def test_a_file_with_its_directory_first_and_its_last_tile_at_the_last_byte_opens(real_layout):
    data = real_layout.read_bytes()
    opened = raster.DepthFile.open(real_layout, GRID)
    assert struct.unpack_from("<I", data, 4)[0] == 8
    assert max(o + n for o, n in zip(opened.offsets, opened.counts)) == len(data)   # the bound is inclusive
    assert (opened.at_cell(29, 39), opened.at_cell(20, 20)) == (29.49, 20.3)


def test_both_layouts_read_the_same_squares(tmp_path, real_layout, depth_set):
    one = raster.DepthFile.open(real_layout, GRID)
    other = raster.DepthFile.open(fx.write_depth_tiff(tmp_path / "last.tif", fx.depth_values()), GRID)
    squares = [(r, c) for r in range(fx.ROWS) for c in range(fx.COLS)]
    assert [one.at_cell(*square) for square in squares] == [other.at_cell(*square) for square in squares]
    real_like = raster.DepthSet.load(fx.write_depth_set(tmp_path / "first", ifd_first=True))
    assert real_like.block(GRID, 0, 0, raster.MAX_BLOCK_CELLS) == depth_set.block(GRID, 0, 0, raster.MAX_BLOCK_CELLS)


def test_a_file_one_byte_short_names_its_last_tile(tmp_path, real_layout):
    data = real_layout.read_bytes()
    short = tmp_path / "short.tif"
    short.write_bytes(data[:-1])
    message = (rf"^short\.tif: tag 325 TileByteCounts: tile 5 ends at byte {len(data)}, "
               rf"past the end of the file \({len(data) - 1} bytes\)$")
    with pytest.raises(raster.RasterError, match=message):
        raster.DepthFile.open(short)


def test_a_truncated_file_names_the_first_tile_past_its_end_not_the_whole_tuple(tmp_path, real_layout):
    whole = raster.DepthFile.open(real_layout, GRID)
    short = tmp_path / "short.tif"
    short.write_bytes(real_layout.read_bytes()[:whole.offsets[4] + whole.counts[4] // 2])   # ends inside tile 4; 5 is gone
    ends = whole.offsets[4] + whole.counts[4]
    message = (rf"^short\.tif: tag 325 TileByteCounts: tile 4 ends at byte {ends}, "
               rf"past the end of the file \({short.stat().st_size} bytes\)$")   # one tile, the first, not the lot
    with pytest.raises(raster.RasterError, match=message):
        raster.DepthFile.open(short)


def test_an_opened_file_keeps_its_absolute_path(monkeypatch, folder):
    name = f"ID211_{GRID}_RP10_depth.tif"
    monkeypatch.chdir(folder)
    opened = raster.DepthFile.open(name, GRID)
    monkeypatch.chdir(folder.parent.parent)       # not where the file is
    assert os.path.isabs(opened.path) and os.path.samefile(opened.path, folder / name)
    assert opened.at_cell(2, 3) == 2.13           # the tile is read now, from wherever the working folder is


# --- several grids, blocks and the build's cells loop ---

@pytest.fixture
def two(tmp_path):
    """Two grids side by side: this one to longitude 110, the next from there."""
    fx.write_depth_set(tmp_path, GRID)
    fx.write_depth_set(tmp_path, "N10_E110", origin=(110.0, 10.0), shift=50.0)
    return raster.DepthSet.load(tmp_path)


def test_two_grids_route_to_their_own_files(two):
    assert [g.name for g in two.grids] == [GRID, "N10_E110"]
    assert two.depths(100.875, 9.375) == {"10": 2.13, "20": 2.63, "50": 3.13}
    assert two.depths(110.875, 9.375) == {"10": 52.13, "20": 52.63, "50": 53.13}
    assert two.depths(109.9, 9.0) == {"10": 4.49, "20": 4.99, "50": 5.49}   # the last column of the first grid
    assert two.depths(120.0, 9.0) is None and two.depths(105.0, 10.5) is None   # east and north of both
    assert two.locate(110.875, 9.375) == (two.grids[1], 2, 3)
    assert two.locate(110.0, 9.0) == (two.grids[1], 4, 0)   # the shared edge goes east, as every edge does
    assert two.block("N10_E110", 0, 0, 4)[-1] == [9.0, 110.75, 53.13, 53.63, 54.13]


def test_a_block_holds_only_wet_squares_in_town_cells_format(depth_set):
    cells = depth_set.block(GRID, 0, 0, 4)
    assert len(cells) == 13                                   # 16 squares less no data, zero and negative
    assert cells[0] == [9.75, 100.75, 1.23, 1.23, 1.23]       # (0, 3), [south, west, d10, d20, d50]
    assert cells[1] == [9.5, 100.0, None, None, 0.42]         # (1, 0): water at 1 in 50 only
    assert cells[-1] == [9.0, 100.75, 3.13, 3.63, 4.13]       # (3, 3)


def test_a_block_stops_at_the_grid_edge(depth_set):
    cells = depth_set.block(GRID, 1, 2, 16)                   # rows 16 to 29 and columns 32 to 39: both edges cut it
    assert len(cells) == 14 * 8
    assert cells[0] == [5.75, 108.0, 16.42, 16.92, 17.42]     # (16, 32)
    assert cells[-1] == [2.5, 109.75, 29.49, 29.99, 30.49]    # (29, 39)
    assert all(south >= 2.5 and west < 110.0 for south, west, *_ in cells)   # no padding squares
    assert len(depth_set.block(GRID, 0, 2, 16)) == 16 * 8


def test_blocks_past_the_grid_or_of_an_unknown_grid_are_not_covered(depth_set):
    assert depth_set.block(GRID, 2, 0, 16) is None
    assert depth_set.block(GRID, 0, 3, 16) is None
    assert depth_set.block(GRID, -1, 0) is None
    assert depth_set.block("N10_E110", 0, 0) is None


@pytest.mark.parametrize("size", [0, -24, raster.MAX_BLOCK_CELLS + 1])
def test_the_block_size_is_capped(depth_set, size):
    with pytest.raises(ValueError, match="block size"):
        depth_set.block(GRID, 0, 0, size)


def test_the_largest_block_covers_the_whole_fixture(depth_set):
    stored = 16 * 40 + 14 * 16 + 14 * 8   # tiles 0 to 2, 4 and 5; tile 3 is empty
    assert len(depth_set.block(GRID, 0, 0, raster.MAX_BLOCK_CELLS)) == stored - 5   # less 5 dry special squares


# --- a view, as the build used it ---

def test_view_cells_repeat_the_build_loop(depth_set):
    assert depth_set.view_cells((100.0, 9.0, 101.0, 10.0)) == depth_set.block(GRID, 0, 0, 5)
    with pytest.raises(ValueError, match="not inside one loaded grid"):
        depth_set.view_cells((99.0, 9.0, 101.0, 10.0))


@pytest.mark.parametrize("view", [
    (101.0, 9.0, 100.0, 10.0), (100.0, 10.0, 101.0, 9.0),         # west of east, south below north
    (100.5, 9.0, 100.5, 10.0), (100.0, 9.5, 101.0, 9.5),          # no width, no height
    (math.nan, 9.0, 101.0, 10.0), (100.0, 9.0, 101.0, math.nan),
], ids=["west past east", "south past north", "no width", "no height", "west nan", "north nan"])
def test_a_reversed_or_empty_view_is_refused_not_answered_with_no_squares(depth_set, view):
    with pytest.raises(ValueError, match="empty or reversed"):
        depth_set.view_cells(view)


def test_a_view_of_too_many_squares_is_refused_before_any_is_read(depth_set, monkeypatch):
    monkeypatch.setattr(raster, "MAX_VIEW_SQUARES", 25)
    assert depth_set.view_cells((100.0, 9.0, 101.0, 10.0)) == depth_set.block(GRID, 0, 0, 5)   # 5 x 5 = 25: allowed
    with pytest.raises(ValueError, match=r"30 squares.*at most 25"):
        depth_set.view_cells((100.0, 9.0, 101.25, 10.0))                   # 5 x 6


def test_a_view_across_two_grids_is_refused(two):
    with pytest.raises(ValueError, match="not inside one loaded grid"):
        two.view_cells((109.5, 9.0, 110.5, 10.0))       # north-west corner in one grid, south-east in the next
    assert two.view_cells((110.0, 9.0, 111.0, 10.0)) == two.block("N10_E110", 0, 0, 5)   # all in the next grid: fine


# --- caches, loading and the app's cached set ---

def test_the_tile_cache_drops_the_least_recently_used():
    cache = raster.TileCache(limit=2)
    first, second, third = (array("f", [n]) for n in (1, 2, 3))
    cache.put("a", first)
    cache.put("b", second)
    assert cache.get("a") is first        # now b is the least recently used
    cache.put("c", third)
    assert (len(cache), cache.get("b"), cache.get("a"), cache.get("c")) == (2, None, first, third)


def test_reads_stay_within_the_tile_cache_limit(folder):
    small = raster.DepthSet.load(folder, cache_tiles=2)
    for cell in [(2, 3), (2, 20), (20, 20), (2, 3)]:
        assert small.depths(*small.grids[0].centre(*cell))["50"] > 0
        assert len(small.cache) <= 2


def test_one_square_caches_one_tile_per_return_period(depth_set):
    assert depth_set.cache.limit == raster.TILE_CACHE_TILES == 48
    depth_set.depths(100.875, 9.375)
    depth_set.depths(101.125, 9.125)   # same tiles
    assert len(depth_set.cache) == 3


def test_depth_set_reads_banjir_raster_dir_once(monkeypatch, folder):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(folder))
    raster.depth_set.cache_clear()
    loaded = raster.depth_set()
    assert loaded is raster.depth_set()
    assert (loaded.folder, [g.name for g in loaded.grids]) == (str(folder), [GRID])
    raster.depth_set.cache_clear()


def test_the_default_raster_folder_is_app_data_rasters(monkeypatch):
    monkeypatch.delenv("BANJIR_RASTER_DIR", raising=False)
    assert raster.raster_dir() == ROOT / "app" / "data" / "rasters"


def test_a_missing_folder_gives_an_empty_set(tmp_path):
    empty = raster.DepthSet.load(tmp_path / "none")
    assert (empty.grids, empty.depths(101.5, 3.0), empty.block(GRID, 0, 0)) == ((), None, None)
    assert empty.coverage()["grids"] == []


def test_a_grid_missing_a_return_period_is_refused(tmp_path):
    fx.write_depth_set(tmp_path, rps=(10, 20))
    with pytest.raises(raster.RasterError, match="N10_E100.*50"):
        raster.DepthSet.load(tmp_path)


def test_the_return_period_files_must_share_one_grid(tmp_path):
    fx.write_depth_set(tmp_path)
    fx.write_depth_tiff(tmp_path / f"ID211_{GRID}_RP50_depth.tif", fx.depth_values(50), origin=(100.25, 10.0))
    with pytest.raises(raster.RasterError, match="N10_E100"):
        raster.DepthSet.load(tmp_path)


def test_two_files_for_one_grid_and_return_period_are_refused(tmp_path):
    fx.write_depth_set(tmp_path)
    fx.write_depth_tiff(tmp_path / f"ID999_{GRID}_RP10_depth.tif", fx.depth_values(10, shift=1.0))
    with pytest.raises(raster.RasterError, match=r"two files.*N10_E100.*10"):
        raster.DepthSet.load(tmp_path)


def test_a_relative_folder_is_kept_absolute(monkeypatch, folder):
    monkeypatch.chdir(folder.parent)
    loaded = raster.DepthSet.load(folder.name)
    monkeypatch.chdir(folder.parent.parent)
    assert (loaded.folder, loaded.depths(100.875, 9.375)["10"]) == (str(folder), 2.13)


def test_other_files_in_the_folder_are_ignored(tmp_path):
    fx.write_depth_set(tmp_path)
    (tmp_path / "SOURCES.txt").write_text("names, bytes, SHA-256")
    (tmp_path / "notes.tif").write_bytes(b"not a depth file")
    assert [g.name for g in raster.DepthSet.load(tmp_path).grids] == [GRID]


def test_coverage_describes_each_grid(depth_set):
    cover = depth_set.coverage()
    assert (cover["return_periods"], cover["block_cells"]) == ([10, 20, 50], 24)
    assert cover["grids"] == [{"name": GRID, "x0": 100.0, "y0": 10.0, "px": 0.25, "py": 0.25, "rows": 30, "cols": 40,
                               "bounds": [100.0, 2.5, 110.0, 10.0]}]
    assert cover["data_version"] == depth_set.data_version and json.loads(json.dumps(cover)) == cover


def test_the_data_version_follows_the_file_bytes(folder):
    first = raster.DepthSet.load(folder).data_version
    assert re.fullmatch(r"[0-9a-f]{12}", first) and raster.DepthSet.load(folder).data_version == first
    fx.write_depth_tiff(folder / f"ID211_{GRID}_RP50_depth.tif", fx.depth_values(50, shift=0.01))
    assert raster.DepthSet.load(folder).data_version != first


def test_the_data_version_follows_the_file_names_too(folder):
    first = raster.DepthSet.load(folder).data_version
    (folder / f"ID211_{GRID}_RP50_depth.tif").rename(folder / f"ID212_{GRID}_RP50_depth.tif")   # same bytes and order
    assert raster.DepthSet.load(folder).data_version != first


def test_the_data_version_is_worked_out_when_the_set_loads_not_on_first_use(folder):
    expected = raster.DepthSet.load(folder).data_version
    loaded = raster.DepthSet.load(folder)
    for path in folder.glob("*.tif"):
        path.unlink()                                     # gone before anyone asked for the version
    assert (loaded.data_version, loaded.coverage()["data_version"]) == (expected, expected)


def test_raster_uses_the_standard_library_only():
    tree = ast.parse(Path(raster.__file__).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert {name.split(".")[0] for name in names} <= sys.stdlib_module_names


# --- the real JRC files: parity with the built JSON, and speed ---

def real_raster_dir() -> Path | None:
    """BANJIR_RASTER_DIR, else app/data/rasters, else the raw JRC folder beside the repo: the first holding files."""
    candidates = (os.environ.get("BANJIR_RASTER_DIR"), ROOT / "app" / "data" / "rasters",
                  ROOT.parent / "05_Raw_Data_Sources" / "jrc_glofas_v2_1")
    return next((Path(c) for c in candidates if c and any(Path(c).glob("*_RP*_depth.tif"))), None)


REAL_DIR = real_raster_dir()
needs_real = pytest.mark.skipif(REAL_DIR is None, reason="no JRC depth files on this machine")


@pytest.fixture(scope="module")
def real():
    return raster.DepthSet.load(REAL_DIR)


def built(name: str) -> list[Path]:
    """Every built copy of a data file: app/data/{name}, or app/data/areas/*/{name} once the areas are split."""
    data = ROOT / "app" / "data"
    paths = sorted({*data.glob(name), *data.glob(f"areas/*/{name}")})
    assert paths, f"no built {name} under app/data"
    return paths


def square(grid: raster.Grid, cell: list) -> tuple:
    """(row, col, d10, d20, d50) of a town.json cell, the row and column taken from its south-west corner."""
    south, west, *depths = cell
    return (round((grid.y0 - south) / grid.py) - 1, round((west - grid.x0) / grid.px), *depths)


@needs_real
def test_parity_every_built_premise_depth(real):
    checked = []
    for path in built("premises.json"):
        premises = json.loads(path.read_text(encoding="utf-8"))
        found = [(p["id"], p["depth_m"], real.depths(p["lon"], p["lat"])) for p in premises]
        wrong = [row for row in found if row[1] != row[2]]
        assert not wrong, f"{path}: {len(wrong)} differ, first {wrong[:3]}"
        checked.append(f"{len(premises)} in {path.relative_to(ROOT)}")
    print(f"\nparity, premises equal: {', '.join(checked)}")


def assert_same_town(real, town: dict) -> None:
    grid = real.locate(*town["view"][:2])[0]
    rebuilt = real.view_cells(town["view"])
    assert [square(grid, c) for c in rebuilt] == [square(grid, c) for c in town["cells"]]
    assert [cell[:2] for cell in rebuilt] == [cell[:2] for cell in town["cells"]]   # south and west, exactly
    for cell in town["cells"]:
        row, col, *depths = square(grid, cell)
        lon, lat = grid.centre(row, col)
        assert real.locate(lon, lat) == (grid, row, col)
        assert real.depths(lon, lat) == dict(zip(("10", "20", "50"), depths))
    assert (town["cell_deg"], town["return_periods"]) == (grid.px, [10, 20, 50])


@needs_real
def test_parity_every_built_town_square(real):
    checked = []
    for path in built("town.json"):
        town = json.loads(path.read_text(encoding="utf-8"))
        assert_same_town(real, town)
        checked.append(f"{len(town['cells'])} in {path.relative_to(ROOT)}")
    print(f"\nparity, squares equal: {', '.join(checked)}")


def built_depths() -> list:
    """Every depth in the built data: each premise's and its road's, and each town square's."""
    premises = [p for path in built("premises.json") for p in json.loads(path.read_text(encoding="utf-8"))]
    squares = [c for path in built("town.json") for c in json.loads(path.read_text(encoding="utf-8"))["cells"]]
    return [v for p in premises for d in (p["depth_m"], (p["road"] or {}).get("depth_m", {})) for v in d.values()
            ] + [v for cell in squares for v in cell[2:]]


@needs_real
def test_no_built_depth_is_exactly_zero():
    values = built_depths()
    assert len(values) > 2000 and 0.0 not in values   # so a depth that rounds to 0.00 is no built value to keep


@needs_real
def test_real_files_have_the_checked_layout(real):
    grid = next(g for g in real.grids if g.name == GRID)
    assert (grid.rows, grid.cols) == (11999, 11999)
    assert (grid.x0, grid.y0) == (99.97625154437965, 10.00706666666666)
    assert (grid.px, grid.py) == (0.0008333333356347339, 0.0008333333333325754)


@needs_real
def test_a_view_of_the_whole_real_grid_is_refused_at_once(real):
    start = time.perf_counter()
    with pytest.raises(ValueError, match=r"squares.*at most"):
        real.view_cells((100.0, 0.5, 109.9, 10.0))
    assert time.perf_counter() - start < 0.1   # counted from the corners, not by visiting 100 million squares


@needs_real
def test_the_plan_example_point_snaps_to_its_square(real):
    grid, row, col = real.locate(101.5364982, 3.0297599)
    lon, lat = grid.centre(row, col)
    assert f"pt:{lat:.5f},{lon:.5f}" == "pt:3.02998,101.53667"
    assert real.depths(lon, lat) == {"10": 1.35, "20": 1.54, "50": 1.76}


def test_ten_thousand_warm_reads_take_under_a_second(request, folder):
    if REAL_DIR is None:
        depths, (west, south, east, north), source = raster.DepthSet.load(folder), (100.0, 2.5, 110.0, 10.0), "fixture"
    else:
        depths, (west, south, east, north), source = request.getfixturevalue("real"), SRI_MUDA_VIEW, "JRC files"
    steps = [n / 100 for n in range(100)]
    points = [(west + (east - west) * i, south + (north - south) * j) for i in steps for j in steps]
    for point in points:
        depths.depths(*point)   # warm the tile cache
    start = time.perf_counter()
    for point in points:
        depths.depths(*point)
    elapsed = time.perf_counter() - start
    print(f"\n10,000 warm reads ({source}, 3 return periods each): {elapsed:.3f} s")
    assert elapsed < 1.0
