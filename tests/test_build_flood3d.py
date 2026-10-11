"""tools/build_flood3d.py on small made-up inputs, no network: building heights from OSM tags, Google's raster or a
marked guess; the shop's building found by containment or nearness; the flood squares kept in the box, each building
given the depths of the square under it and the shop's building the shop's own depths; the UTM sums; and Google's
median height over an outline."""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_flood3d as bf  # noqa: E402

SQUARE = [[101.0, 3.0], [101.001, 3.0], [101.001, 3.001], [101.0, 3.001], [101.0, 3.0]]
SHOP = "node-5565878632"   # the baked shop, read from the area's own premises.json


def way(way_id, ring, **tags):
    return {"type": "way", "id": way_id, "tags": {"building": "yes", **tags},
            "geometry": [{"lon": lon, "lat": lat} for lon, lat in ring]}


def test_height_comes_from_osm_then_google_then_a_marked_guess():
    assert bf.height_of({"height": "12 m"}, google=30.0) == (12.0, "osm")
    assert bf.height_of({"building:levels": "4"}) == (12.8, "osm")
    assert bf.height_of({"building": "house"}, google=7.04) == (7.0, "google")
    assert bf.height_of({"building": "house"}) == (6.4, "guess")
    assert bf.height_of({"building": "yes", "height": "tall"}) == (6.4, "guess")   # unreadable height: guessed
    assert bf.height_of({"building:levels": "0"}) == (6.4, "guess")


def test_shop_building_is_the_one_it_stands_in_else_the_nearest_close_by():
    far = [[101.01, 3.01], [101.011, 3.01], [101.011, 3.011], [101.01, 3.01]]
    assert bf.shop_building([far, SQUARE], lat=3.0005, lon=101.0005) == 1
    assert bf.shop_building([far, SQUARE], lat=3.0011, lon=101.0005) == 1   # ~11 m north of a wall, far from corners
    assert bf.shop_building([far, SQUARE], lat=3.005, lon=101.0005) is None


def test_buildings_skip_open_ways_mark_the_shop_and_ask_google_only_without_an_osm_height():
    open_ring = SQUARE[:-1] + [[101.0, 3.0002]]
    beside = [[p[0] + 0.002, p[1]] for p in SQUARE]
    asked = []
    answer = {"elements": [way(1, SQUARE, height="9"), way(2, open_ring), way(4, beside), {"type": "node", "id": 3}]}
    found = bf.buildings(answer, lat=3.0005, lon=101.0005, google=lambda ring: asked.append(ring) or 11.0)
    assert [f["id"] for f in found] == [1, 4]
    assert found[0]["properties"] == {"h": 9.0, "hsrc": "osm", "guessed": False, "shop": True}
    assert found[1]["properties"] == {"h": 11.0, "hsrc": "google", "guessed": False, "shop": False}
    assert asked == [beside]
    assert bf.buildings(answer, 3.0005, 101.0005)[1]["properties"]["hsrc"] == "guess"   # no raster: a guess


def test_squares_keep_wet_cells_in_the_box_and_buildings_take_the_depths_under_them():
    town = {"cell_deg": 0.001, "return_periods": [10, 50],
            "cells": [[3.0, 101.0, 0.4, 1.2], [3.0, 101.001, None, None], [3.5, 101.0, 2.0, 2.0], [3.001, 101.0, None, 0.3]]}
    water = bf.squares(town, (2.999, 100.999, 3.002, 101.002))
    assert [w["properties"] for w in water] == [{"d10": 0.4, "d50": 1.2}, {"d10": 0, "d50": 0.3}]

    inside = {"type": "Feature", "properties": {"h": 6.4}, "geometry": {"type": "Polygon", "coordinates": [[
        [101.0002, 3.0002], [101.0004, 3.0002], [101.0004, 3.0004], [101.0002, 3.0004], [101.0002, 3.0002]]]}}
    assert bf.with_depths(inside, water, ["d10", "d50"])["properties"] == {"h": 6.4, "d10": 0.4, "d50": 1.2}
    assert inside["properties"] == {"h": 6.4}   # the building given in is left as it was
    dry = {**inside, "geometry": {"type": "Polygon", "coordinates": [[[p[0] + 0.01, p[1]] for p in inside["geometry"]["coordinates"][0]]]}}
    assert bf.with_depths(dry, water, ["d10", "d50"])["properties"] == {"h": 6.4, "d10": 0, "d50": 0}


def test_the_shops_building_is_wet_to_the_shops_own_depths():
    baked = bf.bake("shah-alam", SHOP, 60, post=lambda query: {"elements": []})
    lat, lon = baked["place"]["lat"], baked["place"]["lon"]
    ring = [[lon - 1e-4, lat - 1e-4], [lon + 1e-4, lat - 1e-4], [lon + 1e-4, lat + 1e-4], [lon - 1e-4, lat + 1e-4]]
    answer = {"elements": [way(1, ring + ring[:1])]}
    [shop] = bf.bake("shah-alam", SHOP, 60, post=lambda query: answer)["buildings"]["features"]
    assert shop["properties"]["shop"] is True
    assert {k: shop["properties"][k] for k in ("d10", "d20", "d50")} == \
        {f"d{rp}": depth or 0 for rp, depth in baked["place"]["depth_m"].items()}


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


def grid_around(lat, lon, height, presence=0.9, size=40):
    """A Heights window of size x size 0.5 m squares centred on (lat, lon), each square from height(row, col)."""
    x, y = bf.utm_north(lat, lon, 47)
    west, north = x - size / 4, y + size / 4
    return bf.Heights(47, west, north, 0.5, size, [height(r, c) for r in range(size) for c in range(size)],
                      [presence] * size * size)


def outline(lat, lon, metres):
    """A (lon, lat) square about `metres` a side centred on the point."""
    d_lat, d_lon = metres / 2 / bf.METRES_PER_DEG, metres / 2 / (bf.METRES_PER_DEG * math.cos(math.radians(lat)))
    return [[lon - d_lon, lat - d_lat], [lon + d_lon, lat - d_lat], [lon + d_lon, lat + d_lat], [lon - d_lon, lat + d_lat],
            [lon - d_lon, lat - d_lat]]


def test_google_height_is_the_median_of_confident_squares_inside_the_outline():
    lat, lon = 3.067, 101.4897
    ring = outline(lat, lon, 4)
    inside = bf.squares_in(grid_around(lat, lon, lambda r, c: 0.0), ring)
    assert 56 <= len(inside) <= 72   # 4 m x 4 m: 8 x 8 squares, give or take an edge row
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0 if c % 2 else 12.0), ring) == 10.5
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0, presence=0.3), ring) is None   # not confident
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 1.5), ring) is None                 # under a storey
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0), outline(lat, lon, 1)) is None  # too few squares
    assert bf.google_height(grid_around(lat, lon, lambda r, c: 9.0), outline(lat, lon + 0.01, 4)) is None   # off grid


def test_bands_are_found_by_their_gdal_description_and_layers_by_their_year():
    metadata = ('<GDALMetadata><Item name="DESCRIPTION" sample="0" role="description">building_fractional_count</Item>'
                '<Item name="DESCRIPTION" sample="1" role="description">building_height</Item></GDALMetadata>')
    assert bf.band_of(metadata, "building_height") == 1
    with pytest.raises(bf.tr.TiffError):
        bf.band_of(metadata, "building_presence")
    assert bf.layer_year(bf.HEIGHTS_URL) == "2023" and bf.layer_year("local.tif") == ""
