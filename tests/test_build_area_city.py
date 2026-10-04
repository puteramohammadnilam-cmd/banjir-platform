"""tools/build_area.py at city scale: the road grid index, the section of each business (--sections) and --replaces.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_build_area_city.py
"""
import json
import os
import random
import sys
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_area as ba  # noqa: E402

FIXTURE_VIEW = (100.0, 8.0, 101.0, 10.0)
SEED = 20261005


def road(name, *pts):
    return {"name": name, "kind": "residential", "pts": list(pts)}


def random_roads(rng, count, span_m):
    """Polylines of 2 to 6 points: short streets, and now and then a long straight one across many squares."""
    roads = []
    for i in range(count):
        x, y = rng.uniform(0, span_m), rng.uniform(0, span_m)
        pts = [(x, y)]
        step = 3000 if i % 25 == 0 else 120
        for _ in range(rng.randint(1, 5)):
            x, y = x + rng.uniform(-step, step), y + rng.uniform(-step, step)
            pts.append((x, y))
        roads.append(road(f"r{i}", *pts))
    return roads


# ---------- the grid index finds what the brute-force search finds

def test_the_indexed_nearest_road_equals_brute_force_on_a_seeded_random_set():
    rng = random.Random(SEED)
    roads = random_roads(rng, 400, 8000)
    index = ba.RoadIndex(roads)
    points = [(rng.uniform(-2000, 10000), rng.uniform(-2000, 10000)) for _ in range(1500)]
    for p in points:
        slow, fast = ba.nearest_road(p, roads), index.nearest(p)
        assert fast[0] is slow[0] and fast[1] == slow[1] and fast[2] == slow[2], p


def test_ties_go_to_the_first_road_in_the_list_as_before():
    twin_a, twin_b = road("A", (0.0, 0.0), (1000.0, 0.0)), road("B", (0.0, 0.0), (1000.0, 0.0))
    other = road("C", (0.0, 600.0), (1000.0, 600.0))
    for roads in ([twin_a, twin_b, other], [twin_b, twin_a, other], [other, twin_b, twin_a]):
        p = (500.0, 100.0)
        assert ba.RoadIndex(roads).nearest(p)[0] is ba.nearest_road(p, roads)[0]


def test_a_road_far_from_the_point_is_still_found():
    roads = [road("Far", (50_000.0, 50_000.0), (50_100.0, 50_000.0))]
    found, dist, at = ba.RoadIndex(roads).nearest((0.0, 0.0))
    assert found["name"] == "Far" and at == (50_000.0, 50_000.0)


def test_the_index_with_no_roads_says_so():
    with pytest.raises(ValueError, match="no roads"):
        ba.RoadIndex([]).nearest((0.0, 0.0))


def test_a_one_point_square_of_the_index_is_250_m():
    assert ba.ROAD_CELL_M == 250


# ---------- the section of each business

def square_section(sid, west, south, side=0.01):
    ring = [[west, south], [west + side, south], [west + side, south + side], [west, south + side], [west, south]]
    geometry = {"type": "MultiPolygon", "coordinates": [[ring]]}
    return {"id": sid, "geometry": geometry, "bbox": (west, south, west + side, south + side)}


SECTIONS = [square_section("s-a", 101.50, 3.00), square_section("s-b", 101.51, 3.00)]


def row(osm_id, lon, lat):
    return {"id": f"node-{osm_id}", "lon": lon, "lat": lat}


def test_a_business_takes_the_section_that_holds_it_and_the_first_on_a_shared_edge():
    rows = ba.assign_sections([row(1, 101.505, 3.005), row(2, 101.515, 3.005), row(3, 101.51, 3.005)], SECTIONS)
    assert [r["section"] for r in rows] == ["s-a", "s-b", "s-a"]


def test_a_business_just_outside_takes_the_nearest_section_within_300_m():
    rows = ba.assign_sections([row(1, 101.505, 2.998)], SECTIONS)   # about 220 m south of s-a
    assert rows[0]["section"] == "s-a"


def test_a_business_farther_than_300_m_from_every_section_stops_the_build_naming_each():
    with pytest.raises(ValueError, match=r"2 businesses.*300 m.*node-7.*node-8"):
        ba.assign_sections([row(1, 101.505, 3.005), row(7, 101.505, 2.99), row(8, 101.6, 3.0)], SECTIONS)


def test_assigning_sections_leaves_the_rows_it_was_given_alone():
    given = [row(1, 101.505, 3.005)]
    ba.assign_sections(given, SECTIONS)
    assert "section" not in given[0]


