"""Re-sampling an area whose OpenStreetMap inputs were not kept, tools/resample_area.py (plan WS-A, Kota Tinggi).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_resample_area.py -rs

The fixture grids are tiny GeoTIFFs (tests/tiff_fixture.py): squares of 0.25 degrees, about 28 km, so a road "within
distance_m" of a business is placed tens of kilometres away to reach a neighbouring square.
"""
import json
import os
import sys
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import areas, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import resample_area as ra  # noqa: E402

RAW = Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources")
OLD_JRC = RAW / "jrc_glofas_v2_1"
KOTA_TINGGI_OLD = RAW / "kota_tinggi" / "built_rp10_100_500"   # the area as built before 4 Oct 2026, kept outside the repo
VIEW = [100.0, 8.5, 101.0, 10.0]   # inside the 8 x 8 fixture grid, which ends at 8 N
ROWS, COLS = 8, 8
SQUARE_M = 0.25 * 110574.0   # one fixture square, north to south


def grid_values(base: float, **squares) -> list[list[float]]:
    """ROWS x COLS depths r + c/100 + base, with chosen squares ("r2c3": value) set apart."""
    chosen = {tuple(int(x) for x in key[1:].split("c")): value for key, value in squares.items()}
    return [[chosen.get((r, c), r + c / 100 + base) for c in range(COLS)] for r in range(ROWS)]


