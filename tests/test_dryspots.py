"""Where to move the car (app/dryspots.py, tools/build_dry_spots.py, POST /api/dry-spot).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_dryspots.py
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import dryspots, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_dry_spots  # noqa: E402

LAT, LON = 3.0, 101.5
M_LAT = 1 / 110574.0   # degrees of latitude in a metre


def write_spots(tmp_path, monkeypatch, spots, names=("Jalan Satu",)):
    folder = tmp_path / "test-town"
    folder.mkdir()
    (folder / "dry_spots.json").write_text(json.dumps({"credit": "c", "spacing_m": 40, "names": list(names), "spots": spots}))
    monkeypatch.setattr(dryspots, "AREAS_DIR", tmp_path)
    dryspots._load.cache_clear()


@pytest.fixture(autouse=True)
def fresh_cache():
    dryspots._load.cache_clear()
    yield
    dryspots._load.cache_clear()


def test_the_nearest_spot_is_picked_per_flood_size(tmp_path, monkeypatch):
    write_spots(tmp_path, monkeypatch, [
        [LAT + 100 * M_LAT, LON, 1, 0],    # 100 m north, dry only in a 1 in 10
        [LAT - 300 * M_LAT, LON, 3, -1],   # 300 m south, dry in all three, no name
    ])
    found = dryspots.nearest("test-town", LAT, LON)
    assert found["10"]["distance_m"] == 100 and found["10"]["road"] == "Jalan Satu" and found["10"]["bearing"] == 0
    assert found["20"] == found["50"] and found["50"]["distance_m"] == 300 and found["50"]["road"] is None
    assert found["50"]["bearing"] == 180 and found["credit"] == "c"


def test_spots_beyond_reach_are_not_offered(tmp_path, monkeypatch):
    write_spots(tmp_path, monkeypatch, [[LAT + 3100 * M_LAT, LON, 3, 0]])
    assert dryspots.nearest("test-town", LAT, LON) == {"10": None, "20": None, "50": None, "credit": "c"}


def test_an_area_without_spots_or_with_a_damaged_file_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(dryspots, "AREAS_DIR", tmp_path)
    assert dryspots.nearest("test-town", LAT, LON) is None
    assert dryspots.nearest(None, LAT, LON) is None
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "dry_spots.json").write_text("{not json")
    assert dryspots.nearest("broken", LAT, LON) is None


def test_the_build_walks_a_street_every_step_and_counts_dry_sizes():
    pts = list(build_dry_spots.walk([(0, 0), (100, 0)], 40))
    assert pts == [(0, 0), (40.0, 0.0), (80.0, 0.0), (100, 0)]
    across = list(build_dry_spots.walk([(0, 0), (30, 0), (30, 0), (30, 50)], 40))   # a corner and a zero-length piece
    assert across == [(0, 0), (30.0, 10.0), (30.0, 50.0), (30, 50)]
    assert build_dry_spots.dry_count({"10": None, "20": None, "50": 0.3}) == 2
    assert build_dry_spots.dry_count({"10": 0.1, "20": None, "50": None}) == 0
    assert build_dry_spots.dry_count(None) == 0


@pytest.mark.parametrize("tags, ok", [
    ({"highway": "residential", "name": "Jalan A"}, True),
    ({"highway": "service"}, True),
    ({"highway": "primary"}, False),
    ({"highway": "residential", "bridge": "yes"}, False),
    ({"highway": "residential", "tunnel": "building_passage"}, False),
    ({"highway": "residential", "access": "private"}, False),
    ({"highway": "service", "service": "parking_aisle"}, False),
    ({"highway": "service", "service": "driveway"}, False),
])
def test_only_public_streets_off_bridges_and_out_of_tunnels_are_walked(tags, ok):
    assert build_dry_spots.is_parkable(tags) is ok


def test_the_city_has_dry_spots_and_the_endpoint_answers_by_post_only():
    client = TestClient(main.app)
    main._hits.clear()
    res = client.post("/api/dry-spot", json={"place": "node-3970662969"})
    assert res.status_code == 200
    spots = res.json()["data"]["spots"]
    assert spots["50"]["distance_m"] <= dryspots.REACH_M and "OpenStreetMap" in spots["credit"]
    assert client.get("/api/dry-spot").status_code == 405
    assert client.post("/api/dry-spot", json={"place": "node-1"}).status_code == 404