# ---------- the build with sections, and --replaces

def write_json(path, elements):
    path.write_text(json.dumps({"elements": elements}), encoding="utf-8")
    return path


def node(osm_id, lon, lat, **tags):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "timestamp": "2026-01-02T03:04:05Z", "tags": tags}


@pytest.fixture
def city(tmp_path):
    pois = write_json(tmp_path / "pois.json", [node(1, 100.875, 9.375, shop="bakery", name="Bakery"),
                                               node(2, 100.125, 9.875, amenity="cafe", name="Cafe")])
    roads = write_json(tmp_path / "roads.json", [{"type": "way", "id": 1, "tags": {"highway": "residential"},
                                                  "geometry": [{"lon": 100.0, "lat": 9.375}, {"lon": 101.0, "lat": 9.375}]}])
    sections = [square_section("s-east", 100.5, 9.0, side=1.0), square_section("s-west", 100.0, 9.5, side=0.5)]
    return pois, roads, sections


def test_build_with_sections_writes_the_section_of_each_business(tmp_path, city):
    pois, roads, sections = city
    depths = raster.DepthSet.load(fx.write_depth_set(tmp_path / "r"))
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    premises, _ = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj), [], depths,
                           sections=sections)
    assert {p["id"]: p["section"] for p in premises} == {"node-1": "s-east", "node-2": "s-west"}
    plain, _ = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj), [], depths)
    assert all("section" not in p for p in plain), "no --sections, no section key: older builds stay byte for byte"


def test_main_reads_sections_and_lets_a_replaced_area_share_ids(tmp_path, city, monkeypatch):
    pois, roads, sections = city
    monkeypatch.setattr(ba.sections_io, "load_sections", lambda path: sections)
    monkeypatch.setattr(ba, "installed_ids", lambda area, replaces: {"node-1"} - ({"node-1"} if "old" in replaces else set()))
    argv = ["--area", "demo", "--view", *map(str, FIXTURE_VIEW), "--pois", str(pois), "--roads", str(roads),
            "--out", str(tmp_path / "out"), "--rasters", str(fx.write_depth_set(tmp_path / "r")),
            "--sections", str(tmp_path / "sections.geojson")]
    (tmp_path / "sections.geojson").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="another area"):
        ba.main(argv)
    assert ba.main([*argv, "--replaces", "old"]) == 0
    premises = json.loads((tmp_path / "out" / "premises.json").read_text(encoding="utf-8"))
    assert sorted(p["section"] for p in premises) == ["s-east", "s-west"]


def test_installed_ids_leave_out_the_area_itself_and_the_replaced_ones():
    every = ba.installed_ids("nothing-here", ())
    assert every and ba.installed_ids("kuantan", ()) < every
    assert ba.installed_ids("nothing-here", ("kuantan",)) == ba.installed_ids("kuantan", ())


# ---------- the hidden city area rebuilds byte for byte from its saved inputs

CITY = ROOT / "app" / "data" / "areas" / "_shah-alam"
CITY_RAW = Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources") / "shah_alam"
CITY_INPUTS = [CITY_RAW / "city_osm" / name for name in ("pois.json", "roads.json", "shelters.json")] + \
    [CITY_RAW / "mbsa_sections" / "sections.geojson"]


def city_inputs_or_skip():
    missing = [p.name for p in CITY_INPUTS if not p.is_file()]
    if missing or not (CITY / "premises.json").is_file():
        pytest.skip(f"the city inputs or build are not on this machine: {', '.join(missing) or 'premises.json'}")
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")


def test_the_city_rebuilds_byte_identical_with_every_business_in_a_section(tmp_path):
    city_inputs_or_skip()
    import area_sections
    pois, roads, shelters, sections = CITY_INPUTS
    view = json.loads((CITY / "area.json").read_text(encoding="utf-8"))["view"]
    (tmp_path / "area.json").write_bytes((CITY / "area.json").read_bytes())
    assert ba.main(["--area", "shah-alam", "--view", *map(str, view), "--pois", str(pois), "--roads", str(roads),
                    "--shelters", str(shelters), "--sections", str(sections), "--replaces", "sri-muda",
                    "--out", str(tmp_path)]) == 0
    assert area_sections.main(["--area-dir", str(tmp_path), "--sections", str(sections)]) == 0
    for name in ("premises.json", "town.json", "sections.json"):
        assert (tmp_path / name).read_bytes() == (CITY / name).read_bytes(), name
