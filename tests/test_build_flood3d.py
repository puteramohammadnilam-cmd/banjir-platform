"""tools/build_flood3d.py on small made-up inputs, no network: heights from OSM tags, Google's raster or a guess, each
with its source code; outlines kept by where their middle lies; corners as whole millionths of a degree from the
box's corner, read back as the page reads them; the wet squares over the box; a saved Overpass answer reused; the
UTM sums; Google's median height over an outline at 0.5 m and 2 m squares; and the tile a building reads, where two
overlap, through a real two-image (overview) GeoTIFF."""
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_flood3d as bf  # noqa: E402
import geotiff_write as gw  # noqa: E402

METRES_PER_DEG = 111_320.0   # near enough over the few metres these outlines span
SQUARE = [(101.0, 3.0), (101.001, 3.0), (101.001, 3.001), (101.0, 3.001), (101.0, 3.0)]
SECTION = {"id": "seksyen-x", "bbox": [101.0, 3.0, 101.01, 3.01]}
TOWN = {"cell_deg": 0.001, "return_periods": [10, 20, 50],
        "cells": [[3.0, 101.0, 0.4, None, 1.2], [3.0, 101.001, None, None, None], [3.5, 101.0, 2.0, 2.0, 2.0],
                  [2.9995, 100.997, None, None, 0.3]]}


def way(way_id, ring, **tags):
    return {"type": "way", "id": way_id, "tags": {"building": "yes", **tags},
            "geometry": [{"lon": lon, "lat": lat} for lon, lat in ring]}


def shifted(ring, dlon=0.0, dlat=0.0):
    return [(lon + dlon, lat + dlat) for lon, lat in ring]


def decode(row, origin):
    """A bundle building's corners back to lon1, lat1, lon2, lat2, ..., as the page reads them: origin plus
    millionths of a degree."""
    lon0, lat0 = origin
    return [value for x, y in zip(row[2::2], row[3::2]) for value in (lon0 + x / 1e6, lat0 + y / 1e6)]


def flat(ring):
    return [value for point in ring for value in point]


def test_height_comes_from_osm_then_google_then_a_guess_with_its_source_code():
    assert bf.height_of({"height": "12 m"}, google=30.0) == (12.0, 0)
    assert bf.height_of({"building:levels": "4"}) == (12.8, 0)
    assert bf.height_of({"building": "house"}, google=7.04) == (7.0, 1)
    assert bf.height_of({"building": "house"}) == (6.4, 2)
    assert bf.height_of({"building": "yes", "height": "tall"}) == (6.4, 2)   # unreadable height: guessed
    assert bf.height_of({"building:levels": "0"}) == (6.4, 2)


def test_corners_are_millionths_of_a_degree_from_the_origin_without_the_closing_corner():
    origin = (100.99, 2.995)
    row = bf.encode(SQUARE, origin)
    assert row == [10000, 5000, 11000, 5000, 11000, 6000, 10000, 6000]
    assert decode([0, 0, *row], origin) == pytest.approx(flat(SQUARE[:-1]), abs=1e-9)
    odd = [(101.12345678, 3.0000004), (101.1235, 3.0), (101.1235, 3.0001), (101.12345678, 3.0000004)]
    assert bf.encode(odd, (101.0, 3.0)) == [123457, 0, 123500, 0, 123500, 100]   # rounded to the nearest


def test_a_corner_rounding_onto_its_neighbour_is_dropped_and_under_three_corners_drops_the_building():
    near = [(101.0, 3.0), (101.0000001, 3.0), (101.001, 3.0), (101.001, 3.001), (101.0, 3.0)]
    assert bf.encode(near, (101.0, 3.0)) == [0, 0, 1000, 0, 1000, 1000]
    sliver = [(101.0, 3.0), (101.001, 3.0), (101.0000002, 3.0000001), (101.0, 3.0)]
    assert bf.encode(sliver, (101.0, 3.0)) is None


def test_outlines_keep_closed_ways_whose_middle_lies_in_the_box():
    box = (101.0, 3.0, 101.01, 3.01)
    straddling = shifted(SQUARE, dlon=-0.0004)                    # half out of the box, middle in it
    outside = shifted(SQUARE, dlon=-0.0006)                       # middle west of the box
    open_way = SQUARE[:-1] + [(101.0, 3.0002)]
    answer = {"elements": [way(1, SQUARE), way(2, straddling), way(3, outside), way(4, open_way),
                           {"type": "node", "id": 5}, {"type": "relation", "id": 6}]}
    assert [ring for _, ring in bf.outlines(answer, box)] == [SQUARE, straddling]


def test_water_rows_are_the_wet_squares_over_the_box_with_a_dry_size_as_0():
    rows = bf.water_rows(TOWN, (100.9975, 2.9995, 101.002, 3.002))
    assert rows == [[3.0, 101.0, 0.4, 0, 1.2], [2.9995, 100.997, 0, 0, 0.3]]   # the last overlaps the box's corner


