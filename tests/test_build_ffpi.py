"""tools/build_ffpi.py, tools/grid_ops.py and tools/png_write.py on hand cases and small made-up grids, no network:
the slope steps (with 27-30 % rated 10), every WorldCover class rated, the built-up share split, the USDA texture
triangle, vegetation cover steps, the Scenario 2 formula, class edges, water as no data and the PNG's indices."""
import json
import math
import struct
import sys
import zlib
from array import array
from pathlib import Path

import pytest

from app import geo, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_ffpi as bf  # noqa: E402
import grid_ops as go  # noqa: E402
import png_write  # noqa: E402

CONTRACT = json.loads((ROOT / "tests" / "fixtures" / "index_contract.json").read_text(encoding="utf-8"))


# --- ratings ---

@pytest.mark.parametrize("slope, rating", [(0, 1), (2.99, 1), (3, 1), (3.01, 2), (6, 2), (15, 5), (24.5, 9), (27, 9),
                                           (27.01, 10), (29.9, 10), (30, 10), (45, 10), (400, 10)])
def test_slope_ratings_step_every_3_percent_and_27_to_30_counts_as_10(slope, rating):
    assert bf.slope_rating(slope) == rating


def cover(**shares) -> dict[int, int]:
    """WorldCover pixel counts out of 100, from class=count keywords such as c50=40."""
    return {int(k[1:]): v for k, v in shares.items()}


