"""Areas split into sections (app/sections.py) and the endpoints that serve them, on the made-up city of
tests/sectioned_fixture.py beside one real area that is not split. Docstrings and names here name no real place.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_sections_api.py
"""
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ai, areas, googlemaps, history, main, places, sections
from sectioned_fixture import CHECKLIST_POINT, CITY, PLAIN, city  # noqa: F401  (city is a fixture)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
REAL_DIR = next((folder for folder in (ROOT / "app" / "data" / "rasters",) if any(folder.glob("*_RP*_depth.tif"))),
                None)
UNKNOWN_SECTION = {"success": False, "data": None, "error": "Unknown section."}
UNKNOWN_AREA = {"success": False, "data": None, "error": "Unknown area."}
INDEX_KEYS = {"id", "name", "kind", "sector", "section", "road", "depth_m"}
SECTION_KEYS = {"id", "name", "bbox", "zoom", "outline", "area_km2", "counts"}
GAP = (3.045, 101.55)        # in the city's view, over 300 m from every section
NEAR_ZONE_2 = (3.0415, 101.55)   # about 170 m north of zone 2's outline


@pytest.fixture
def client(city, monkeypatch):
    main._hits.clear()
    return TestClient(main.app)


def city_area() -> areas.Area:
    return areas.get(CITY)


# ---------- the overlap rule, shared with the page

def test_the_squares_of_a_box_follow_the_page_overlap_rule_case_for_case():
    shared = json.loads((FIXTURES / "overlap_cases.json").read_text(encoding="utf-8"))
    size = shared["size"]
    for case in shared["cases"]:
        found = sections.overlaps_view(shared["view"], case["south"], case["west"], size["px"], size["py"])
        assert found is case["overlaps"], case["why"]
    assert sections.overlaps_view(None, 3.02, 101.53, size["px"], size["py"]) is False
    assert sections.overlaps_view(shared["view"], float("nan"), 101.53, size["px"], size["py"]) is False


# ---------- reading and finding sections

def test_the_sections_load_in_their_own_order_and_a_plain_area_has_none(city):
    assert [s["id"] for s in sections.listed(CITY)] == ["zon-1", "zon-2", "zon-u3"]
    assert sections.has_sections(city_area()) and not sections.has_sections(areas.get(PLAIN))
    assert sections.listed(PLAIN) == () and sections.get(areas.get(PLAIN), "zon-1") is None
    assert sections.ref(city_area(), "zon-2") == {"id": "zon-2", "name": "Zon 2"}
    assert sections.ref(city_area(), "nope") is None and sections.ref(None, "zon-2") is None


@pytest.mark.parametrize("text, found", [
    ("zon-2", "zon-2"), ("Zon 2", "zon-2"), ("2", "zon-2"), ("zone 2", "zon-2"), ("ZONE  U3", "zon-u3"),
    ("u 3", "zon-u3"), ("zon-u3", "zon-u3"), ("Old Town", "zon-2"), ("olde town", "zon-2"), ("old-town", "zon-2"),
    ("3", None), ("Zone", None), ("", None), ("   ", None), ("Zon 22", None), (None, None), (2, None),
])
def test_a_section_is_found_by_id_name_number_or_alias(city, text, found):
    section = sections.find_section(city_area(), text)
    assert (section["id"] if section else None) == found


def test_a_plain_area_or_no_area_finds_no_section(city):
    assert sections.find_section(areas.get(PLAIN), "1") is None and sections.find_section(None, "zon-1") is None


@pytest.mark.parametrize("point, found", [
    ((3.01, 101.51), "zon-1"), ((3.03, 101.55), "zon-2"), ((3.052, 101.542), "zon-2"), ((3.05, 101.51), "zon-u3"),
    ((3.02, 101.53), "zon-1"),            # on the edge two sections share: the first in the list
    (NEAR_ZONE_2, "zon-2"),               # in no outline, but near one
    (GAP, None), ((3.058, 101.558), None),
])
def test_a_point_takes_the_section_that_holds_it_or_the_nearest_within_300_m(city, point, found):
    section = sections.section_at(city_area(), *point)
    assert (section["id"] if section else None) == found


def test_a_point_in_a_split_area_but_in_no_section_is_in_no_area(city):
    area, section = sections.listed_area_at(*GAP)
    assert (area, section) == (None, None)
    area, section = sections.listed_area_at(3.03, 101.55)
    assert (area.id, section["id"]) == (CITY, "zon-2")
    plain = areas.premises(PLAIN)[0]
    area, section = sections.listed_area_at(plain["lat"], plain["lon"])
    assert (area.id, section) == (PLAIN, None)


