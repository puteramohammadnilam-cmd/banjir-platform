"""tools/fetch_flood_points.py, on answers recorded from the service (tests/fixtures/arcgis_flood_points), no network.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_fetch_flood_points.py
"""
import copy
import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import fetch_flood_points as ffp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "arcgis_flood_points"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeService:
    """Answers every URL the tool asks for from the recorded files, and keeps the list of what was asked."""

    def __init__(self):
        self.asked: list[str] = []

    def __call__(self, url: str) -> dict:
        self.asked.append(url)
        for year in ffp.LAYERS:
            item_id = recorded(f"{year}_service.json")["serviceItemId"]
            if url.startswith(f"{ffp.ACCOUNT}/{year}/FeatureServer/0/query"):
                return recorded(f"{year}_page1.geojson")
            if url == f"{ffp.ACCOUNT}/{year}/FeatureServer/0?f=json":
                return recorded(f"{year}_layer.json")
            if url == f"{ffp.ACCOUNT}/{year}/FeatureServer?f=json":
                return recorded(f"{year}_service.json")
            if url == ffp.ITEM_URL.format(item_id=item_id):
                return recorded(f"{year}_item.json")
        raise AssertionError(f"unexpected request: {url}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the tests make no network request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(ffp.time, "sleep", lambda seconds: None)


def point(lon, lat, **properties):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


# ---------- asking the service

def test_a_layer_is_asked_for_by_service_layer_item_and_pages_of_a_thousand():
    service = FakeService()
    layer = ffp.fetch_layer("2021", service)
    assert layer["item"]["owner"] == "d1anameera"
    assert layer["service"]["serviceItemId"] == layer["item"]["id"]
    assert len(ffp.features_of(layer)) == 6
    page = service.asked[-1]
    assert "/2021/FeatureServer/0/query?" in page
    for part in ("where=1%3D1", "outFields=%2A", "f=geojson", "resultOffset=0", "resultRecordCount=1000"):
        assert part in page


def test_pages_are_followed_by_offset_until_the_service_stops_saying_it_exceeded_its_limit():
    pages = {0: {"features": [point(101.5, 3.0), point(101.5, 3.1)], "properties": {"exceededTransferLimit": True}},
             2: {"features": [point(101.5, 3.2)], "properties": {}}}
    asked = []

    def get_json(url):
        asked.append(url)
        return pages[int(url.split("resultOffset=")[1].split("&")[0])]

    result = ffp.fetch_pages("2021", get_json)
    assert [len(p["features"]) for p in result] == [2, 1]
    assert len(asked) == 2 and "resultOffset=2" in asked[1]


def test_an_empty_page_that_claims_more_does_not_loop_forever():
    answers = iter([{"features": [point(101.5, 3.0)], "properties": {"exceededTransferLimit": True}},
                    {"features": [], "properties": {"exceededTransferLimit": True}}])
    assert len(ffp.fetch_pages("2021", lambda url: next(answers))) == 2


def test_an_answer_with_no_features_is_an_error_not_an_empty_layer():
    with pytest.raises(RuntimeError, match="no features"):
        ffp.fetch_pages("2021", lambda url: {"error": {"code": 400, "message": "Invalid query"}})


def test_requests_carry_a_descriptive_user_agent_and_pause(monkeypatch):
    seen = {}
    slept = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            return b'{"features": []}'

    def fake_urlopen(request, timeout):
        seen["agent"] = request.get_header("User-agent")
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ffp.time, "sleep", slept.append)
    assert ffp.http_get_json("https://example.test/x") == {"features": []}
    assert "myflood-research" in seen["agent"] and "@" not in seen["agent"], "descriptive, with no personal address"
    assert slept == [ffp.PAUSE_SECONDS] and ffp.PAUSE_SECONDS >= 1.0


# ---------- the Shah Alam part

def test_the_box_takes_its_edges_and_leaves_out_rows_with_no_point():
    box = ffp.SHAH_ALAM_BOX
    assert ffp.in_box(point(box["west"], box["south"])) and ffp.in_box(point(box["east"], box["north"]))
    assert not ffp.in_box(point(box["east"] + 0.0001, 3.0))
    assert not ffp.in_box(point(101.5, box["south"] - 0.0001))
    assert not ffp.in_box({"type": "Feature", "geometry": None, "properties": {"KWSN_BANJIR": None}})
    assert not ffp.in_box({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[101.5, 3.0], [101.5, 3.1]]}})


def test_only_the_points_in_the_box_are_kept_each_naming_its_layer_and_the_originals_are_untouched():
    layers = [ffp.fetch_layer(name, FakeService()) for name in ffp.LAYERS]
    before = copy.deepcopy(layers)
    kept = ffp.filter_shah_alam(layers)
    assert layers == before, "nothing is changed in place"
    assert sorted(f["properties"]["KWSN_BANJIR"] for f in kept) == sorted([
        "Taman Melawis", "Kawasan Pantai Bharu, Jalan Meru", "Jalan Bukit Rimau",
        "Sekitar kawasan Persimpangan Bukit Botak", "Kampung Tengah, Puchong - Jalan Tempenis", "Jalan Cempaka 2, Kampung Paya\nJaras Hilir"])
    assert {f["properties"]["source_layer"] for f in kept} == {"2021", "2022"}
    assert all("source_layer" not in f["properties"] for layer in layers for f in ffp.features_of(layer))
    assert any(f["properties"]["Date"] is None for f in kept), "a row with no date is still a flood point"


# ---------- the files

def test_build_writes_the_raw_answers_the_shah_alam_points_and_sources(tmp_path):
    counts = ffp.build(tmp_path / "out", "2026-10-04", FakeService())
    assert counts == {"total": 12, "shah_alam": 6, "by_layer": {"2021": 6, "2022": 6}}
    out = tmp_path / "out"
    raw = sorted(p.name for p in (out / "raw_2026-10-04").iterdir())
    assert raw == [f"{y}_{part}" for y in ffp.LAYERS for part in ("item.json", "layer.json", "page1.geojson", "service.json")]
    assert json.loads((out / "raw_2026-10-04" / "2021_page1.geojson").read_text(encoding="utf-8")) == recorded("2021_page1.geojson")
    kept = json.loads((out / "shah_alam.geojson").read_text(encoding="utf-8"))
    assert kept["type"] == "FeatureCollection" and len(kept["features"]) == 6


def test_sources_credit_the_owner_state_the_missing_licence_and_count_what_was_kept(tmp_path):
    ffp.build(tmp_path, "2026-10-04", FakeService())
    text = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    for expected in ("d1anameera", "none stated", "approved by the user", "do not present them as an official record", "(1 with no point)",
                     "2021-05-05", "raw_2026-10-04", "2.95 to 3.23 N", "101.43 to 101.59 E"):
        assert expected in text, expected
    assert "(6 points;" in text


def test_main_takes_the_folder_and_the_date(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ffp, "http_get_json", FakeService())
    monkeypatch.setattr(ffp, "collect", lambda get_json=ffp.http_get_json: [ffp.fetch_layer(n, FakeService()) for n in ffp.LAYERS])
    assert ffp.main(["--out", str(tmp_path / "x"), "--date", "2026-01-02"]) == 0
    assert (tmp_path / "x" / "raw_2026-01-02").is_dir()
    assert "6 in the Shah Alam box" in capsys.readouterr().out