def test_every_worldcover_class_has_a_land_rating():
    assert set(bf.LAND_RATINGS) == {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
    for k, rating in bf.LAND_RATINGS.items():
        assert rating is None if k == bf.BUILT else 1 <= rating <= 10
    for k in bf.LAND_RATINGS:
        if k not in (bf.WATER, bf.BUILT):
            assert bf.land_rating(cover(**{f"c{k}": 9})) == bf.LAND_RATINGS[k]


@pytest.mark.parametrize("counts, rating", [
    (cover(c50=100), 10), (cover(c50=80, c10=20), 10), (cover(c50=79, c10=21), 9), (cover(c50=50, c30=50), 9),
    (cover(c50=49, c10=51), 8), (cover(c50=20, c10=80), 8),
    (cover(c50=19, c10=81), (19 * 7 + 81 * 3) / 100),        # under a fifth built: open space, mixed with the rest
    (cover(c10=50, c30=50), (3 + 6) / 2), (cover(c80=50, c10=50), 2.0)])
def test_built_up_share_picks_the_developed_intensity_like_nlcd(counts, rating):
    assert bf.land_rating(counts) == pytest.approx(rating)


def test_a_square_mostly_water_or_without_cover_has_no_land_rating():
    assert bf.land_rating(cover(c80=51, c50=49)) is None
    assert bf.land_rating(cover()) is None


@pytest.mark.parametrize("sand, silt, clay, texture", [
    (92, 5, 3, "sand"), (82, 12, 6, "loamy sand"), (65, 25, 10, "sandy loam"), (40, 40, 20, "loam"),
    (20, 65, 15, "silt loam"), (5, 88, 7, "silt"), (60, 12, 28, "sandy clay loam"), (32, 34, 34, "clay loam"),
    (10, 55, 35, "silty clay loam"), (50, 5, 45, "sandy clay"), (5, 47, 48, "silty clay"), (20, 20, 60, "clay"),
    (45, 28, 27, "clay loam"), (52, 28, 20, "loam"), (53, 27, 20, "sandy clay loam")])
def test_the_usda_texture_triangle(sand, silt, clay, texture):
    assert bf.texture_class(sand, silt, clay) == texture


def test_every_texture_has_a_soil_rating_from_the_table():
    ratings = {t: bf.SOIL_RATINGS[t] for t in bf.TEXTURES}
    assert ratings["sand"] == 2 and ratings["sandy loam"] == 3 and ratings["loam"] == 6 and ratings["clay"] == 9
    assert ratings["silt loam"] == ratings["loamy sand"] == 4 and ratings["silt"] == 5
    assert ratings["sandy clay loam"] == ratings["silty clay loam"] == 7
    assert ratings["clay loam"] == ratings["sandy clay"] == 8 and ratings["silty clay"] == 9
    assert bf.IMPERVIOUS == 10


@pytest.mark.parametrize("fvc, rating", [(1.0, 1), (0.9, 1), (0.8999, 2), (0.8, 2), (0.45, 6), (0.1, 9), (0.0999, 10),
                                         (0.0, 10)])
def test_vegetation_cover_steps_every_10_percent(fvc, rating):
    assert bf.vegetation_rating(fvc) == rating


def test_scenario_2_weights_slope_by_1_5_and_vegetation_by_half():
    assert bf.ffpi(10, 5, 4, 2) == 6.25
    assert bf.round_score(6.25) == 6.3 and bf.round_score(6.35) == 6.4 and bf.round_score(6.249) == 6.2
    assert bf.ffpi(1, 1, 1, 1) == 1 and bf.ffpi(10, 10, 10, 10) == 10


@pytest.mark.parametrize("score, name", [(1.0, "low"), (4.4, "low"), (4.5, "medium"), (5.0, "medium"), (6.0, "medium"),
                                         (6.4, "medium"), (6.5, "high"), (8.4, "high"), (8.5, "extreme"),
                                         (10.0, "extreme")])
def test_class_edges_belong_to_the_class_above(score, name):
    stored = struct.unpack("<f", struct.pack("<f", score))[0]   # as read back from the float32 file
    assert bf.class_of(stored) == name


def test_the_classes_breaks_and_colours_are_the_contract_s():
    example = CONTRACT["ffpi_json"]["example"]
    assert list(bf.CLASSES) == example["classes"] and list(bf.BREAKS) == example["breaks"]
    colours = bf.legend()
    assert [c["class"] for c in colours] == example["classes"]
    assert [c["colour"] for c in colours] == [c["colour"] for c in example["legend"]]
    lightness = [c["oklch"][0] for c in colours]
    assert lightness == sorted(lightness, reverse=True) and all(c["oklch"][2] == 50 for c in colours)


def test_the_breaks_follow_the_paper_s_reading_of_5_to_6_as_medium():
    assert bf.BREAKS == (4.5, 6.5, 8.5)
    method = bf.ffpi_text.method()
    for text in (method["classes"], method["summary"]):
        assert "5 to 6" in text and "medium" in text, text
    assert "4.5" in method["classes"] and "6.5" in method["classes"] and "8.5" in method["classes"]
    assert "equal" not in method["classes"] and not any("equal steps" in d for d in method["deviations"])


NDVI_WORDS = ("ESA WorldCover Sentinel-1 and Sentinel-2 10m Annual Composites accessed on 4 October 2026 from "
              "https://registry.opendata.aws/esa-worldcover-vito-composites")


def test_the_credit_gives_the_ndvi_composite_s_access_date_in_its_own_words():
    log = [{"file": "worldcover/a/pieces.json", "date": "2026-10-09"},
           {"file": "vegetation/ESA_WorldCover_10m_2021_v200_N03E101_NDVI/pieces.json", "date": "2026-10-03"},
           {"file": "vegetation/ESA_WorldCover_10m_2021_v200_N02E101_NDVI/pieces.json", "date": "2026-10-04"}]
    assert bf.ndvi_accessed(log) == "2026-10-04"            # the later of the composite's pieces
    credit = bf.ffpi_text.credit("2026-10-04")
    assert NDVI_WORDS in credit and "CC BY 4.0" in credit and "Copernicus DEM GLO-30" in credit
    with pytest.raises(ValueError):
        bf.ndvi_accessed([{"file": "worldcover/a/pieces.json", "date": "2026-10-04"}])


def test_oklch_out_of_the_srgb_gamut_is_refused():
    assert bf.oklch_hex(1.0, 0.0, 0) == "#ffffff" and bf.oklch_hex(0.0, 0.0, 0) == "#000000"
    with pytest.raises(ValueError, match="gamut"):
        bf.oklch_hex(0.5, 0.3, 50)


# --- grids ---

def small_grid(rows=4, cols=4) -> go.Grid:
    return go.Grid(101.0, 3.0, 0.25, 0.25, rows, cols)


def test_slope_percent_follows_horn_on_a_plane_and_leaves_no_data_alone():
    grid = small_grid(5, 5)
    plane = array("d", (2.0 * c for r in range(5) for c in range(5)))          # 2 m up per 10 m east
    slope = go.slope_percent(plane, 5, 5, 10.0, 10.0)
    assert slope[12] == pytest.approx(20.0) and slope[0] == pytest.approx(10.0)   # past the edge: the edge row
    plane[12] = go.NODATA
    assert go.slope_percent(plane, 5, 5, 10.0, 10.0)[12] == go.NODATA
    assert grid.size == 25


@pytest.mark.parametrize("east, north, expected", [(2.0, 0.0, 20.0), (0.0, 3.0, 15.0),
                                                    (2.0, 3.0, 100 * math.hypot(2 / 10, 3 / 20))])
def test_horn_slope_takes_each_axis_with_its_own_spacing(east, north, expected):
    """Planes rising east (per 10 m) and north (per 20 m): rows run north to south, so a swapped or flipped axis, or
    spacings taken the wrong way round, give another slope."""
    rows, cols, dx, dy = 5, 6, 10.0, 20.0
    plane = array("d", (east * c + north * (rows - 1 - r) for r in range(rows) for c in range(cols)))
    slope = go.slope_percent(plane, rows, cols, dx, dy)
    assert slope[2 * cols + 3] == pytest.approx(expected)
    tilted = array("d", (east * (rows - 1 - r) + north * c for r in range(rows) for c in range(cols)))
    if east != north:                                   # the same rises on the other axes: another answer
        assert go.slope_percent(tilted, rows, cols, dx, dy)[2 * cols + 3] != pytest.approx(expected)


def test_the_scores_are_no_data_outside_the_city_outline():
    values = array("d", [5.0, 6.0, go.NODATA, 7.0])
    assert list(bf.inside(values, bytearray([1, 0, 1, 1]))) == [5.0, go.NODATA, go.NODATA, 7.0]


def test_three_by_three_lowest_and_mean_leave_out_no_data():
    values = array("d", [5, 1, 7, go.NODATA, 4, 2, 9, 8, 3])
    assert list(go.min_filter3(values, 3, 3)) == [1, 1, 1, 1, 1, 1, 4, 2, 2]
    assert go.mean_filter3(values, 3, 3)[0] == pytest.approx((5 + 1 + 4) / 3)


def test_polygon_masks_match_app_geo_and_keep_holes_out():
    grid = go.Grid(101.0, 3.1, 0.01, 0.01, 10, 10)
    outer = [[101.012, 3.002], [101.088, 3.002], [101.088, 3.088], [101.012, 3.088], [101.012, 3.002]]
    hole = [[101.032, 3.032], [101.068, 3.032], [101.068, 3.068], [101.032, 3.068], [101.032, 3.032]]
    shape = {"type": "Polygon", "coordinates": [outer, hole]}
    mask = go.polygon_mask(grid, shape)
    for i in range(grid.size):
        assert mask[i] == geo.point_in_geometry(*grid.centre(*divmod(i, grid.cols)), shape), i
    other = {"type": "MultiPolygon", "coordinates": [[outer]]}
    holder = go.first_holder(grid, [shape, other])
    assert holder[5 * 10 + 5] == 1 and holder[2 * 10 + 2] == 0 and holder[0] == -1


def test_line_metres_add_up_to_the_line_and_distances_reach_the_cap():
    grid = go.Grid(101.0, 3.0, 0.001, 0.001, 20, 20)
    dx, dy = grid.metres()
    line = [grid.centre(10, 0), grid.centre(10, 19)]
    metres = go.line_metres(grid, [line])
    assert sum(metres) == pytest.approx(19 * dx) and sum(1 for m in metres if m) == 20
    far = go.distance_to(go.draw_lines(grid, [line]), grid, 5.5 * dy)
    assert far[10 * 20 + 3] == 0 and far[5 * 20 + 3] == pytest.approx(5 * dy) and math.isinf(far[0])


def test_a_disc_sum_counts_the_squares_within_the_radius():
    grid = go.Grid(101.0, 3.0, 0.001, 0.001, 9, 9)
    ones = array("d", [1.0]) * grid.size
    spec = go.disc_rows(2.0, 1.0, 1.0)
    assert spec == [(-2, 0), (-1, 1), (0, 2), (1, 1), (2, 0)]
    found = go.disc_sum(ones, grid, spec)
    assert found[4 * 9 + 4] == 13 and found[0] == 6


def test_finer_classes_are_counted_into_their_square_by_pixel_centre():
    grid = go.Grid(101.0, 3.0, 0.3, 0.3, 1, 2)
    pixels = [50, 50, 10, 80, 10, 50, 50, 10, 80, 0, 50, 50]          # 2 rows of 6 pixels of 0.1 degree
    found = go.fractions_from(grid, pixels, (101.0, 3.0, 0.1, 0.1, 6), (10, 50, 80))
    assert (found[50][0], found[10][0], found[80][0]) == (3, 2, 1)
    assert (found[50][1], found[10][1], found[80][1]) == (3, 1, 1)   # 0 is not counted


# --- the score grid and the PNG ---

def test_water_and_missing_inputs_give_no_data_and_the_rest_a_rounded_score():
    factors = bf.Factors(m=array("d", [10, 1, 1, 3]), l=array("d", [5, go.NODATA, 10, 7.4]),
                         s=array("d", [4, 9, go.NODATA, 8]), v=array("d", [2, 10, 10, 6]))
    scores = bf.scores(factors)
    assert list(scores) == [6.3, go.NODATA, go.NODATA, round(bf.round_score((4.5 + 7.4 + 8 + 3) / 4), 1)]


def read_png(path: Path) -> tuple[dict, list[list[int]]]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, at = {}, 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        chunks.setdefault(kind.decode(), b"")
        chunks[kind.decode()] += data[at + 8:at + 8 + length]
        at += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks["IHDR"][:10])
    raw, row_bytes, rows = zlib.decompress(chunks["IDAT"]), -(-width * depth // 8), []
    for r in range(height):
        line = raw[r * (row_bytes + 1):(r + 1) * (row_bytes + 1)]
        assert line[0] == 0                                     # no filter
        bits = "".join(format(b, "08b") for b in line[1:])
        rows.append([int(bits[i * depth:(i + 1) * depth], 2) for i in range(width)])
    return {"width": width, "height": height, "depth": depth, "colour": colour, **chunks}, rows


def test_the_png_holds_class_indices_with_index_0_transparent(tmp_path):
    grid = small_grid(2, 3)
    scores = array("d", [1.0, 5.0, 7.0, 9.0, go.NODATA, 6.0])
    shown = bytearray([1, 1, 1, 1, 1, 0])
    path = bf.write_png(tmp_path / "x.png", grid, scores, shown)
    info, rows = read_png(path)
    assert (info["width"], info["height"], info["depth"], info["colour"]) == (3, 2, 4, 3)
    assert rows == [[1, 2, 3], [4, 0, 0]]
    palette = [info["PLTE"][i:i + 3].hex() for i in range(0, len(info["PLTE"]), 3)]
    assert palette[1:] == [c["colour"][1:] for c in bf.legend()]
    assert info["tRNS"] == bytes([0, 255, 255, 255, 255])


def test_png_rows_pack_two_indices_a_byte_and_pad_the_last(tmp_path):
    path = png_write.write_indexed(tmp_path / "p.png", [[1, 2, 3], [0, 4, 5]], [(0, 0, 0)] * 6, {0: 0}, depth=4)
    info, rows = read_png(path)
    assert rows == [[1, 2, 3], [0, 4, 5]] and info["tRNS"] == b"\x00"


def test_the_written_tif_reads_back_through_app_raster(tmp_path):
    grid = small_grid(3, 4)
    scores = array("d", [1.0, 2.5, go.NODATA, 10.0, 6.3, 6.2, 5.5, 3.3, 7.8, 7.7, 4.4, 9.9])
    path, digest = bf.write_tif(tmp_path / "x_ffpi.tif", grid, scores)
    crop = raster.DepthFile.open(path, "x")
    assert crop.grid.x0 == grid.west and crop.grid.y0 == grid.north
    assert crop.value_at(0, 2, lambda v: v) == go.NODATA
    assert round(crop.value_at(1, 0, lambda v: v), 4) == 6.3 and len(digest) == 64
