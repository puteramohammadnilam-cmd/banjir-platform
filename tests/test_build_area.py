"""The general area builder, tools/build_area.py (plan card A9).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_build_area.py -rs

The parity tests rebuild Sri Muda from the raw files it was first built from and compare the bytes with the files in
app/data/areas/sri-muda. They skip, saying why, when the raw files or the depth rasters are not on this machine.
"""
import json
import math
import sys
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import areas, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_area as ba  # noqa: E402

RAW = ROOT.parent / "05_Raw_Data_Sources"
SRI_MUDA_RAW = RAW / "shah_alam"
SRI_MUDA_POIS = SRI_MUDA_RAW / "overpass_sri_muda_pois.json"
SRI_MUDA_ROADS = SRI_MUDA_RAW / "overpass_sri_muda_roads.json"
SRI_MUDA_VIEW = (101.515, 3.008, 101.550, 3.042)
SRI_MUDA_DIR = ROOT / "app" / "data" / "areas" / "sri-muda"
FIXTURE_VIEW = (100.0, 8.0, 101.0, 9.0)   # inside the fixture grid (100-110 E, 2.5-10 N, squares of 0.25 degrees)


# ---------- helpers

def node(osm_id: int, lon: float, lat: float, **tags) -> dict:
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "timestamp": "2026-01-02T03:04:05Z", "tags": tags}


def way_centre(osm_id: int, lon: float, lat: float, **tags) -> dict:
    return {"type": "way", "id": osm_id, "center": {"lat": lat, "lon": lon}, "timestamp": "2025-12-31T00:00:00Z",
            "tags": tags}


def road(kind: str, *points: tuple[float, float], name: str | None = None) -> dict:
    tags = {"highway": kind, **({"name": name} if name else {})}
    return {"type": "way", "id": 1, "tags": tags, "geometry": [{"lon": lon, "lat": lat} for lon, lat in points]}


def write_json(path: Path, elements: list[dict]) -> Path:
    path.write_text(json.dumps({"elements": elements}), encoding="utf-8")
    return path


@pytest.fixture
def depths(tmp_path):
    return raster.DepthSet.load(fx.write_depth_set(tmp_path / "rasters"))


@pytest.fixture
def inputs(tmp_path):
    """Three businesses on known fixture squares, one road and one relief centre."""
    pois = write_json(tmp_path / "pois.json", [
        node(1, 100.875, 9.375, shop="bakery", name="Bakery", brand="Chain"),   # row 2, col 3: wet at all three
        node(2, 100.125, 9.875, amenity="cafe", name="Dry Cafe"),               # row 0, col 0: no data, dry
        way_centre(3, 100.625, 8.875, amenity="pharmacy"),                      # row 4, col 2: wet, unnamed
        node(4, 100.5, 9.0, amenity="bank", name="Bank"),                       # not a business we count
    ])
    roads = write_json(tmp_path / "roads.json", [road("residential", (100.0, 9.375), (101.0, 9.375), name="Jalan A")])
    shelters = tmp_path / "shelters.json"
    shelters.write_text(json.dumps({"located": [{"name": "Hall", "lat": 9.4, "lon": 100.9}]}), encoding="utf-8")
    return pois, roads, shelters


# ---------- parity with the built Sri Muda files

def real_inputs_or_skip():
    missing = [p.name for p in (SRI_MUDA_POIS, SRI_MUDA_ROADS) if not p.is_file()]
    if missing:
        pytest.skip(f"the raw OpenStreetMap files are not on this machine: {', '.join(missing)}")
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")


def test_rebuilding_sri_muda_is_byte_identical(tmp_path):
    real_inputs_or_skip()
    code = ba.main(["--area", "sri-muda", "--view", *map(str, SRI_MUDA_VIEW), "--pois", str(SRI_MUDA_POIS),
                    "--roads", str(SRI_MUDA_ROADS), "--out", str(tmp_path)])
    assert code == 0
    for name in ("premises.json", "town.json"):
        assert (tmp_path / name).read_bytes() == (SRI_MUDA_DIR / name).read_bytes(), name


