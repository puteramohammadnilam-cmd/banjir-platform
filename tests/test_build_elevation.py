"""tools/build_elevation.py on small made-up inputs, no network: the percentile, the disc, the nearest river search
(against a search of every river square), the drawing of rivers, the floating point predictor, two COG tiles joined at
their seam, and a whole build read back by app/elevation.py."""
import json
import math
import struct
import sys
import zlib
from pathlib import Path

import pytest

from app import elevation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_elevation as be  # noqa: E402
import geotiff_write as gw  # noqa: E402

PX = 1 / 16                # a made-up GLO-30: 16 squares to the degree, 8 px tiles, centres on whole squares
SIZE, TILE = 16, 8


def test_percentile_interpolates_between_ranks_like_numpy():
    assert be.percentile(range(1, 11), 10) == pytest.approx(1.9)
    assert be.percentile([5.0], 10) == 5.0
    assert be.percentile([4, 1, 3, 2], 0) == 1 and be.percentile([4, 1, 3, 2], 100) == 4
    assert be.percentile([2.0, 2.0, 30.0], 10) == 2.0   # one bridge does not lift the river


def test_the_disc_holds_the_squares_within_the_radius():
    found = set(be.disc(150, 30, 30))
    assert (0, 0) in found and (0, 5) in found and (3, 4) in found and (5, 0) in found
    assert (4, 4) not in found and (0, 6) not in found
    assert len(found) == len(set(be.disc(150, 30, 30))) == 81


