"""app/geo.py: point in polygon (holes, multipolygons, the edge rule), bbox, area, simplify, distance, nearest polygon.

Coordinates are GeoJSON order, (lon, lat). Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_geo.py
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from app import geo  # noqa: E402
import fetch_mbsa_sections as fms  # noqa: E402

M_PER_DEG = geo.EARTH_RADIUS_KM * 1000 * math.pi / 180   # one degree of latitude, in metres


def square(west=0.0, south=0.0, east=1.0, north=1.0):
    return [(west, south), (east, south), (east, north), (west, north), (west, south)]


def circle(radius_deg=0.01, count=360, centre=(101.5, 3.0)):
    cx, cy = centre
    ring = [(cx + radius_deg * math.cos(2 * math.pi * i / count), cy + radius_deg * math.sin(2 * math.pi * i / count)) for i in range(count)]
    return [*ring, ring[0]]


UNIT = [square()]
WITH_HOLE = [square(), square(0.25, 0.25, 0.75, 0.75)]
TWO_PARTS = [[square(0, 0, 1, 1)], [square(2, 0, 3, 1)]]


# ---------- point in polygon

@pytest.mark.parametrize("x, y, expected", [
    (0.5, 0.5, True), (1.5, 0.5, False), (-0.1, 0.5, False), (0.5, 1.1, False), (0.5, -0.1, False),
])
def test_a_point_is_inside_or_outside_a_square(x, y, expected):
    assert geo.point_in_polygon(x, y, UNIT) is expected


@pytest.mark.parametrize("x, y", [(0.5, 0.0), (0.5, 1.0), (0.0, 0.5), (1.0, 0.5)])
def test_a_point_exactly_on_an_edge_counts_as_inside(x, y):
    assert geo.point_in_polygon(x, y, UNIT) is True


@pytest.mark.parametrize("x, y", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
def test_a_point_exactly_on_a_vertex_counts_as_inside(x, y):
    assert geo.point_in_polygon(x, y, UNIT) is True


def test_a_point_just_past_an_edge_is_outside():
    assert geo.point_in_polygon(1.0 + 1e-9, 0.5, UNIT) is False


def test_the_ray_is_right_when_it_passes_exactly_through_a_vertex():
    diamond = [[(0, 1), (1, 0), (2, 1), (1, 2), (0, 1)]]
    assert geo.point_in_polygon(1.0, 1.0, diamond) is True     # level with the left and right corners
    assert geo.point_in_polygon(-0.5, 1.0, diamond) is False   # the same ray, starting left of the left corner
    assert geo.point_in_polygon(2.5, 1.0, diamond) is False


def test_the_ring_direction_does_not_matter():
    assert geo.point_in_polygon(0.5, 0.5, [list(reversed(square()))]) is True


def test_a_point_in_a_hole_is_outside_and_one_on_the_hole_edge_is_inside():
    assert geo.point_in_polygon(0.5, 0.5, WITH_HOLE) is False
    assert geo.point_in_polygon(0.1, 0.1, WITH_HOLE) is True
    assert geo.point_in_polygon(0.25, 0.5, WITH_HOLE) is True    # the hole's own edge belongs to the polygon
    assert geo.point_in_polygon(0.75, 0.75, WITH_HOLE) is True   # and so does its corner


def test_a_multipolygon_holds_a_point_in_any_part_but_not_in_the_gap():
    geometry = {"type": "MultiPolygon", "coordinates": TWO_PARTS}
    assert geo.point_in_geometry(0.5, 0.5, geometry) is True
    assert geo.point_in_geometry(2.5, 0.5, geometry) is True
    assert geo.point_in_geometry(1.5, 0.5, geometry) is False


def test_a_polygon_geometry_works_like_its_single_polygon():
    geometry = {"type": "Polygon", "coordinates": WITH_HOLE}
    assert geo.point_in_geometry(0.1, 0.1, geometry) is True
    assert geo.point_in_geometry(0.5, 0.5, geometry) is False


def test_a_geometry_that_is_not_an_area_is_refused():
    with pytest.raises(ValueError, match="Polygon"):
        geo.point_in_geometry(0, 0, {"type": "Point", "coordinates": [0, 0]})


# ---------- bbox

def test_bbox_of_a_polygon_and_of_a_multipolygon():
    assert geo.bbox({"type": "Polygon", "coordinates": WITH_HOLE}) == (0.0, 0.0, 1.0, 1.0)
    assert geo.bbox({"type": "MultiPolygon", "coordinates": TWO_PARTS}) == (0.0, 0.0, 3.0, 1.0)


def test_in_bbox_includes_the_edge_and_a_margin_widens_it():
    box = (0.0, 0.0, 1.0, 1.0)
    assert geo.in_bbox(1.0, 1.0, box) is True
    assert geo.in_bbox(1.001, 0.5, box) is False
    assert geo.in_bbox(1.001, 0.5, box, margin_deg=0.002) is True


# ---------- area

def test_the_area_of_a_box_matches_the_sphere_formula():
    ring = square(101.0, 3.0, 101.1, 3.1)
    expected = geo.EARTH_RADIUS_KM ** 2 * math.radians(0.1) * (math.sin(math.radians(3.1)) - math.sin(math.radians(3.0)))
    assert geo.ring_area_km2(ring) == pytest.approx(expected, rel=1e-9)


def test_the_area_method_is_the_one_the_section_fetch_tool_uses():
    ring = circle()
    assert geo.ring_area_km2(ring) == pytest.approx(fms.ring_area_km2(ring), rel=1e-12)
    polygon = [square(101, 3, 101.1, 3.1), square(101.02, 3.02, 101.04, 3.04)]
    assert geo.polygon_area_km2(polygon) == pytest.approx(fms.polygon_area_km2(polygon), rel=1e-12)


def test_a_hole_takes_its_area_away_and_a_multipolygon_adds_its_parts():
    full = geo.polygon_area_km2([square(101, 3, 101.1, 3.1)])
    holed = geo.polygon_area_km2([square(101, 3, 101.1, 3.1), square(101.025, 3.025, 101.075, 3.075)])
    assert holed == pytest.approx(full * 0.75, rel=1e-3)
    parts = {"type": "MultiPolygon", "coordinates": [[square(101, 3, 101.1, 3.1)], [square(101.2, 3, 101.3, 3.1)]]}
    assert geo.geometry_area_km2(parts) == pytest.approx(2 * full, rel=1e-3)


def test_area_is_the_same_whichever_way_the_ring_runs():
    assert geo.ring_area_km2(list(reversed(circle()))) == pytest.approx(geo.ring_area_km2(circle()), rel=1e-12)


# ---------- simplify

def has_self_crossing(ring):
    return geo.ring_self_intersects(ring)


def test_simplify_keeps_the_area_within_one_percent_and_the_ring_valid():
    ring = circle(radius_deg=0.01, count=720)   # a 1.1 km circle drawn with 720 points
    simple = geo.simplify_ring(ring, tolerance_m=5)
    assert len(simple) < len(ring) / 3
    assert simple[0] == simple[-1] and len(simple) >= 4
    assert not has_self_crossing(simple)
    assert abs(geo.ring_area_km2(simple) - geo.ring_area_km2(ring)) / geo.ring_area_km2(ring) < 0.01


def test_simplify_drops_points_that_sit_on_a_straight_side():
    ring = [(0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5), (0, 0)]
    assert geo.simplify_ring(ring, tolerance_m=1) == square()


def test_simplify_with_zero_tolerance_changes_nothing():
    assert geo.simplify_ring(circle(count=50), tolerance_m=0) == circle(count=50)


def test_simplify_never_collapses_a_ring_however_large_the_tolerance():
    tiny = [(101.5, 3.0), (101.5001, 3.0), (101.5001, 3.0001), (101.5, 3.0001), (101.5, 3.0)]
    simple = geo.simplify_ring(tiny, tolerance_m=10_000)
    assert simple[0] == simple[-1] and len(simple) >= 4
    triangle = [(0, 0), (1, 0), (0, 1), (0, 0)]
    assert geo.simplify_ring(triangle, tolerance_m=10_000_000) == triangle


def test_simplify_does_not_change_its_input():
    ring = circle(count=200)
    before = list(ring)
    geo.simplify_ring(ring, tolerance_m=20)
    assert ring == before


def test_a_simplified_ring_that_would_cross_itself_is_given_a_finer_tolerance():
    # a valid ring (a star-like shape, about 4 km across) where one Douglas-Peucker pass at 1.5 km crosses itself
    ring = [(101.51237, 3.00045), (101.53278, 3.00432), (101.51689, 3.00708), (101.50963, 3.00609), (101.51793, 3.0218),
            (101.50069, 3.01305), (101.48999, 2.9619), (101.51818, 2.99584), (101.51237, 3.00045)]
    assert not geo.ring_self_intersects(ring)
    assert geo.ring_self_intersects(geo._simplify_once(ring, 1500))
    simple = geo.simplify_ring(ring, tolerance_m=1500)
    assert not geo.ring_self_intersects(simple) and simple[0] == simple[-1] and len(simple) >= 4


def test_a_ring_that_already_crosses_itself_comes_back_unchanged():
    bow_tie_like = [(0, 0), (4, 0), (4, 3), (1, 3), (1, 1), (3, 1), (3, 2), (2, 2), (2.05, 1.5), (0, 3), (0, 0)]
    assert geo.simplify_ring(bow_tie_like, tolerance_m=50_000) == bow_tie_like


def test_simplify_a_geometry_keeps_every_part_and_drops_only_holes_smaller_than_the_tolerance():
    big_hole = [(101.02, 3.02), (101.08, 3.02), (101.08, 3.08), (101.02, 3.08), (101.02, 3.02)]
    pin_hole = [(101.05, 3.05), (101.05001, 3.05), (101.05001, 3.05001), (101.05, 3.05001), (101.05, 3.05)]
    outer = circle(radius_deg=0.2, count=400, centre=(101.05, 3.05))
    parts = [[outer, big_hole, pin_hole], [square(102, 3, 102.0005, 3.0005)]]
    simple = geo.simplify_geometry({"type": "MultiPolygon", "coordinates": parts}, tolerance_m=30)
    assert simple["type"] == "MultiPolygon" and len(simple["coordinates"]) == 2
    assert len(simple["coordinates"][0]) == 2            # the pin hole went, the big one stayed
    assert len(simple["coordinates"][1][0]) >= 4         # a speck of a part is still a valid ring
    assert abs(geo.geometry_area_km2(simple) - geo.geometry_area_km2({"type": "MultiPolygon", "coordinates": parts})) < 0.01 * geo.geometry_area_km2({"type": "MultiPolygon", "coordinates": parts})


def test_simplify_a_polygon_geometry_stays_a_polygon():
    simple = geo.simplify_geometry({"type": "Polygon", "coordinates": [circle(count=300)]}, tolerance_m=5)
    assert simple["type"] == "Polygon" and len(simple["coordinates"]) == 1


def test_ring_self_intersects_sees_a_bow_tie_and_not_a_square():
    assert geo.ring_self_intersects([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]) is True
    assert geo.ring_self_intersects(square()) is False


# ---------- distance

def test_distance_to_the_edge_of_a_box_in_metres():
    ring = square(101.0, 3.0, 101.1, 3.1)
    east = 101.1 + 10 / (M_PER_DEG * math.cos(math.radians(3.05)))   # ten metres east of the east side
    assert geo.distance_to_ring_m(east, 3.05, ring) == pytest.approx(10, rel=0.01)
    north = 3.1 + 25 / M_PER_DEG
    assert geo.distance_to_ring_m(101.05, north, ring) == pytest.approx(25, rel=0.01)


def test_distance_to_a_corner_is_the_straight_line_to_the_vertex():
    ring = square(0, 0, 1, 1)
    d = geo.distance_to_ring_m(1 + 30 / M_PER_DEG, 1 + 40 / M_PER_DEG, ring)
    assert d == pytest.approx(50, rel=0.01)


def test_distance_scales_longitude_by_the_latitude():
    ring = square(100.0, 60.0, 100.1, 60.1)
    assert geo.distance_to_ring_m(100.1 + 0.001, 60.05, ring) == pytest.approx(0.001 * M_PER_DEG * 0.5, rel=0.01)


def test_a_point_on_the_edge_is_zero_metres_away_and_an_inside_point_is_its_depth_from_the_edge():
    ring = square(0, 0, 1, 1)
    assert geo.distance_to_ring_m(0.5, 0.0, ring) == pytest.approx(0, abs=1e-6)
    assert geo.distance_to_ring_m(0.5, 0.01, ring) == pytest.approx(0.01 * M_PER_DEG, rel=0.01)


def test_distance_to_a_polygon_edge_counts_hole_edges_and_geometry_distance_is_zero_inside():
    polygon = [square(0, 0, 1, 1), square(0.4, 0.4, 0.6, 0.6)]
    assert geo.distance_to_polygon_edge_m(0.5, 0.5, polygon) == pytest.approx(0.1 * M_PER_DEG, rel=0.01)   # inside the hole
    geometry = {"type": "Polygon", "coordinates": polygon}
    assert geo.distance_to_geometry_m(0.1, 0.1, geometry) == 0.0
    assert geo.distance_to_geometry_m(0.5, 0.5, geometry) == pytest.approx(0.1 * M_PER_DEG, rel=0.01)
    assert geo.distance_to_geometry_m(1.0 + 100 / M_PER_DEG, 0.5, geometry) == pytest.approx(100, rel=0.01)


# ---------- containing and nearest

def item(name, west, east):
    geometry = {"type": "Polygon", "coordinates": [square(west, 0, east, 1)]}
    return {"id": name, "geometry": geometry, "bbox": geo.bbox(geometry)}


ITEMS = [item("a", 0, 1), item("b", 1, 2), item("far", 5, 6)]


def test_containing_gives_the_first_item_whose_area_holds_the_point():
    assert geo.containing(0.5, 0.5, ITEMS)["id"] == "a"
    assert geo.containing(1.5, 0.5, ITEMS)["id"] == "b"
    assert geo.containing(3.0, 0.5, ITEMS) is None


def test_a_point_on_the_edge_two_items_share_goes_to_the_first_in_the_list():
    assert geo.containing(1.0, 0.5, ITEMS)["id"] == "a"
    assert geo.containing(1.0, 0.5, list(reversed(ITEMS)))["id"] == "b"


def test_containing_works_without_a_precomputed_bbox():
    bare = [{"id": "a", "geometry": ITEMS[0]["geometry"]}]
    assert geo.containing(0.5, 0.5, bare)["id"] == "a"


def test_nearest_within_finds_the_inside_item_at_zero_and_an_outside_one_by_distance():
    found, metres = geo.nearest_within(0.5, 0.5, ITEMS, max_m=100)
    assert found["id"] == "a" and metres == 0.0
    near = 2.0 + 200 / M_PER_DEG
    found, metres = geo.nearest_within(near, 0.5, ITEMS, max_m=300)
    assert found["id"] == "b" and metres == pytest.approx(200, rel=0.01)


def test_nearest_within_gives_none_when_nothing_is_close_enough():
    assert geo.nearest_within(3.0, 0.5, ITEMS, max_m=300) is None


def test_nearest_within_picks_the_closer_of_two_and_the_first_on_a_tie():
    gap = [item("left", 0, 1), item("right", 1.002, 2)]
    found, _ = geo.nearest_within(1.0005, 0.5, gap, max_m=500)
    assert found["id"] == "left"
    found, _ = geo.nearest_within(1.0015, 0.5, gap, max_m=500)
    assert found["id"] == "right"
    found, _ = geo.nearest_within(1.001, 0.5, gap, max_m=500)
    assert found["id"] == "left"
