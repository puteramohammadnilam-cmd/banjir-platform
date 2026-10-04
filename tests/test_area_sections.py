"""tools/area_sections.py: per-section counts and outlines (sections.json), on the fixture rasters and, when it is built,
the hidden city area's own files.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_area_sections.py
"""
import json
import sys
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import geo, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import area_sections as asec  # noqa: E402
import build_area as ba  # noqa: E402

FIXTURE_VIEW = (100.0, 8.0, 101.0, 10.0)
CITY = ROOT / "app" / "data" / "areas" / "_shah-alam"
CITY_BUILT = pytest.mark.skipif(not (CITY / "sections.json").is_file(), reason="the city area is not built here")
RPS = ("10", "20", "50")


def box_section(sid, west, south, east, north):
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"id": sid, "name": sid.upper(), "number_label": sid[-1], "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]},
            "bbox": (west, south, east, north), "area_km2": round(geo.geometry_area_km2({"type": "Polygon", "coordinates": [ring]}), 3)}


SECTIONS = [box_section("s-n", 100.0, 9.0, 101.0, 10.0), box_section("s-s", 100.0, 8.0, 101.0, 9.0)]


def node(osm_id, lon, lat, **tags):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "timestamp": "2026-01-02T03:04:05Z", "tags": tags}


@pytest.fixture
def built(tmp_path):
    depths = raster.DepthSet.load(fx.write_depth_set(tmp_path / "r"))
    pois = tmp_path / "pois.json"
    pois.write_text(json.dumps({"elements": [node(1, 100.875, 9.375, shop="bakery"), node(2, 100.125, 9.875, amenity="cafe"),
                                             node(3, 100.625, 8.875, amenity="pharmacy"), node(4, 100.375, 8.125, shop="kiosk")]}))
    roads = tmp_path / "roads.json"
    roads.write_text(json.dumps({"elements": [{"type": "way", "id": 1, "tags": {"highway": "residential"},
                                               "geometry": [{"lon": 100.0, "lat": 9.0}, {"lon": 101.0, "lat": 9.0}]}]}))
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    premises, town = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj), [], depths,
                              sections=SECTIONS)
    return premises, json.loads(json.dumps(town)), depths


def expected_wet_cells(town, section):
    west, south, east, north = section["bbox"]
    inside = [c for c in town["cells"] if west < c[1] + fx.PIXEL / 2 < east and south < c[0] + fx.PIXEL / 2 < north]
    return {rp: sum(1 for c in inside if c[2 + i]) for i, rp in enumerate(RPS)}


def test_each_section_counts_its_squares_wet_squares_and_businesses(built):
    premises, town, depths = built
    result = asec.build(premises, town, SECTIONS, depths)
    by_id = {s["id"]: s for s in result["sections"]}
    for section in SECTIONS:
        counts = by_id[section["id"]]["counts"]
        assert counts["cells"] == 16, "4 by 4 squares of 0.25 degrees"
        assert counts["wet_cells"] == expected_wet_cells(town, section)
        mine = [p for p in premises if p["section"] == section["id"]]
        assert counts["businesses"] == len(mine) == 2
        assert counts["wet_businesses"] == {rp: sum(1 for p in mine if p["depth_m"][rp]) for rp in RPS}
    assert result["outside_sections"]["cells"] == 45 - 32, "view_cells also reads the squares on the east and south edges"


def test_the_city_is_the_sum_of_the_sections_and_holds_every_business(built):
    premises, town, depths = built
    result = asec.build(premises, town, SECTIONS, depths)
    assert result["city"]["businesses"] == len(premises)
    assert result["city"]["cells"] == sum(s["counts"]["cells"] for s in result["sections"])
    for rp in RPS:
        assert result["city"]["wet_cells"][rp] == sum(s["counts"]["wet_cells"][rp] for s in result["sections"])