def write_set(folder: Path, layers: dict[int, list[list[float]]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for rp, values in layers.items():
        fx.write_depth_tiff(folder / f"ID211_N10_E100_RP{rp}_depth.tif", values, empty=())
    return folder


def old_layers(**squares) -> dict[int, list[list[float]]]:
    return {10: grid_values(0.1, **squares.get("rp10", {})), 100: grid_values(0.6, **squares.get("rp100", {})),
            500: grid_values(1.1, **squares.get("rp500", {}))}


def new_layers(**squares) -> dict[int, list[list[float]]]:
    return {10: grid_values(0.1, **squares.get("rp10", {})), 20: grid_values(0.3, **squares.get("rp20", {})),
            50: grid_values(0.5, **squares.get("rp50", {}))}


def premise(pid: str, lon: float, lat: float, depth: dict, road_depth: dict, distance_m: int = 0) -> dict:
    return {"id": pid, "name": pid, "sector": "shop", "kind": "kiosk", "is_chain": False, "lat": lat, "lon": lon,
            "map_last_edited": "2020-01-01", "depth_m": depth,
            "road": {"name": "Jalan A", "kind": "residential", "distance_m": distance_m, "depth_m": road_depth},
            "shelter": None}


def old_depth(r: int, c: int) -> dict:
    return {"10": round(r + c / 100 + 0.1, 2), "100": round(r + c / 100 + 0.6, 2), "500": round(r + c / 100 + 1.1, 2)}


def centre(r: int, c: int) -> tuple[float, float]:
    """(lon, lat) of a fixture square's centre."""
    return 100.0 + (c + 0.5) * 0.25, 10.0 - (r + 0.5) * 0.25


def write_area(folder: Path, premises: list[dict], old_set: raster.DepthSet) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    town = {"view": VIEW, "cell_deg": 0.25, "return_periods": [10, 100, 500], "cells": old_set.view_cells(VIEW),
            "shelters": [{"name": "Hall", "lat": 9.0, "lon": 100.5}]}
    (folder / "premises.json").write_text(json.dumps(premises, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "town.json").write_text(json.dumps(town, separators=(",", ":")), encoding="utf-8")
    return folder


@pytest.fixture
def sets(tmp_path):
    old = write_set(tmp_path / "old", old_layers())
    new = write_set(tmp_path / "new", new_layers())
    return ra.load_old(old), raster.DepthSet.load(new), old, new


# ---------- loading the old files

def test_the_old_files_load_in_the_old_order(sets):
    old_set, new_set, _, _ = sets
    assert ra.OLD_PERIODS == (10, 100, 500)
    assert ra.old_depths(old_set, *centre(2, 3)) == old_depth(2, 3)
    assert new_set.depths(*centre(2, 3)) == {"10": 2.13, "20": 2.33, "50": 2.53}


def test_loading_old_files_refuses_a_grid_short_of_a_size(tmp_path):
    folder = write_set(tmp_path / "old", {10: grid_values(0.1), 100: grid_values(0.6)})
    with pytest.raises(raster.RasterError, match="500"):
        ra.load_old(folder)


# ---------- the road's square

def test_the_road_square_is_the_one_whose_old_depths_match(sets):
    old_set, new_set, _, _ = sets
    lon, lat = centre(2, 3)
    road = ra.road_depths(premise("node-1", lon, lat, old_depth(2, 3), old_depth(2, 4), round(SQUARE_M)),
                          VIEW, old_set, new_set)
    assert road == {"10": 2.14, "20": 2.34, "50": 2.54}


def test_a_road_square_too_far_for_its_distance_is_not_taken(sets):
    old_set, new_set, _, _ = sets
    lon, lat = centre(2, 3)
    with pytest.raises(ra.ResampleError, match="node-1.*no square"):
        ra.road_depths(premise("node-1", lon, lat, old_depth(2, 3), old_depth(2, 5), 10), VIEW, old_set, new_set)


def test_two_matching_squares_that_agree_on_the_new_depths_are_fine(tmp_path):
    twin = {"rp10": {"r2c4": 2.13}, "rp100": {"r2c4": 2.63}, "rp500": {"r2c4": 3.13}}   # (2, 4) reads as (2, 3)
    old_set = ra.load_old(write_set(tmp_path / "old", old_layers(**twin)))
    new_set = raster.DepthSet.load(write_set(tmp_path / "new", new_layers(
        rp10={"r2c4": 2.13}, rp20={"r2c4": 2.33}, rp50={"r2c4": 2.53})))
    lon, lat = centre(2, 3)
    assert ra.road_depths(premise("node-1", lon, lat, old_depth(2, 3), old_depth(2, 3), round(SQUARE_M)),
                          VIEW, old_set, new_set) == {"10": 2.13, "20": 2.33, "50": 2.53}


def test_two_matching_squares_with_different_new_depths_stop_the_run(tmp_path):
    twin = {"rp10": {"r2c4": 2.13}, "rp100": {"r2c4": 2.63}, "rp500": {"r2c4": 3.13}}
    old_set = ra.load_old(write_set(tmp_path / "old", old_layers(**twin)))
    new_set = raster.DepthSet.load(write_set(tmp_path / "new", new_layers()))   # (2, 4) differs from (2, 3) here
    lon, lat = centre(2, 3)
    with pytest.raises(ra.ResampleError, match="node-1.*ambiguous"):
        ra.road_depths(premise("node-1", lon, lat, old_depth(2, 3), old_depth(2, 3), round(SQUARE_M)),
                       VIEW, old_set, new_set)


def test_a_dry_road_stays_dry_when_every_dry_square_near_it_stays_dry(tmp_path):
    dry = {f"r2c{c}": fx.NODATA for c in (3, 4)}
    old_set = ra.load_old(write_set(tmp_path / "old", old_layers(rp10=dry, rp100=dry, rp500=dry)))
    new_set = raster.DepthSet.load(write_set(tmp_path / "new", new_layers(rp10=dry, rp20=dry, rp50=dry)))
    lon, lat = centre(2, 3)
    none = {"10": None, "100": None, "500": None}
    assert ra.road_depths(premise("node-1", lon, lat, none, none, round(SQUARE_M)), VIEW, old_set, new_set) == {
        "10": None, "20": None, "50": None}


# ---------- the whole area

def run(tmp_path, premises, old_folder, new_folder):
    area = write_area(tmp_path / "area", premises, ra.load_old(old_folder))
    out = tmp_path / "out"
    code = ra.main(["--area", "test", "--from", str(area), "--old-rasters", str(old_folder), "--rasters",
                    str(new_folder), "--out", str(out)])
    return code, out


def test_main_rewrites_every_depth_and_keeps_everything_else(tmp_path, sets, capsys):
    _, new_set, old, new = sets
    lon, lat = centre(2, 3)
    rows = [premise("node-1", lon, lat, old_depth(2, 3), old_depth(2, 4), round(SQUARE_M)),
            premise("node-2", *centre(5, 1), old_depth(5, 1), old_depth(5, 1), 3)]
    code, out = run(tmp_path, rows, old, new)
    assert code == 0
    premises = json.loads((out / "premises.json").read_text(encoding="utf-8"))
    town = json.loads((out / "town.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in premises] == ["node-1", "node-2"]
    assert premises[0]["depth_m"] == {"10": 2.13, "20": 2.33, "50": 2.53}
    assert premises[0]["road"] == {**rows[0]["road"], "depth_m": {"10": 2.14, "20": 2.34, "50": 2.54}}
    assert premises[1]["depth_m"] == premises[1]["road"]["depth_m"] == {"10": 5.11, "20": 5.31, "50": 5.51}
    assert {k: v for k, v in premises[0].items() if k not in ("depth_m", "road")} == {
        k: v for k, v in rows[0].items() if k not in ("depth_m", "road")}
    assert town == {"view": VIEW, "cell_deg": 0.25, "return_periods": [10, 20, 50], "cells": new_set.view_cells(VIEW),
                    "shelters": [{"name": "Hall", "lat": 9.0, "lon": 100.5}]}
    assert "2 premises" in capsys.readouterr().out


def test_main_refuses_old_files_that_are_not_the_ones_the_area_was_built_from(tmp_path, sets):
    _, _, old, new = sets
    lon, lat = centre(2, 3)
    wrong = {**old_depth(2, 3), "100": 9.99}
    area = write_area(tmp_path / "area", [premise("node-1", lon, lat, wrong, old_depth(2, 3))], ra.load_old(old))
    with pytest.raises(ra.ResampleError, match="node-1.*old"):
        ra.main(["--area", "test", "--from", str(area), "--old-rasters", str(old), "--rasters", str(new),
                 "--out", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


def test_main_refuses_a_town_the_old_files_do_not_rebuild(tmp_path, sets):
    _, _, old, new = sets
    area = write_area(tmp_path / "area", [premise("node-1", *centre(2, 3), old_depth(2, 3), old_depth(2, 3))],
                      ra.load_old(old))
    town = json.loads((area / "town.json").read_text(encoding="utf-8"))
    (area / "town.json").write_text(json.dumps({**town, "cells": town["cells"][1:]}), encoding="utf-8")
    with pytest.raises(ra.ResampleError, match="town.json"):
        ra.main(["--area", "test", "--from", str(area), "--old-rasters", str(old), "--rasters", str(new),
                 "--out", str(tmp_path / "out")])


def test_main_refuses_an_area_already_on_the_new_sizes(tmp_path, sets):
    _, _, old, new = sets
    area = write_area(tmp_path / "area", [premise("node-1", *centre(2, 3), old_depth(2, 3), old_depth(2, 3))],
                      ra.load_old(old))
    town = json.loads((area / "town.json").read_text(encoding="utf-8"))
    (area / "town.json").write_text(json.dumps({**town, "return_periods": [10, 20, 50]}), encoding="utf-8")
    with pytest.raises(ra.ResampleError, match="already"):
        ra.main(["--area", "test", "--from", str(area), "--old-rasters", str(old), "--rasters", str(new),
                 "--out", str(tmp_path / "out")])


# ---------- Kota Tinggi, as shipped

def test_kota_tinggi_was_resampled_from_the_old_files_by_this_tool():
    """The shipped files, checked against the JRC files again: each business and square at 1 in 10, 20 and 50."""
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")
    area = areas.get("kota-tinggi")
    premises, town = areas.premises(area.id), areas.town(area.id)
    assert all(raster.depth_set().depths(p["lon"], p["lat"]) == p["depth_m"] for p in premises)
    assert town["cells"] == raster.depth_set().view_cells(area.view) and town["return_periods"] == [10, 20, 50]


def test_kota_tinggi_roads_match_a_fresh_resample_from_the_old_files(tmp_path):
    if not (OLD_JRC / "ID211_N10_E100_RP100_depth.tif").is_file() or not KOTA_TINGGI_OLD.is_dir():
        pytest.skip(f"the old files or the old Kota Tinggi build are not in {RAW}")
    if not raster.depth_set().grids:
        pytest.skip(f"no depth rasters in {raster.raster_dir()}")
    old = json.loads((KOTA_TINGGI_OLD / "premises.json").read_text(encoding="utf-8"))
    old_set = ra.load_old(OLD_JRC)
    shipped = {p["id"]: p for p in areas.premises("kota-tinggi")}
    for p in old:
        assert ra.road_depths(p, list(areas.get("kota-tinggi").view), old_set, raster.depth_set()) == \
            shipped[p["id"]]["road"]["depth_m"], p["id"]