def test_sri_muda_numbers_match_the_handover():
    real_inputs_or_skip()
    premises, town = ba.build(SRI_MUDA_VIEW, ba.load_businesses(SRI_MUDA_POIS), ba.load_roads(
        SRI_MUDA_ROADS, ba.Projection.for_view(SRI_MUDA_VIEW)), [], raster.depth_set())
    wet = {rp: sum(1 for p in premises if p["depth_m"][rp]) for rp in ("10", "100", "500")}
    assert (len(premises), wet, len(town["cells"])) == (204, {"10": 174, "100": 183, "500": 188}, 1575)


# ---------- the projection: cos(lat) comes from the view's centre

def test_projection_takes_cos_of_the_view_centre_latitude():
    here = ba.Projection.for_view(SRI_MUDA_VIEW)
    assert here.m_per_deg_lon == 111320.0 * math.cos(math.radians(3.025))   # the value the old build fixed
    far = ba.Projection.for_view((102.185, 5.513, 102.22, 5.547))
    assert far.m_per_deg_lon == pytest.approx(111320.0 * math.cos(math.radians(5.53)))
    assert far.m_per_deg_lon < here.m_per_deg_lon


def test_projection_round_trips_a_point():
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    lon, lat = proj.to_lonlat(*proj.to_m(100.5, 8.5))
    assert (lon, lat) == pytest.approx((100.5, 8.5), abs=1e-9)


# ---------- reading the raw files

def test_load_businesses_keeps_shops_crafts_eateries_and_pharmacies(inputs):
    rows = ba.load_businesses(inputs[0])
    assert [r["id"] for r in rows] == ["node-1", "node-2", "way-3"]   # the bank is left out
    first, _, third = rows
    assert (first["sector"], first["kind"], first["is_chain"], first["edited"]) == ("shop", "bakery", True, "2026-01-02")
    assert (rows[1]["sector"], rows[1]["kind"]) == ("eatery", "cafe")
    assert (third["lon"], third["lat"], third["name"], third["sector"]) == (100.625, 8.875, None, "shop")


def test_load_roads_keeps_vehicle_roads_only(tmp_path):
    path = write_json(tmp_path / "roads.json", [
        road("residential", (100.0, 9.0), (100.1, 9.0), name="Jalan A"),
        road("footway", (100.0, 9.0), (100.1, 9.0)),
        road("service", (100.0, 9.0)),   # one point is not a road
    ])
    roads = ba.load_roads(path, ba.Projection.for_view(FIXTURE_VIEW))
    assert [(r["name"], r["kind"], len(r["pts"])) for r in roads] == [("Jalan A", "residential", 2)]


def test_load_shelters_is_empty_without_a_file(tmp_path, inputs):
    assert ba.load_shelters(None) == []
    assert ba.load_shelters(tmp_path / "absent.json") == []
    assert ba.load_shelters(inputs[2]) == [{"name": "Hall", "lat": 9.4, "lon": 100.9}]


def test_nearest_road_picks_the_closest_segment():
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    near = {"name": "Near", "kind": "residential", "pts": [proj.to_m(100.0, 9.0), proj.to_m(101.0, 9.0)]}
    far = {"name": "Far", "kind": "residential", "pts": [proj.to_m(100.0, 9.5), proj.to_m(101.0, 9.5)]}
    found, dist, at = ba.nearest_road(proj.to_m(100.5, 9.001), [far, near])
    assert found["name"] == "Near" and dist == pytest.approx(0.001 * ba.M_PER_DEG_LAT, rel=1e-6)
    assert proj.to_lonlat(*at) == pytest.approx((100.5, 9.0), abs=1e-9)


def test_nearest_road_with_no_roads_says_so():
    with pytest.raises(ValueError, match="no roads"):
        ba.nearest_road((0.0, 0.0), [])


# ---------- building one area

def test_build_reads_each_premise_from_the_rasters(depths, inputs):
    pois, roads, shelters = inputs
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    premises, town = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj),
                              ba.load_shelters(shelters), depths)
    assert [p["name"] for p in premises] == ["Dry Cafe", "Bakery", "Unnamed (no name on the map)"]   # eateries, then shops; by name
    by_id = {p["id"]: p for p in premises}
    assert by_id["node-1"]["depth_m"] == {"10": 2.13, "100": 2.63, "500": 3.13}
    assert by_id["node-2"]["depth_m"] == {"10": None, "100": None, "500": None}
    assert by_id["node-1"]["is_chain"] is True and by_id["node-2"]["is_chain"] is False
    assert by_id["node-1"]["road"] == {"name": "Jalan A", "kind": "residential", "distance_m": 0,
                                       "depth_m": {"10": 2.13, "100": 2.63, "500": 3.13}}
    apart = math.hypot(0.025 * proj.m_per_deg_lon, 0.025 * ba.M_PER_DEG_LAT)   # 0.025 degrees east and north
    assert by_id["node-1"]["shelter"] == {"name": "Hall", "distance_m": round(apart)}
    assert by_id["node-1"]["map_last_edited"] == "2026-01-02"
    assert town["shelters"] == [{"name": "Hall", "lat": 9.4, "lon": 100.9}]