def test_the_news_place_names_the_section_and_its_other_names(city):
    area = city_area()
    assert sections.news_place(area, None) == "Test City"
    assert sections.news_place(area, sections.get(area, "zon-2")) == "Zon 2 (Old Town, Olde Town), Test City"
    assert sections.news_place(area, sections.get(area, "zon-1")) == "Zon 1, Test City"


def test_a_business_place_carries_its_section(city):
    place = places.resolve("node-990000003")
    assert (place["area_id"], place["section"]) == (CITY, {"id": "zon-2", "name": "Zon 2"})
    assert places.resolve(areas.premises(PLAIN)[0]["id"])["section"] is None


# ---------- checks on the data

def test_every_business_alias_and_default_section_must_name_a_known_section(city):
    area, shown, built = city_area(), areas.premises(CITY), areas.town(CITY)
    known = areas.section_ids(CITY)
    areas.check_built(area, shown, built, known)
    stray = ({**shown[0], "section": "zon-9"}, *shown[1:])
    with pytest.raises(areas.AreaError, match="every business in premises.json needs a known section"):
        areas.check_built(area, stray, built, known)
    with pytest.raises(areas.AreaError, match="every alias and the default section"):
        areas.check_built(replace(area, default_section="zon-9"), shown, built, known)
    with pytest.raises(areas.AreaError, match="needs a section_word"):
        areas.check_built(replace(area, section_word=None), shown, built, known)
    with pytest.raises(areas.AreaError, match="need a sections.json"):
        areas.check_built(replace(area, aliases=()), shown, built, None)


@pytest.mark.parametrize("change, problem", [
    ({"aliases": [{"id": "Old Town", "section": "zon-2", "names": []}]}, "aliases must be"),
    ({"aliases": [{"id": "old-town", "section": "zon-2"}]}, "aliases must be"),
    ({"section_word": {"en": "Zone"}}, "section_word must be"),
    ({"section_word": "Zone"}, "section_word must be"),
    ({"default_section": "Zon 2"}, "default_section must be"),
])
def test_malformed_section_fields_in_area_json_are_rejected(city, change, problem):
    path = areas.AREAS_DIR / CITY / "area.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), **change}), encoding="utf-8")
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=problem):
        areas.load_all()


@pytest.mark.parametrize("change, problem", [
    (lambda doc: {**doc, "sections": []}, "no sections"),
    (lambda doc: [*doc["sections"]], "must hold a list of sections"),
    (lambda doc: {**doc, "sections": [doc["sections"][0], doc["sections"][0]]}, "section ids repeat"),
    (lambda doc: {**doc, "sections": [{**doc["sections"][0], "bbox": [1, 2, 3]}]}, "bbox must be"),
    (lambda doc: {**doc, "sections": [{**doc["sections"][0], "outline": {"type": "Point"}}]}, "outline must be"),
    (lambda doc: {**doc, "sections": [{k: v for k, v in doc["sections"][0].items() if k != "counts"}]}, "needs id"),
])
def test_a_malformed_sections_file_stops_the_server(city, change, problem):
    path = areas.AREAS_DIR / CITY / "sections.json"
    path.write_text(json.dumps(change(json.loads(path.read_text()))), encoding="utf-8")
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=problem):
        sections.preload()


def test_an_alias_may_not_be_an_area_id(city):
    path = areas.AREAS_DIR / CITY / "area.json"
    config = json.loads(path.read_text())
    path.write_text(json.dumps({**config, "aliases": [{"id": PLAIN, "section": "zon-1", "names": []}]}))
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=f"also an area id: {PLAIN}"):
        sections.preload()


def _rewrite_history(change) -> None:
    path = areas.AREAS_DIR / CITY / "history.json"
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
    sections.clear_caches()
    history.load.cache_clear()


def _without_section(doc: dict, section_id: str) -> dict:
    """The history with no word of one section: its name gone, and the events placed in it."""
    return {**doc, "section_names": {key: value for key, value in doc["section_names"].items() if key != section_id},
            "events": [event for event in doc["events"] if section_id not in event["sections"]]}


@pytest.mark.parametrize("change, problem", [
    (lambda text: text[:-2], "history.json: not JSON"),
    (lambda text: json.dumps({**json.loads(text), "events": "none"}), "events must be a list"),
    (lambda text: json.dumps(_without_section(json.loads(text), "zon-u3")), "differ: zon-u3"),
    (lambda text: json.dumps({**json.loads(text), "section_names": {
        **json.loads(text)["section_names"], "zon-9": {"en": "Zone 9", "ms": "Zon 9"}}}), "differ: zon-9"),
])
def test_a_bad_history_file_stops_the_server_at_start_up(city, change, problem):
    """A history.json that is not sound, or whose section_names are not exactly the sections.json ids, would answer
    the section pages with a 500: it stops start-up instead."""
    sections.preload()   # the fixture's own is sound
    _rewrite_history(change)
    with pytest.raises(areas.AreaError, match=problem):
        sections.preload()