def brute_nearest(sources, rows, cols, dx, dy, cap):
    best = []
    for i in range(rows * cols):
        r, c = divmod(i, cols)
        dist, src = min((math.hypot((r - s // cols) * dy, (c - s % cols) * dx), s) for s in sources)
        best.append(dist if dist <= cap else None)
    return best


def test_the_nearest_river_search_finds_the_nearest_square_within_the_cap():
    rows = cols = 10
    sources = [0 * cols + 9, 4 * cols + 2, 9 * cols + 0, 7 * cols + 7]
    dx, dy, cap = 30.0, 31.0, 125.0
    found = be.nearest_river(sources, rows, cols, dx, dy, cap)
    for i, want in enumerate(brute_nearest(sources, rows, cols, dx, dy, cap)):
        if want is None:
            assert found[i] == -1, i
        else:
            r, c = divmod(i, cols)
            got = math.hypot((r - found[i] // cols) * dy, (c - found[i] % cols) * dx)
            assert found[i] in sources and got == pytest.approx(want), i
    assert found[4 * cols + 2] == 4 * cols + 2 and found[0 * cols + 0] == -1   # a river square is its own; far ones none


def test_a_plain_breadth_first_search_would_pick_the_diagonal():
    rows, cols = 3, 4
    found = be.nearest_river([1, 2], rows, cols, 30.0, 30.0, 1000.0)   # river squares (0, 1) and (0, 2)
    assert found[1 * cols + 2] == 2   # straight below (0, 2), not the diagonal (0, 1) that is searched first


def test_heights_above_the_river_keep_negatives_and_leave_gaps_as_no_data():
    surface = [5.0, 1.0, -9999.0, 8.0]
    out = be.above_river(surface, {0: 2.0}, [0, 0, 0, -1])
    assert list(out) == [3.0, -1.0, be.NODATA, be.NODATA]


def test_river_levels_take_the_low_values_near_each_river_square():
    rows, cols = 1, 6
    surface = [3.0, 2.0, 2.5, 12.0, 2.2, 40.0]
    mask = bytearray([1, 1, 1, 1, 1, 0])
    levels = be.river_levels(surface, mask, rows, cols, [(0, -1), (0, 0), (0, 1)], 10)
    assert set(levels) == {0, 1, 2, 3, 4}             # not the square off the river
    assert levels[3] == pytest.approx(be.percentile([2.5, 12.0, 2.2], 10))
    assert levels[4] == pytest.approx(be.percentile([12.0, 2.2], 10))   # 40 m is not river


def window(rows=12, cols=12) -> be.Window:
    return be.Window(gx0=1600, gy0=60, rows=rows, cols=cols, px=PX, py=PX)   # 100 E, 3.75 N


def test_a_line_marks_each_square_it_crosses_and_an_area_fills_round_its_hole():
    w = window()
    lon = lambda col: (w.gx0 + col) * PX
    lat = lambda row: (w.gy0 - row) * PX
    line = [(lon(0), lat(1)), (lon(11), lat(1))]
    outer = [(lon(2), lat(4)), (lon(9), lat(4)), (lon(9), lat(10)), (lon(2), lat(10)), (lon(2), lat(4))]
    hole = [(lon(5), lat(6)), (lon(7), lat(6)), (lon(7), lat(8)), (lon(5), lat(8)), (lon(5), lat(6))]
    mask = be.draw_rivers(w, [line], [[outer, hole]])
    marked = {divmod(i, w.cols) for i, v in enumerate(mask) if v}
    assert {(1, c) for c in range(12)} <= marked
    assert (5, 3) in marked and (9, 8) in marked and (6, 6) not in marked and (7, 6) not in marked
    assert (3, 3) not in marked and (11, 3) not in marked


def test_rivers_and_water_areas_are_told_apart_from_other_answers():
    answer = {"elements": [
        {"type": "way", "tags": {"waterway": "river"}, "geometry": [{"lat": 3, "lon": 101}, {"lat": 3.1, "lon": 101}]},
        {"type": "way", "tags": {"waterway": "drain"}, "geometry": [{"lat": 3, "lon": 101}, {"lat": 3.1, "lon": 101}]},
        {"type": "way", "tags": {"natural": "water", "water": "pond"}, "geometry": []},
        {"type": "way", "tags": {"waterway": "riverbank"},
         "geometry": [{"lat": 3, "lon": 101}, {"lat": 3, "lon": 102}, {"lat": 4, "lon": 101}]},
        {"type": "relation", "tags": {"natural": "water", "water": "river"},
         "members": [{"type": "way", "geometry": [{"lat": 3, "lon": 101}, {"lat": 3, "lon": 102}, {"lat": 4, "lon": 102}]}]},
        {"type": "node", "tags": {"natural": "peak"}, "lat": 3, "lon": 101},
    ]}
    lines, areas = be.river_shapes(answer)
    assert len(lines) == 1 and len(areas) == 2


# --- the GLO-30 COG layout ---

def predicted(raw: bytes, width: int) -> bytes:
    """TIFF's floating point predictor applied: what a COG stores before deflate."""
    out = bytearray()
    for start in range(0, len(raw), width * 4):
        values = struct.unpack(f"<{width}f", raw[start:start + width * 4])
        big = struct.pack(f">{width}f", *values)
        planes = bytes(big[k::4][i] for k in range(4) for i in range(width))
        out += bytes((planes[i] - (planes[i - 1] if i else 0)) & 0xFF for i in range(len(planes)))
    return bytes(out)


def height(gy: int, gx: int) -> float:
    return (gy - 32) + (gx - 1616) / 100


def write_cog(folder: Path, lat_floor: int, lon_floor: int) -> Path:
    """A made-up GLO-30 tile: pixel is point at whole squares, predictor 3, no GDAL_NODATA."""
    north, west = (lat_floor + 1) * SIZE, lon_floor * SIZE
    rows = [[height(north - r, west + c) for c in range(SIZE)] for r in range(SIZE)]
    count = (SIZE // TILE) ** 2
    chunks = {i: zlib.compress(predicted(gw.tile_bytes(rows, i, TILE, 0.0), TILE)) for i in range(count)}
    path = folder / f"{be.tile_name(lat_floor, lon_floor)}.tif"
    gw.write_tiff(path, rows, tile=TILE, origin=(lon_floor, lat_floor + 1), pixel=(PX, PX), padding=0.0,
                  chunks=chunks, tags={317: (gw.SHORT, (3,)), 42113: None,
                                       34735: (gw.SHORT, gw.geo_keys({1024: 2, 1025: 2, 2048: 4326}))})
    return path


def test_the_float_predictor_is_undone_byte_for_byte():
    raw = struct.pack("<8f", 1.5, -2.25, 1e-3, 300.0, 0.0, -0.0, 12.345, 7.0) * 2
    assert be.undo_float_predictor(predicted(raw, 8), 8) == raw


def test_two_tiles_join_at_their_seam(tmp_path):
    cogs = [be.Cog.open(write_cog(tmp_path, lat, 101)) for lat in (3, 2)]
    assert (cogs[0].gy0, cogs[1].gy0, cogs[0].gx0, cogs[0].predictor) == (64, 48, 1616, 3)
    w = be.Window.around((101.1, 2.6, 101.6, 3.4), PX, PX)    # 3.0 N is the seam
    joined = be.mosaic(cogs, w)
    for r in range(w.rows):
        for c in range(w.cols):
            assert joined[r * w.cols + c] == pytest.approx(height(w.gy0 - r, w.gx0 + c), abs=1e-4), (r, c)


def test_a_cog_in_another_layout_is_refused(tmp_path):
    rows = [[1.0] * SIZE for _ in range(SIZE)]
    path = gw.write_tiff(tmp_path / "x.tif", rows, tile=TILE, origin=(101, 3), pixel=(PX, PX), padding=0.0,
                         tags={317: (gw.SHORT, (2,))})
    with pytest.raises(be.BuildError, match="Predictor"):
        be.Cog.open(path)


def test_tiles_are_named_like_glo30():
    assert be.tiles_for((101.4, 2.9, 101.6, 3.3)) == ["Copernicus_DSM_COG_10_N03_00_E101_00_DEM",
                                                      "Copernicus_DSM_COG_10_N02_00_E101_00_DEM"]


# --- a whole build ---

def test_a_build_writes_two_crops_that_the_app_reads(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "dem"
    raw.mkdir()
    for lat in (3, 2):
        write_cog(raw, lat, 101)
    river = [{"lat": 3.0, "lon": 101.0}, {"lat": 3.0, "lon": 101.99}]   # along the seam
    (raw / "rivers_test.json").write_text(json.dumps({"elements": [
        {"type": "way", "tags": {"waterway": "river"}, "geometry": river}]}))
    monkeypatch.setattr(be, "CAP_M", 15_000.0)            # squares here are about 7 km
    monkeypatch.setattr(be, "LEVEL_RADIUS_M", 8_000.0)
    found = be.build(be.parse_args(["build", "--name", "test", "--bbox", "101.3", "2.8", "101.6", "3.2",
                                    "--raw", str(raw), "--out", str(out), "--margin-km", "0"]))
    assert sorted(found["files"]) == ["test_above_river.tif", "test_surface.tif"]
    monkeypatch.setenv("BANJIR_DEM_DIR", str(out))
    on_river = elevation.at(3.0, 101.5)                    # square gx 1624: its neighbours on the river are 0.01 apart
    assert on_river == {"ground_m": round(height(48, 1624), 1), "above_river_m": 0.0}
    one_up = elevation.at(3.0 + PX, 101.5)
    assert one_up == {"ground_m": round(height(49, 1624), 1), "above_river_m": 1.0}
    assert elevation.at(3.0 + 3 * PX, 101.5)["above_river_m"] is None   # about 21 km away: past the cap