def test_build_town_holds_the_wet_squares_of_the_view(depths, inputs):
    pois, roads, _ = inputs
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    _, town = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj), [], depths)
    assert town["view"] == FIXTURE_VIEW and town["return_periods"] == (10, 100, 500)
    assert town["cell_deg"] == fx.PIXEL and town["shelters"] == []
    assert town["cells"] == depths.view_cells(FIXTURE_VIEW) and town["cells"]


def test_premise_without_a_shelter_has_null(depths, inputs):
    pois, roads, _ = inputs
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    premises, _ = ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(roads, proj), [], depths)
    assert all(p["shelter"] is None for p in premises)


def test_build_refuses_a_business_outside_the_loaded_rasters(depths, inputs, tmp_path):
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    pois = write_json(tmp_path / "far.json", [node(9, 50.0, 8.5, shop="kiosk", name="Far")])
    with pytest.raises(ValueError, match="node-9"):
        ba.build(FIXTURE_VIEW, ba.load_businesses(pois), ba.load_roads(inputs[1], proj), [], depths)


def test_build_refuses_a_view_outside_the_rasters(depths, inputs):
    proj = ba.Projection.for_view(FIXTURE_VIEW)
    with pytest.raises(ValueError, match="view"):
        ba.build((50.0, 8.0, 51.0, 9.0), ba.load_businesses(inputs[0]), ba.load_roads(inputs[1], proj), [], depths)


def test_check_premises_refuses_nothing_to_show_or_a_repeated_id():
    wet = {"10": 1.0, "100": 1.0, "500": 1.0}
    one = {"id": "node-1", "depth_m": wet}
    ba.check_premises([one, {"id": "node-2", "depth_m": wet}])
    with pytest.raises(ValueError, match="no businesses"):
        ba.check_premises([])
    with pytest.raises(ValueError, match="repeated"):
        ba.check_premises([one, one])


def test_check_premises_refuses_a_bigger_flood_that_wets_fewer():
    dry = {"10": None, "100": None, "500": None}
    wet_10_only = {"10": 1.0, "100": None, "500": None}
    with pytest.raises(ValueError, match="wet"):
        ba.check_premises([{"id": "node-1", "depth_m": wet_10_only}, {"id": "node-2", "depth_m": dry}])


# ---------- writing the files and the command line

def run_cli(tmp_path, inputs, *extra, view=FIXTURE_VIEW, raster_dir=None):
    pois, roads, _ = inputs
    argv = ["--area", "demo", "--view", *map(str, view), "--pois", str(pois), "--roads", str(roads),
            "--out", str(tmp_path / "out"), "--rasters", str(raster_dir), *extra]
    return ba.main(argv)


def test_main_writes_premises_and_town(tmp_path, inputs, capsys):
    folder = fx.write_depth_set(tmp_path / "r")
    assert run_cli(tmp_path, inputs, "--shelters", str(inputs[2]), raster_dir=folder) == 0
    premises = json.loads((tmp_path / "out" / "premises.json").read_text(encoding="utf-8"))
    town = json.loads((tmp_path / "out" / "town.json").read_text(encoding="utf-8"))
    assert len(premises) == 3 and town["view"] == list(FIXTURE_VIEW) and len(town["shelters"]) == 1
    assert "3 premises" in capsys.readouterr().out


def test_main_output_is_stable_between_runs(tmp_path, inputs):
    folder = fx.write_depth_set(tmp_path / "r")
    run_cli(tmp_path, inputs, raster_dir=folder)
    first = {n: (tmp_path / "out" / n).read_bytes() for n in ("premises.json", "town.json")}
    run_cli(tmp_path, inputs, raster_dir=folder)
    assert first == {n: (tmp_path / "out" / n).read_bytes() for n in first}