# ---------- GET /api/areas and the data

def test_the_area_list_says_which_areas_are_split_and_their_aliases(client):
    body = client.get("/api/areas").json()["data"]
    listed = {area["id"]: area for area in body["areas"]}
    assert body["default"] == CITY and list(listed) == [CITY, PLAIN]
    assert listed[CITY]["has_sections"] is True and listed[CITY]["has_history"] is True
    assert listed[CITY]["aliases"] == [{"id": "old-town", "section": "zon-2", "names": ["Old Town", "Olde Town"]}]
    assert (listed[PLAIN]["has_sections"], listed[PLAIN]["aliases"], listed[PLAIN]["has_history"]) == (False, [], True)


def test_the_city_data_holds_sections_and_a_lean_index_but_no_squares_or_premises(client):
    data = client.get("/api/data").json()["data"]
    assert data == client.get(f"/api/areas/{CITY}/data").json()["data"]
    assert set(data) == {"area", "sections", "index", "town", "premises", "limits"}
    assert data["premises"] == [] and data["town"]["cells"] == [] and len(data["town"]["shelters"]) == 2
    assert data["town"]["view"] == data["area"]["view"] == [101.5, 3.0, 101.56, 3.06]
    assert [set(s) for s in data["sections"]] == [SECTION_KEYS] * 3
    assert data["sections"][1]["outline"]["type"] == "MultiPolygon"
    assert len(data["index"]) == 6 and all(set(row) == INDEX_KEYS for row in data["index"])
    assert data["index"][2] == {"id": "node-990000003", "name": "Kedai Tiga", "kind": "convenience", "sector": "shop",
                                "section": "zon-2", "road": {"name": "Jalan Satu"},
                                "depth_m": {"10": 1.35, "20": 1.54, "50": 1.76}}
    area = data["area"]
    assert (area["section_word"], area["default_section"]) == ({"en": "Zone", "ms": "Zon"}, None)
    assert len(area["history"]["floods"]) == 3 and area["history"]["scope"] is None


def test_a_section_holds_its_businesses_the_squares_of_its_box_and_every_shelter(client):
    data = client.get(f"/api/areas/{CITY}/sections/zon-2/data").json()["data"]
    assert set(data) == {"area", "section", "sections", "town", "premises", "limits"}
    assert set(data["section"]) == SECTION_KEYS and data["section"]["id"] == "zon-2"
    assert data["sections"] == [{"id": "zon-1", "name": "Zon 1"}, {"id": "zon-2", "name": "Zon 2"},
                                {"id": "zon-u3", "name": "Zon U3"}]
    built = areas.town(CITY)
    assert data["town"]["view"] == data["section"]["bbox"] == [101.53, 3.0, 101.56, 3.055]
    assert data["town"]["cells"] == built["cells"][1:4]   # across the edge, and the two inside
    assert data["town"]["shelters"] == built["shelters"] and data["town"]["cell_deg"] == built["cell_deg"]
    assert [p["id"] for p in data["premises"]] == ["node-990000003", "node-990000004", "node-990000005"]
    assert all(p["section"] == "zon-2" and "elevation" in p for p in data["premises"])
    assert [f["when"] for f in data["area"]["history"]["floods"]] == ["18 to 19 Dec 2021", "11 Apr 2025"]
    assert data["area"]["history"]["scope"] == "zon-2" and data["area"]["section_word"] == {"en": "Zone", "ms": "Zon"}
    zone_1 = client.get(f"/api/areas/{CITY}/sections/zon-1/data").json()["data"]
    assert zone_1["town"]["cells"] == built["cells"][0:2] and len(zone_1["premises"]) == 2


def test_a_section_answers_head_as_get(client):
    response = client.head(f"/api/areas/{CITY}/sections/zon-1/data")
    assert response.status_code == 200 and response.content == b""


@pytest.mark.parametrize("path, expected", [
    (f"/api/areas/{CITY}/sections/zon-9/data", UNKNOWN_SECTION),
    (f"/api/areas/{CITY}/sections/Zon%202/data", UNKNOWN_SECTION),   # ids only in a path, not names
    (f"/api/areas/{PLAIN}/sections/zon-1/data", UNKNOWN_SECTION),
    ("/api/areas/nope/sections/zon-1/data", UNKNOWN_AREA),
    ("/api/rain?section=zon-9", UNKNOWN_SECTION),
])
def test_an_unknown_section_is_a_404_in_the_envelope(client, path, expected):
    response = client.get(path)
    assert response.status_code == 404 and response.json() == expected