def test_a_bundle_holds_the_box_its_corner_the_buildings_and_the_water():
    box = bf.section_box(SECTION["bbox"])
    dlat, dlon = 300 / 110_574, 300 / (111_320 * math.cos(math.radians(3.005)))   # 300 m, as fetch_area_osm.widen
    assert box == pytest.approx((101.0 - dlon, 3.0 - dlat, 101.01 + dlon, 3.01 + dlat), abs=1e-6)
    assert all(v == round(v, 6) for v in box)
    inside = shifted(SQUARE, 0.002, 0.002)
    sliver = [(101.003, 3.003), (101.004, 3.003), (101.0030001, 3.0030001), (101.003, 3.003)]
    answer = {"osm3s": {"timestamp_osm_base": "2026-10-01T08:00:00Z"},
              "elements": [way(1, inside, height="9"), way(2, shifted(inside, 0.002)), way(3, shifted(inside, 0.004),
                           building="house"), way(4, sliver), way(5, shifted(SQUARE, 0.2))]}
    asked = []

    def google(rings):
        asked.extend(rings)
        return [11.04, None]

    bundle = bf.bake("shah-alam", SECTION, TOWN, answer, google, credit="credit")
    assert asked == [shifted(inside, 0.002), shifted(inside, 0.004)]   # only those without an OSM height
    assert {k: bundle[k] for k in ("version", "area", "section", "credit", "fetched_on")} == \
        {"version": 1, "area": "shah-alam", "section": "seksyen-x", "credit": "credit", "fetched_on": "2026-10-01"}
    assert bundle["box"] == list(box) and bundle["origin"] == list(box[:2])
    assert [row[:2] for row in bundle["buildings"]] == [[9.0, 0], [11.0, 1], [6.4, 2]]   # the sliver dropped
    back = decode(bundle["buildings"][1], bundle["origin"])
    assert back == pytest.approx(flat(shifted(inside, 0.002)[:-1]), abs=6e-7)
    assert (bundle["cell_deg"], bundle["return_periods"]) == (0.001, [10, 20, 50])
    assert bundle["water"] == [[3.0, 101.0, 0.4, 0, 1.2], [2.9995, 100.997, 0, 0, 0.3]]
    json.dumps(bundle, allow_nan=False)


def test_a_saved_overpass_answer_is_reused_and_a_new_one_saved(tmp_path):
    box = (101.0, 3.0, 101.01, 3.01)
    saved = tmp_path / "seksyen-x.json"
    asked = []
    answer = bf.overpass_answer(saved, box, post=lambda query: asked.append(query) or {"elements": [way(1, SQUARE)]})
    assert asked == ["[out:json][timeout:300];way[building](3.000000,101.000000,3.010000,101.010000);out geom;"]
    assert json.loads(saved.read_text()) == answer
    assert bf.overpass_answer(saved, box, post=lambda query: pytest.fail("asked again")) == answer
    with pytest.raises(bf.OverpassTimeout):
        bf.overpass_answer(tmp_path / "busy.json", box, post=lambda query: {"remark": "runtime error: timed out"})
    assert not (tmp_path / "busy.json").exists()


def meridian_arc(lat: float) -> float:
    """Metres from the equator along a WGS 84 meridian (Helmert's series): a check apart from utm_north's sums."""
    e2 = bf.WGS84_F * (2 - bf.WGS84_F)
    phi = math.radians(lat)
    return bf.WGS84_A * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
                         - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
                         + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
                         - 35 * e2 ** 3 / 3072 * math.sin(6 * phi))


def test_utm_north_puts_the_central_meridian_at_500_km_and_follows_the_meridian_arc():
    assert bf.utm_north(0.0, 99.0, 47) == pytest.approx((500_000.0, 0.0), abs=1e-6)
    east, north = bf.utm_north(3.0, 99.0, 47)
    assert east == pytest.approx(500_000.0, abs=1e-6)
    assert north == pytest.approx(0.9996 * meridian_arc(3.0), abs=0.01)
    left, right = bf.utm_north(3.0, 98.5, 47), bf.utm_north(3.0, 99.5, 47)   # mirror images across the meridian
    assert 500_000 - left[0] == pytest.approx(right[0] - 500_000, abs=1e-6) and left[1] == pytest.approx(right[1])


def grid_around(lat, lon, height, presence=0.9, size=40, pixel=0.5):
    """A Heights window of size x size squares `pixel` metres wide centred on (lat, lon), each from height(row, col)."""
    x, y = bf.utm_north(lat, lon, 47)
    west, north = x - size * pixel / 2, y + size * pixel / 2
    return bf.Heights(47, west, north, pixel, size, [height(r, c) for r in range(size) for c in range(size)],
                      [presence] * size * size)


def outline(lat, lon, metres):
    """A (lon, lat) square about `metres` a side centred on the point."""
    d_lat, d_lon = metres / 2 / METRES_PER_DEG, metres / 2 / (METRES_PER_DEG * math.cos(math.radians(lat)))
    return [(lon - d_lon, lat - d_lat), (lon + d_lon, lat - d_lat), (lon + d_lon, lat + d_lat),
            (lon - d_lon, lat + d_lat), (lon - d_lon, lat - d_lat)]


