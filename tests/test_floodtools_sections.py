"""The AI tools over an area split into sections (app/floodtools.py, app/ai.py), on the made-up city of
tests/sectioned_fixture.py beside one real area that is not split. Docstrings and names here name no real place.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_floodtools_sections.py
"""
import json

import pytest
from google import genai

from app import ai, areas, floodtools, googlemaps, places, sections
from sectioned_fixture import CITY, PLAIN, city, clear  # noqa: F401  (city is a fixture)


@pytest.fixture
def question(city):
    """Open a question's scope: question(section_id=None, place=None, area_id=CITY); closed after the test."""
    tokens = []

    def start(section_id=None, place=None, area_id=CITY):
        area = areas.get(area_id)
        found = places.resolve(place) if place else None
        tokens.append(floodtools.start_question(area, found, sections.get(area, section_id)))

    yield start
    for token in reversed(tokens):
        floodtools.end_question(token)


# ---------- find_business and flood_check

def test_find_business_searches_the_whole_city_and_names_each_section(question):
    question()
    found = floodtools.find_business("kedai")
    assert [(b["name"], b["section"]) for b in found] == [
        ("Kedai Satu", "Zon 1"), ("Kedai Tiga", "Zon 2"), ("Kedai Lima", "Zon 2")]


def test_find_business_puts_the_question_section_first(question):
    question("zon-2")
    assert [b["name"] for b in floodtools.find_business("kedai")] == ["Kedai Tiga", "Kedai Lima", "Kedai Satu"]
    assert [b["name"] for b in floodtools.find_business("kopi")] == ["Kopi Dua", "Kopi Enam"]


def test_find_business_in_a_plain_area_has_no_section_key(question):
    question(area_id=PLAIN)
    name = areas.premises(PLAIN)[0]["name"]
    assert floodtools.find_business(name) and all("section" not in b for b in floodtools.find_business(name))


def test_flood_check_names_the_section_of_a_business(question):
    question()
    assert floodtools.flood_check("node-990000004")["section"] == "Zon 2"


def test_a_selected_business_brings_its_own_section_to_the_question(question):
    question("zon-1", place="node-990000006")
    assert floodtools.current_section()["id"] == "zon-u3" and floodtools.current_area().id == CITY


# ---------- area_summary

def test_the_city_summary_counts_every_business_and_ranks_the_sections(question):
    question()
    summary = floodtools.area_summary()
    assert summary["total_businesses"] == 6 and summary["sections"] == 3
    assert {rp: s["businesses_with_water"] for rp, s in summary["scenarios"].items()} == {"10": 2, "20": 2, "50": 3}
    assert summary["scenarios"]["10"]["stay_dry"] == 4
    assert summary["scenarios"]["50"]["some_that_stay_dry"] == ["Kedai Satu", "Kedai Lima", "Kopi Enam"]
    ranked = summary["sections_with_most_businesses_with_water"]
    assert [s["section"] for s in ranked] == ["Zon 2", "Zon 1", "Zon U3"]
    assert ranked[0] == {"section": "Zon 2", "businesses": 3, "businesses_with_water": {"10": 1, "20": 1, "50": 2},
                         "squares": 3, "squares_with_water": {"10": 2, "20": 3, "50": 3}}
    assert summary["shelters"] == ["Dewan Satu", "Sekolah Dua"]


@pytest.mark.parametrize("asked", ["Zon 2", "2", "zone 2", "zon-2", "Old Town"])
def test_a_section_summary_counts_only_its_businesses_and_squares(question, asked):
    question()
    summary = floodtools.area_summary(asked)
    assert summary["total_businesses"] == 3 and summary["section"] == "Zon 2"
    assert (summary["squares"], summary["squares_with_water"]) == (3, {"10": 2, "20": 3, "50": 3})
    assert "sections_with_most_businesses_with_water" not in summary


def test_the_summary_names_at_most_fifteen_dry_businesses_and_counts_the_rest(question, monkeypatch):
    monkeypatch.setattr(floodtools, "MAX_DRY_NAMES", 2)
    question()
    dry = floodtools.area_summary()["scenarios"]["50"]
    assert (dry["stay_dry"], dry["some_that_stay_dry"]) == (3, ["Kedai Satu", "Kedai Lima"])
    assert floodtools.MAX_DRY_NAMES == 2 and floodtools.MAX_TOP_SECTIONS == 10