def test_a_section_row_has_what_the_api_contract_needs(built):
    premises, town, depths = built
    row = asec.build(premises, town, SECTIONS, depths)["sections"][0]
    assert set(row) == {"id", "name", "number_label", "bbox", "zoom", "area_km2", "counts", "outline"}
    assert row["bbox"] == [100.0, 9.0, 101.0, 10.0] and asec.MIN_ZOOM <= row["zoom"] <= asec.MAX_ZOOM
    assert set(row["counts"]) == {"businesses", "cells", "wet_businesses", "wet_cells"}


def test_a_business_without_a_known_section_stops_the_build(built):
    premises, town, depths = built
    with pytest.raises(ValueError, match="no known section.*node-"):
        asec.build([{**premises[0], "section": "elsewhere"}, *premises[1:]], town, SECTIONS, depths)


def test_a_bigger_flood_that_wets_fewer_is_refused():
    counts = {"businesses": 1, "cells": 1, "wet_businesses": {"10": 1, "20": 0, "50": 1}, "wet_cells": dict.fromkeys(RPS, 0)}
    with pytest.raises(ValueError, match="s-x: a bigger flood wets fewer businesses"):
        asec.check({"city": {**counts, "wet_businesses": dict.fromkeys(RPS, 0)}, "sections": [{"id": "s-x", "counts": counts}]},
                   [{}])


def test_zoom_fits_the_section_and_stays_in_range():
    assert asec.section_zoom((101.515, 3.008, 101.55, 3.042)) == 15   # a section the size of the old Sri Muda view
    assert asec.section_zoom((101.0, 3.0, 102.0, 4.0)) == asec.MIN_ZOOM
    assert asec.section_zoom((101.0, 3.0, 101.0001, 3.0001)) == asec.MAX_ZOOM


def test_the_outline_is_rounded_and_simplified_within_ten_metres():
    ring = [[101.5 + i * 0.00001, 3.0 + (0.00002 if i % 2 else 0.0)] for i in range(200)]   # a wiggly south edge
    ring += [[101.502, 3.01], [101.5, 3.01], ring[0]]
    shape = asec.outline({"type": "Polygon", "coordinates": [ring]})
    assert shape["type"] == "Polygon" and len(shape["coordinates"][0]) < 10
    assert all(round(v, 5) == v for pt in shape["coordinates"][0] for v in pt)
    before, after = geo.geometry_area_km2({"type": "Polygon", "coordinates": [ring]}), geo.geometry_area_km2(shape)
    assert after == pytest.approx(before, rel=0.01)


# ---------- the built city, when it is here

@CITY_BUILT
def test_the_city_sections_add_up_and_wet_counts_rise_with_flood_size():
    premises = json.loads((CITY / "premises.json").read_text(encoding="utf-8"))
    built = json.loads((CITY / "sections.json").read_text(encoding="utf-8"))
    assert len(built["sections"]) == 56 and len({s["id"] for s in built["sections"]}) == 56
    assert built["city"]["businesses"] == len(premises) == sum(s["counts"]["businesses"] for s in built["sections"])
    for counts in [built["city"], *(s["counts"] for s in built["sections"])]:
        for key in ("wet_businesses", "wet_cells"):
            assert counts[key]["10"] <= counts[key]["20"] <= counts[key]["50"]
        assert counts["wet_cells"]["50"] <= counts["cells"] and counts["wet_businesses"]["50"] <= counts["businesses"]
    assert {p["section"] for p in premises} <= {s["id"] for s in built["sections"]}


@CITY_BUILT
def test_the_city_area_json_has_the_section_fields_and_its_view_holds_the_build():
    area = json.loads((CITY / "area.json").read_text(encoding="utf-8"))
    town = json.loads((CITY / "town.json").read_text(encoding="utf-8"))
    assert area["id"] == "shah-alam" and area["default_section"] is None and area["history"] is None
    assert area["aliases"] == [{"id": "sri-muda", "section": "seksyen-25", "names": ["Taman Sri Muda", "Taman Seri Muda"]}]
    assert area["section_word"] == {"en": "Section", "ms": "Seksyen"}
    assert town["view"] == area["view"] and "not an official list" in area["notes"]["shelters"]
