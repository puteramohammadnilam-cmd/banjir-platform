"""tools/fetch_area_osm.py: the city-wide Overpass fetch and its section-by-section fallback, on made-up answers and a
few elements recorded from the real one (tests/fixtures/city_osm). No network.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_fetch_area_osm.py
"""
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_area as ba  # noqa: E402
import fetch_area_osm as fao  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "city_osm"
STAMP = {"timestamp_osm_base": "2026-10-05T01:00:00Z"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the tests make no network request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(fao.time, "sleep", lambda seconds: None)


def section(osm_id, west):
    return {"id": f"s-{osm_id}", "osm_id": osm_id, "bbox": (west, 3.0, west + 0.01, 3.01)}


SECTIONS = [section(11, 101.50), section(12, 101.52)]


def element(kind, osm_id):
    return {"type": kind, "id": osm_id, "tags": {"shop": "kiosk"}}


# ---------- the questions

def test_the_business_question_asks_the_city_area_for_what_build_area_keeps():
    query = fao.pois_query(fao.CITY_RELATION)
    assert "area(3608347577)" in query and query.endswith("out center meta;")
    assert 'nwr["shop"](area.a)' in query and 'nwr["craft"](area.a)' in query
    for amenity in [*ba.EATERIES, "pharmacy"]:
        assert amenity in query
    assert "bank" not in query and "fuel" not in query


def test_the_road_question_asks_a_south_west_north_east_box_for_vehicle_roads():
    query = fao.roads_query((101.5, 3.0, 101.6, 3.1))
    assert "(3.000000,101.500000,3.100000,101.600000)" in query and query.endswith("out geom;")
    assert "residential" in query and "service" in query and "footway" not in query


def test_widen_grows_the_box_by_the_metres_asked_on_every_side():
    west, south, east, north = fao.widen((101.5, 3.0, 101.6, 3.1), 500)
    assert (3.0 - south) * ba.M_PER_DEG_LAT == pytest.approx(500)
    assert (north - 3.1) * ba.M_PER_DEG_LAT == pytest.approx(500)
    assert (101.5 - west) * ba.M_PER_DEG_LON_EQUATOR * math.cos(math.radians(3.05)) == pytest.approx(500)
    assert 101.5 - west == pytest.approx(east - 101.6)


# ---------- asking Overpass

class Reply:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return self.body


def test_overpass_gets_the_project_user_agent_with_nothing_personal(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(agent=request.get_header("User-agent"), url=request.full_url, body=request.data.decode())
        return Reply(b'{"elements": []}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fao.overpass_post(fao.pois_query(1)) == {"elements": []}
    assert seen["agent"].startswith("MyFlood/") and "(flood research)" in seen["agent"]
    assert "@" not in seen["agent"] and "http" not in seen["agent"]
    assert seen["url"] == fao.OVERPASS_URL and "area%28" in seen["body"]


def test_a_runtime_error_remark_is_a_timeout_and_a_clean_answer_is_not():
    with pytest.raises(fao.OverpassTimeout):
        fao.checked({"remark": "runtime error: Query timed out in \"query\" at line 1 after 301 seconds.", "elements": []})
    assert fao.checked({"elements": [1]}) == {"elements": [1]}


def test_merge_keeps_each_element_once_in_overpass_order_and_the_oldest_stamp():
    first = {"osm3s": {"timestamp_osm_base": "2026-10-05T02:00:00Z"}, "elements": [element("way", 5), element("node", 9)]}
    second = {"osm3s": {"timestamp_osm_base": "2026-10-05T01:00:00Z"},
              "elements": [element("node", 9), element("relation", 1), element("node", 2)]}
    merged = fao.merge([first, second])
    assert [(e["type"], e["id"]) for e in merged["elements"]] == [("node", 2), ("node", 9), ("way", 5), ("relation", 1)]
    assert merged["osm3s"]["timestamp_osm_base"] == "2026-10-05T01:00:00Z"
    assert "ODbL" in merged["osm3s"]["copyright"]


def fake_post(answers):
    """A post that answers each query from a dict, or raises what the dict holds; the asked queries are kept."""
    asked = []

    def post(query):
        asked.append(query)
        answer = answers[query]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return post, asked


@pytest.mark.parametrize("trouble", [
    {"remark": "runtime error: Query timed out", "elements": []},
    urllib.error.HTTPError(fao.OVERPASS_URL, 504, "Gateway Timeout", {}, None),
    TimeoutError("read timed out"),
    urllib.error.URLError(TimeoutError("connect timed out")),
])
def test_a_city_question_that_times_out_is_asked_section_by_section(trouble):
    whole = fao.pois_query(fao.CITY_RELATION)
    parts = [fao.pois_query(s["osm_id"]) for s in SECTIONS]
    post, asked = fake_post({whole: trouble, parts[0]: {"osm3s": STAMP, "elements": [element("node", 3), element("node", 1)]},
                             parts[1]: {"osm3s": STAMP, "elements": [element("node", 1), element("way", 2)]}})
    answer, how = fao.ask(post, whole, parts)
    assert how == "sections" and asked == [whole, *parts]
    assert [(e["type"], e["id"]) for e in answer["elements"]] == [("node", 1), ("node", 3), ("way", 2)]


def test_a_refusal_that_is_not_a_timeout_is_raised_not_hidden():
    whole = fao.pois_query(fao.CITY_RELATION)
    post, asked = fake_post({whole: urllib.error.HTTPError(fao.OVERPASS_URL, 406, "Not Acceptable", {}, None)})
    with pytest.raises(urllib.error.HTTPError):
        fao.ask(post, whole, ["never asked"])
    assert asked == [whole]


def test_a_section_that_times_out_too_stops_the_fetch():
    whole, part = fao.pois_query(fao.CITY_RELATION), fao.pois_query(11)
    post, _ = fake_post({whole: TimeoutError(), part: {"remark": "runtime error: out of memory", "elements": []}})
    with pytest.raises(fao.OverpassTimeout):
        fao.ask(post, whole, [part])


# ---------- the files

def test_fetch_writes_both_answers_and_sources_and_says_how_each_was_fetched(tmp_path):
    box = fao.widen(fao.union_box([s["bbox"] for s in SECTIONS]), fao.ROAD_MARGIN_M)
    road_parts = {fao.roads_query(fao.widen(s["bbox"], fao.ROAD_MARGIN_M)): {"osm3s": STAMP, "elements": [element("way", i)]}
                  for i, s in enumerate(SECTIONS, start=1)}
    post, _ = fake_post({fao.pois_query(fao.CITY_RELATION): {"osm3s": STAMP, "elements": [element("node", 7)]},
                         fao.roads_query(box): TimeoutError(), **road_parts})
    counts = fao.fetch(tmp_path, "2026-10-05", SECTIONS, post=post)
    assert counts == {"pois": 1, "roads": 2, "how": {"pois": "city", "roads": "sections"}}
    assert json.loads((tmp_path / "pois.json").read_text(encoding="utf-8"))["elements"] == [element("node", 7)]
    assert len(json.loads((tmp_path / "roads.json").read_text(encoding="utf-8"))["elements"]) == 2
    sources = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    assert "ODbL" in sources and "2026-10-05" in sources and "section by section" in sources
    assert fao.USER_AGENT in sources and "area(3608347577)" in sources


# ---------- the recorded elements read as build_area reads a fetch

def test_recorded_city_elements_load_as_businesses_and_roads():
    rows = ba.load_businesses(FIXTURES / "pois_sample.json")
    assert rows and {r["id"].split("-")[0] for r in rows} >= {"node", "way"}
    assert all(101.4 < r["lon"] < 101.6 and 2.9 < r["lat"] < 3.3 and len(r["edited"]) == 10 for r in rows)
    roads = ba.load_roads(FIXTURES / "roads_sample.json", ba.Projection.for_view((101.43, 2.95, 101.59, 3.23)))
    assert roads and all(r["kind"] in ba.VEHICLE_ROADS and len(r["pts"]) >= 2 for r in roads)