def test_an_alias_id_gets_its_section(client):
    data = client.get("/api/areas/old-town/data").json()["data"]
    assert data["section"]["id"] == "zon-2" and data["area"]["id"] == CITY


def test_a_plain_area_answers_as_before(client):
    data = client.get(f"/api/areas/{PLAIN}/data").json()["data"]
    assert set(data) == {"area", "premises", "town", "limits"} and len(data["premises"]) == len(areas.premises(PLAIN))
    assert "section_word" not in data["area"] and data["area"]["history"] == areas._thaw(areas.get(PLAIN).history)


# ---------- a point

@pytest.mark.skipif(REAL_DIR is None, reason="no JRC depth files on this machine")
def test_a_point_gets_its_section_and_a_point_in_no_section_gets_no_area(client, monkeypatch, caplog):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(REAL_DIR))
    caplog.set_level(logging.DEBUG)
    lat, lon = CHECKLIST_POINT
    answer = client.post("/api/point", json={"lat": lat, "lon": lon, "source": "pin"})
    place = answer.json()["data"]["place"]
    assert (place["id"], place["area_id"]) == ("pt:3.02998,101.53667", CITY)
    assert place["section"] == {"id": "zon-2", "name": "Zon 2"}
    assert place["depth_m"] == {"10": 1.35, "20": 1.54, "50": 1.76} and place["shelter"]["name"] == "Dewan Satu"
    assert answer.headers["cache-control"] == "no-store" and "location" not in answer.headers
    near = client.post("/api/point", json={"lat": NEAR_ZONE_2[0], "lon": NEAR_ZONE_2[1], "source": "gps"})
    assert near.json()["data"]["place"]["section"]["id"] == "zon-2"
    gap = client.post("/api/point", json={"lat": GAP[0], "lon": GAP[1], "source": "pin"}).json()["data"]["place"]
    assert (gap["area_id"], gap["section"], gap["shelter"]) == (None, None, None)
    assert "3.02" not in caplog.text and "101.5" not in caplog.text   # no point in any log line


# ---------- questions, rain and news with a section

@pytest.fixture
def asked(monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "ask", lambda question, place, history, area, section=None: seen.append(
        (place, area and area.id, section and section["id"])) or "ok")
    return seen


def test_a_question_takes_the_section_asked_for_or_the_selected_place(client, asked):
    bodies = [{"area_id": CITY, "section_id": "zon-1"}, {"section_id": "zon-u3"}, {"area_id": "old-town"},
              {"area_id": CITY, "section_id": "zon-1", "place": "node-990000004"}, {"area_id": CITY}, {}]
    assert [client.post("/api/ask", json={"question": "hi", **body}).status_code for body in bodies] == [200] * 6
    assert asked == [(None, CITY, "zon-1"), (None, CITY, "zon-u3"), (None, CITY, "zon-2"),
                     ("node-990000004", CITY, "zon-2"), (None, CITY, None), (None, CITY, None)]


@pytest.mark.parametrize("body", [{"section_id": "zon-9"}, {"area_id": PLAIN, "section_id": "zon-1"},
                                  {"section_id": "x" * 41}])
def test_a_question_about_an_unknown_section_is_refused(client, asked, body):
    response = client.post("/api/ask", json={"question": "hi", **body})
    assert response.status_code in (404, 422) and asked == []
    if response.status_code == 404:
        assert response.json() == UNKNOWN_SECTION


def test_rain_is_asked_for_the_middle_of_the_section(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    seen = []
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: seen.append((lat, lon)) or {"total_mm": 0})
    assert client.get(f"/api/rain?area={CITY}&section=zon-1").status_code == 200
    assert client.get(f"/api/rain?area={CITY}").status_code == 200
    assert seen == [pytest.approx((3.015, 101.515)), city_area().centre()]


def test_news_is_asked_about_the_section(client, monkeypatch):
    seen = []
    answer = {"answer": "x", "sources": [], "search_html": None}
    monkeypatch.setattr(ai, "flood_news", lambda area, section=None: seen.append(section and section["id"]) or answer)
    for body in ({"area_id": CITY, "section_id": "zon-2"}, {"area_id": CITY}, None):
        assert client.post("/api/news", json=body).status_code == 200
    assert seen == ["zon-2", None, None]
    assert client.post("/api/news", json={"section_id": "zon-9"}).json() == UNKNOWN_SECTION