def test_google_height_is_the_median_of_confident_squares_inside_the_outline():
    lat, lon = 3.067, 101.4897
    ring = outline(lat, lon, 4)
    inside = bf.squares_in(grid_around(lat, lon, lambda r, c: 0.0), ring)
    assert 56 <= len(inside) <= 72   # 4 m x 4 m: 8 x 8 squares, give or take an edge row
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0 if c % 2 else 12.0), ring) == 10.5
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0, presence=0.3), ring) is None   # not confident
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 1.5), ring) is None                 # under a storey
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0), outline(lat, lon, 1)) is None  # too little roof
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0), outline(lat, lon + 0.01, 4)) is None   # off grid
    assert bf.google_height(None, ring) is None


def test_the_least_roof_is_an_area_so_one_2_m_square_is_enough_and_one_half_metre_square_is_not():
    lat, lon = 3.067, 101.4897
    for pixel, want in ((2.0, 7.0), (0.5, None)):
        grid = grid_around(lat, lon, lambda r, c: 7.0, size=10, pixel=pixel)
        north_east = lat + pixel / 2 / METRES_PER_DEG, lon + pixel / 2 / (METRES_PER_DEG * math.cos(math.radians(lat)))
        ring = outline(*north_east, pixel * 0.8)              # round the centre of the square north-east of the middle
        assert len(bf.squares_in(grid, ring)) == 1
        assert bf.google_height(grid, ring) == want, pixel


def test_bands_are_found_by_their_gdal_description_and_layers_by_their_year():
    metadata = ('<GDALMetadata><Item name="DESCRIPTION" sample="0" role="description">building_fractional_count</Item>'
                '<Item name="DESCRIPTION" sample="1" role="description">building_height</Item></GDALMetadata>')
    assert bf.band_of(metadata, "building_height") == 1
    with pytest.raises(bf.tr.TiffError):
        bf.band_of(metadata, "building_presence")
    assert {bf.layer_year(url) for url in bf.HEIGHTS_TILES} == {"2023"} and bf.layer_year("local.tif") == ""


ONE_BAND = ('<GDALMetadata><Item name="DESCRIPTION" sample="0" role="description">building_height</Item>'
            '<Item name="DESCRIPTION" sample="0" role="description">building_presence</Item></GDALMetadata>\0')


def utm_tile(path, west, north, value, cells=64):
    """A GeoTIFF on UTM 47N of cells x cells 0.5 m squares all `value`, with an overview of 2 m squares all
    value + 100, its one sample standing for both building_height and building_presence."""
    tags = {34735: (gw.SHORT, gw.geo_keys({1024: 1, 1025: 1, 3072: 32647})), 42112: (gw.ASCII, ONE_BAND.encode())}
    first = gw.tiff_bytes([[value] * cells] * cells, tile=16, origin=(west, north), pixel=(0.5, 0.5), padding=-99.0,
                          tags=tags)
    small = [[value + 100] * (cells // 4)] * (cells // 4)
    path.write_bytes(gw.with_overview(first, small, tile=16, padding=-99.0))
    return str(path)


def test_a_building_reads_the_overview_of_the_tile_whose_centre_is_nearest(tmp_path):
    x0, y0 = bf.utm_north(3.067, 101.4897, 47)
    west, north = round(x0) - 16, round(y0) + 16        # tile a spans west to west + 32 m; tile b starts 20 m east
    a = bf.open_tile(utm_tile(tmp_path / "a.tif", west, north, 5.0), tmp_path, pixel_m=2.0)
    b = bf.open_tile(utm_tile(tmp_path / "b.tif", west + 20, north, 7.0), tmp_path, pixel_m=2.0)
    assert (a.image.px, a.image.width, a.bands) == (2.0, 16, (0, 0))
    assert bf.open_tile(str(tmp_path / "a.tif"), tmp_path, pixel_m=1.0).image.px == 0.5   # no 1 m overview: full grid

    def ring_at(east_m, side=6):
        lon, lat = metres_east(east_m)
        return outline(lat, lon, side)

    def metres_east(east_m):
        """(lon, lat) about east_m metres east of tile a's centre, by a small step along the parallel."""
        lat = 3.067 + (north - 16 - y0) / METRES_PER_DEG
        lon = 101.4897 + (west + 16 + east_m - x0) / (METRES_PER_DEG * math.cos(math.radians(3.067)))
        return lon, lat

    near_a, near_b, overlap_b, beyond = ring_at(-8), ring_at(28), ring_at(11), ring_at(80)
    assert [bf.tile_for([a, b], ring) for ring in (near_a, near_b, overlap_b, beyond)] == [a, b, b, None]
    assert bf.google_heights([a, b], [near_a, near_b, overlap_b, beyond]) == [105.0, 107.0, 107.0, None]
    assert bf.no_heights([near_a, near_b]) == [None, None]
