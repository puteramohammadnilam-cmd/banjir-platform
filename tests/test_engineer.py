"""Engineer mode (app/engineer.py, app/engineer_api.py): the rain pools layer and its tools, on the built Shah Alam
files in app/data/pooling. No network and no Google call.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_engineer.py
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app import engineer, main

SRI_MUDA = {"lat": 3.0300, "lon": 101.5367}


@pytest.fixture
def client():
    main._hits.clear()
    return TestClient(main.app)


def picture(data_url: str) -> bytes:
    assert data_url.startswith("data:image/png;base64,")
    return base64.b64decode(data_url.split(",", 1)[1])


def test_the_area_data_carries_the_layer_with_its_check_and_assumptions(client):
    found = client.get("/api/areas/shah-alam/data").json()["data"]["area"]["layers"]["rain_pools"]
    assert found["storms"] == [40, 70, 100] and found["url"].endswith("rain-pools-{mm}.png")
    assert {"auc", "p", "baseline_low_ground_auc", "hotspot_percentile"} <= set(found["check"])
    assert found["assumptions"]["drains_mm"] == 30 and "CC BY-NC-SA" in found["credit"]
    assert client.get("/api/areas/shah-alam/layers/rain-pools-70.png").status_code == 200
    assert client.get("/api/areas/shah-alam/layers/rain-pools-55.png").status_code == 404


def test_inspect_gives_every_value_at_a_spot(client):
    found = client.get("/api/eng/inspect", params=SRI_MUDA).json()["data"]
    assert set(found["river_depth_m"]) == {"10", "20", "50"} and isinstance(found["bare_ground_m"], float)
    assert set(found["pool_m"]) == {"40", "70", "100"} and "ground_m" in found["surface"]
    assert client.get("/api/eng/inspect", params={"lat": 95, "lon": 101}).status_code == 422


def test_a_profile_samples_every_30_m_up_to_5_km(client):
    found = client.get("/api/eng/profile", params={"a_lat": 3.03, "a_lon": 101.53, "b_lat": 3.04, "b_lon": 101.55}).json()
    points = found["data"]["points"]
    assert 2000 < found["data"]["length_m"] < 3000 and points[0]["d"] == 0 and points[-1]["d"] == found["data"]["length_m"]
    too_long = client.get("/api/eng/profile", params={"a_lat": 3.0, "a_lon": 101.45, "b_lat": 3.2, "b_lon": 101.58})
    assert too_long.status_code == 400 and "5 km" in too_long.json()["error"]


def test_basin_draws_the_land_draining_through_a_spot(client):
    found = client.get("/api/eng/basin", params=SRI_MUDA).json()["data"]
    assert found["squares"] >= 1 and found["area_km2"] > 0 and picture(found["png"]).startswith(b"\x89PNG")
    outside = client.get("/api/eng/basin", params={"lat": 4.5, "lon": 101.5})
    assert outside.status_code == 400


def test_a_bund_or_pond_is_worked_out_again_on_a_window(client):
    pond = client.post("/api/eng/whatif", json={"storm_mm": 100, "kind": "pond",
                                                 "points": [[3.030, 101.535], [3.032, 101.538], [3.031, 101.540]]})
    found = pond.json()["data"]
    assert pond.status_code == 200 and found["squares_changed"] > 0 and found["change_m"] == engineer.CHANGE_M
    assert {"wet_squares", "deepest_m", "water_m3"} <= set(found["before"]) and picture(found["png"])
    far = client.post("/api/eng/whatif", json={"storm_mm": 70, "kind": "bund", "points": [[3.0, 101.44], [3.2, 101.58]]})
    assert far.status_code == 400 and "km" in far.json()["error"]
    assert client.post("/api/eng/whatif", json={"storm_mm": 70, "kind": "wall", "points": [[3.03, 101.53]] * 2}).status_code == 422


def test_an_uploaded_grid_is_run_and_never_stored(client):
    rows = [[10] * 5, [10, 8, 8, 8, 10], [10, 8, 7, 8, 10], [10, 8, 8, 8, 10], [10] * 5]
    asc = "ncols 5\nnrows 5\nxllcorner 0\nyllcorner 0\ncellsize 10\nNODATA_value -9999\n" + "\n".join(
        " ".join(map(str, row)) for row in rows)
    found = client.post("/api/eng/upload", json={"asc": asc, "storm_mm": 200}).json()["data"]
    assert found["rows"] == 5 and found["wet_squares"] == 9 and found["cell_m"] == 10
    for bad, words in (("not a grid at all", "ncols"), ("ncols 2\nnrows 2\ncellsize 1\n1 2 3 4", "3 x 3"),
                       ("ncols 3\nnrows 3\ncellsize 1\n1 2 3", "holds 3")):
        answer = client.post("/api/eng/upload", json={"asc": bad, "storm_mm": 70})
        assert answer.status_code == 400 and words in answer.json()["error"], bad


def test_the_downloads_name_their_licence(client):
    csv = client.get("/api/eng/export.csv", params={"section": "seksyen-25"})
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    assert "standing_water_70mm_m (CC BY-NC-SA)" in csv.text.splitlines()[0] and len(csv.text.splitlines()) > 10
    tif = client.get("/api/eng/rain-pools-70.tif")
    assert tif.status_code == 200 and tif.content[:4] == b"II*\x00"


def test_model_runs_share_one_slot(monkeypatch):
    assert engineer.COMPUTE.acquire(blocking=False)
    monkeypatch.setattr(engineer, "COMPUTE_WAIT_S", 0.01)
    try:
        with pytest.raises(engineer.ToolError, match="busy"):
            engineer._run(lambda: None)
    finally:
        engineer.COMPUTE.release()


def test_basin_snaps_to_the_nearest_strong_flow_line_and_says_how_far(client):
    found = client.get("/api/eng/basin", params={"lat": 3.0239, "lon": 101.5409}).json()["data"]
    assert found["squares"] > 20 and 0 <= found["snapped_m"] <= 100


def test_bad_grids_get_a_reason_not_a_server_error(client):
    for bad, words in (("ncols\nnrows 3\ncellsize 1\n1 2 3", "has no value"),
                       ("ncols nan\nnrows 3\ncellsize 1\n1", "not a finite number"),
                       ("ncols 3.5\nnrows 3\ncellsize 1\n1", "whole numbers")):
        answer = client.post("/api/eng/upload", json={"asc": bad, "storm_mm": 70})
        assert answer.status_code == 400 and words in answer.json()["error"], bad


def test_fine_cells_are_metres_and_only_tiny_ones_degrees():
    grid = "\n".join(" ".join(["10"] * 5) for _ in range(5))
    assert engineer.upload(f"ncols 5\nnrows 5\ncellsize 0.5\n{grid}", 70)["cell_m"] == 0.5
    assert engineer.upload(f"ncols 5\nnrows 5\ncellsize 0.000277\n{grid}", 70)["cell_m"] > 25


def test_csv_cells_cannot_run_as_formulas_and_unknown_areas_never_reach_the_cache(client):
    assert engineer._cell_text("=HYPERLINK(1)") == "'=HYPERLINK(1)" and engineer._cell_text("Kedai Ali") == "Kedai Ali"
    assert engineer._cell_text(None) == ""
    assert client.get("/api/areas/nowhere/layers/rain-pools-70.png").status_code == 404


def test_bare_ground_is_fabdem_as_given_and_the_drains_are_kept_apart():
    found = engineer.pools("shah-alam")
    assert found.meta["burn_m"] == 1.0 and found.drains.grid.rows == found.ground.grid.rows