def test_main_refuses_a_view_that_disagrees_with_area_json(tmp_path, inputs):
    folder = fx.write_depth_set(tmp_path / "r")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "area.json").write_text(json.dumps({"view": [1, 2, 3, 4]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="area.json"):
        run_cli(tmp_path, inputs, raster_dir=folder)
    assert not (tmp_path / "out" / "premises.json").exists()   # nothing written


@pytest.mark.parametrize("view", [("1", "2", "1", "3"), ("1", "5", "2", "3"), ("1", "2", "x", "4"), ("1", "2", "3")])
def test_main_refuses_a_bad_view(tmp_path, inputs, view):
    folder = fx.write_depth_set(tmp_path / "r")
    pois, roads, _ = inputs
    argv = ["--area", "demo", "--view", *view, "--pois", str(pois), "--roads", str(roads), "--out", str(tmp_path / "o"),
            "--rasters", str(folder)]
    with pytest.raises(SystemExit):
        ba.main(argv)


def test_main_refuses_a_folder_with_no_rasters(tmp_path, inputs):
    with pytest.raises(SystemExit, match="raster"):
        run_cli(tmp_path, inputs, raster_dir=tmp_path / "empty")


def test_main_names_a_missing_input_file(tmp_path, inputs):
    folder = fx.write_depth_set(tmp_path / "r")
    argv = ["--area", "demo", "--view", *map(str, FIXTURE_VIEW), "--pois", str(tmp_path / "nope.json"),
            "--roads", str(inputs[1]), "--out", str(tmp_path / "o"), "--rasters", str(folder)]
    with pytest.raises(SystemExit, match="nope.json"):
        ba.main(argv)


def test_the_old_builder_is_gone():
    assert not (ROOT / "tools" / "build_data.py").exists()


# ---------- Kuala Krai, the third curated area (gate G-A3)

KRAI_SHIPPED = pytest.mark.skipif(not (ROOT / "app" / "data" / "areas" / "kuala-krai").exists(),
                                  reason="Kuala Krai is built but not shipped as an area yet (05_Raw_Data_Sources/kuala_krai/SOURCES.md)")


@KRAI_SHIPPED
def test_kuala_krai_is_the_third_area_and_sri_muda_stays_the_default():
    assert [a.id for a in areas.load_all()][0] == "sri-muda"
    krai = areas.get("kuala-krai")
    assert krai is not None and krai.history is None and krai.council == "Majlis Daerah Kuala Krai"
    assert "not checked on the ground" in krai.notes["businesses"]
    assert "shelters" in krai.notes and areas.counts(krai)["shelters"] == 0


@KRAI_SHIPPED
def test_kuala_krai_rebuilds_byte_identical_from_its_saved_overpass_answers(tmp_path):
    folder = RAW / "kuala_krai"
    pois, roads = folder / "overpass_kuala_krai_pois.json", folder / "overpass_kuala_krai_roads.json"
    if not (pois.is_file() and roads.is_file()):
        pytest.skip("the saved Overpass answers for Kuala Krai are not on this machine")
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")
    krai = areas.get("kuala-krai")
    ba.main(["--area", "kuala-krai", "--view", *map(str, krai.view), "--pois", str(pois), "--roads", str(roads),
             "--out", str(tmp_path)])
    for name in ("premises.json", "town.json"):
        assert (tmp_path / name).read_bytes() == (ROOT / "app" / "data" / "areas" / "kuala-krai" / name).read_bytes()


@pytest.mark.parametrize("area_id, folder", [("kuantan", "kuantan"), ("kota-bharu", "kota_bharu"),
                                             ("kuala-terengganu", "kuala_terengganu")])
def test_the_screened_towns_rebuild_byte_identical_from_their_saved_overpass_answers(tmp_path, area_id, folder):
    pois, roads = RAW / folder / f"overpass_{folder}_pois.json", RAW / folder / f"overpass_{folder}_roads.json"
    if not (pois.is_file() and roads.is_file()):
        pytest.skip(f"the saved Overpass answers for {area_id} are not on this machine")
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")
    area = areas.get(area_id)
    ba.main(["--area", area_id, "--view", *map(str, area.view), "--pois", str(pois), "--roads", str(roads),
             "--out", str(tmp_path)])
    for name in ("premises.json", "town.json"):
        assert (tmp_path / name).read_bytes() == (ROOT / "app" / "data" / "areas" / area_id / name).read_bytes()
