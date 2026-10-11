"""tools/build_flood3d.py on small made-up inputs, no network: building heights from OSM tags or a guess, the shop's
building found by containment or nearness, the flood squares kept in the box, and each building given the depths of the
square under it."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_flood3d as bf  # noqa: E402

SQUARE = [[101.0, 3.0], [101.001, 3.0], [101.001, 3.001], [101.0, 3.001], [101.0, 3.0]]


def way(way_id, ring, **tags):
    return {"type": "way", "id": way_id, "tags": {"building": "yes", **tags},
            "geometry": [{"lon": lon, "lat": lat} for lon, lat in ring]}


def test_height_comes_from_osm_then_floors_then_a_marked_guess():
    assert bf.height_of({"height": "12 m"}) == (12.0, False)
    assert bf.height_of({"building:levels": "4"}) == (12.8, False)
    assert bf.height_of({"building": "house"}) == (6.4, True)
    assert bf.height_of({"building": "yes", "height": "tall"}) == (6.4, True)   # unreadable height: guessed
    assert bf.height_of({"building:levels": "0"}) == (6.4, True)


def test_shop_building_is_the_one_it_stands_in_else_the_nearest_close_by():
    far = [[101.01, 3.01], [101.011, 3.01], [101.011, 3.011], [101.01, 3.01]]
    assert bf.shop_building([far, SQUARE], lat=3.0005, lon=101.0005) == 1
    assert bf.shop_building([far, SQUARE], lat=3.0011, lon=101.0005) == 1   # ~11 m north of a corner
    assert bf.shop_building([far, SQUARE], lat=3.005, lon=101.0005) is None


def test_buildings_skip_open_ways_and_mark_the_shop():
    open_ring = SQUARE[:-1] + [[101.0, 3.0002]]
    answer = {"elements": [way(1, SQUARE, height="9"), way(2, open_ring), {"type": "node", "id": 3}]}
    [only] = bf.buildings(answer, lat=3.0005, lon=101.0005)
    assert only["id"] == 1 and only["properties"] == {"h": 9.0, "guessed": False, "shop": True}


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