def test_an_unknown_section_or_a_section_of_a_plain_area_is_an_error_for_the_model(question):
    question()
    assert floodtools.area_summary("Zon 9") == {"error": floodtools.UNKNOWN_SECTION}
    assert floodtools.flood_history("Zon 9") == {"error": floodtools.UNKNOWN_SECTION}
    question(area_id=PLAIN)
    assert floodtools.area_summary("1") == {"error": floodtools.NO_SECTIONS}
    assert floodtools.area_summary("")["total_businesses"] == len(areas.premises(PLAIN))
    assert "sections_with_most_businesses_with_water" not in floodtools.area_summary()


# ---------- flood_history

def test_the_flood_history_lists_the_most_recent_first_with_the_count(question):
    question()
    found = floodtools.flood_history()
    assert (found["scope"], found["records"], found["years_checked"]) == ("Test City", 3, [1992, 2026])
    assert [f["when"] for f in found["most_recent"]] == ["11 Apr 2025", "18 to 19 Dec 2021", "26 Feb 2006"]
    assert found["most_recent"][1] == {"when": "18 to 19 Dec 2021", "what": "The big flood.", "depth": "over 1 m",
                                       "source": "A newspaper, 18 to 19 Dec 2021",
                                       "url": "https://example.org/tc-2021-12-18", "confidence": "high",
                                       "account": False, "sections": ["Zon 2", "Zon 1"]}
    assert [2007, 2020] in found["years_with_no_record"]
    assert "not proof" in found["note"] and "flash floods" in found["records_and_model"]


def test_the_flood_history_of_a_section_and_its_cap(question, monkeypatch):
    question()
    assert [f["when"] for f in floodtools.flood_history("U3")["most_recent"]] == ["26 Feb 2006"]
    monkeypatch.setattr(floodtools, "MAX_FLOODS", 1)
    capped = floodtools.flood_history("zon-2")
    assert (capped["scope"], capped["records"], len(capped["most_recent"])) == ("Zon 2", 2, 1)


def test_a_plain_area_gives_its_own_record_and_an_area_without_one_says_none_was_collected(question):
    question(area_id=PLAIN)
    found = floodtools.flood_history()
    assert found["records"] == len(areas.get(PLAIN).history["floods"]) and "years_with_no_record" not in found
    (areas.AREAS_DIR / CITY / "history.json").unlink()
    clear()
    question(area_id=CITY)
    nothing = floodtools.flood_history()
    assert nothing == {"error": floodtools.NO_HISTORY} and "not proof" in nothing["error"]


# ---------- the question itself

def test_rain_for_a_section_question_is_asked_for_the_middle_of_the_section(question, monkeypatch):
    seen = []
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: seen.append((lat, lon)) or {"total_mm": 1})
    question("zon-u3")
    assert floodtools.rain_forecast()["total_mm"] == 1
    assert seen == [pytest.approx((3.05, 101.515))]


def test_a_section_question_tells_the_model_its_section_and_declares_the_new_tool(city, monkeypatch):
    sent = []
    client = genai.Client(api_key="test-key")
    body = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
    monkeypatch.setattr(client._api_client, "request", lambda method, path, payload, http_options=None: sent.append(
        payload) or genai.types.HttpResponse(headers={}, body=json.dumps(body)))
    monkeypatch.setattr(ai, "_client", lambda: client)
    area = areas.get(CITY)
    assert ai.ask("banjir?", None, [], area, sections.get(area, "zon-2")) == "ok"
    system = json.dumps(sent[0]["systemInstruction"])
    assert 'This question is about the section \\"Zon 2\\"' in system and "flood_history" in system
    declared = {d["name"]: d for tool in sent[0]["tools"] for d in tool["functionDeclarations"]}
    assert "flood_history" in declared and declared["area_summary"]["parameters_json_schema"]["properties"]["section"]
    assert not declared["flood_history"]["parameters_json_schema"]["required"]
    ai.ask("banjir?", None, [], area)
    assert "This question is about the section" not in json.dumps(sent[-1]["systemInstruction"])


def test_a_selected_point_brings_its_section_and_the_model_gets_its_name_only(question):
    point = {"id": "pt:3.02998,101.53667", "is_point": True, "area_id": CITY, "depth_m": {"10": 1.0},
             "section": {"id": "zon-2", "name": "Zon 2"}, "shelter": None}
    token = floodtools.start_question(place=point)
    try:
        assert floodtools.current_section()["id"] == "zon-2"
        shown = floodtools._point_for_model(point)
        assert shown["section"] == "Zon 2" and "3.02998" not in json.dumps(shown)
    finally:
        floodtools.end_question(token)
