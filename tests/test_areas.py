"""Curated areas, and a backend that names no place (plan card A3).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_areas.py
"""
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google import genai

from app import ai, areas, floodtools, googlemaps, main, sections

ROOT = Path(__file__).resolve().parent.parent
CITY, KOTA_TINGGI = "shah-alam", "kota-tinggi"
ANETAS = "node-13414432501"   # the first business of the old Taman Sri Muda build, now in seksyen-25
PLACE_WORDS = ("Sri Muda", "Shah Alam", "Seksyen", "MBSA")   # must stay out of app/*.py
UNKNOWN_AREA = {"success": False, "data": None, "error": "Unknown area."}


@pytest.fixture
def client():
    main._hits.clear()
    return TestClient(main.app)


def place_words_in(text: str) -> list[str]:
    return [word for word in PLACE_WORDS if word.lower() in text.lower()]


def ids_in(area_id: str) -> set[str]:
    return {p["id"] for p in areas.premises(area_id)}


# ---------- the areas and their data

def test_every_area_loads_and_the_city_is_the_default():
    ids = [CITY, "kota-bharu", KOTA_TINGGI, "kuala-terengganu", "kuantan"]
    assert [a.id for a in areas.load_all()] == ids   # the default first, then by id
    assert areas.default().id == CITY and areas.default() == areas.get(CITY)
    assert areas.get("sri-muda") is None and sections.alias("sri-muda")[1]["id"] == "seksyen-25"
    assert areas.get("nope") is None
    areas.preload()   # both areas' built data fit their config


def test_business_ids_are_unique_across_areas():
    every = [p["id"] for a in areas.load_all() for p in areas.premises(a.id)]
    assert len(every) == len(set(every))


def test_every_premise_lies_inside_its_own_area():
    for area in areas.load_all():
        west, south, east, north = area.view
        assert list(area.view) == areas.town(area.id)["view"]   # the config agrees with the built data
        for p in areas.premises(area.id):
            assert west <= p["lon"] <= east and south <= p["lat"] <= north, p["id"]
            assert areas.area_at(p["lat"], p["lon"]) == area
            assert sections.listed_area_at(p["lat"], p["lon"])[0] == area, p["id"]
    assert areas.area_at(35.68, 139.69) is None   # Tokyo


def test_the_city_holds_the_2445_businesses_of_its_build():
    shown = areas.premises(CITY)
    wet = {rp: sum(1 for p in shown if p["depth_m"][rp]) for rp in ("10", "20", "50")}
    assert len(shown) == 2445 and wet == {"10": 522, "20": 551, "50": 571}
    assert (areas.default().zoom, areas.default().council) == (12, "Majlis Bandaraya Shah Alam (MBSA)")
    assert areas.business(ANETAS)[0]["section"] == "seksyen-25"


def test_kota_tinggi_is_the_earlier_hand_picked_build():
    area = areas.get(KOTA_TINGGI)
    assert areas.counts(area) == {"businesses": 27, "squares": 382, "shelters": 2}
    # re-sampled at 1 in 10, 20 and 50 by tools/resample_area.py (its OpenStreetMap inputs were not kept)
    assert {rp: sum(1 for p in areas.premises(KOTA_TINGGI) if p["depth_m"][rp]) for rp in ("10", "20", "50")} == {
        "10": 10, "20": 12, "50": 19}
    assert area.history is None and area.council is None
    assert set(area.notes) == {"businesses", "shelters"} and "Not an official list" in area.notes["shelters"]


def test_the_city_history_comes_from_its_history_file_for_the_city_and_each_section():
    city = areas.default()
    assert city.history is None   # not in area.json: in history.json (app/history.py)
    history = sections.history_for(city)
    floods = history["floods"]
    assert (history["first_year"], history["recent_from"], history["last_year"]) == (1992, 2019, 2026)
    assert len(floods) == 54 and [f["year"] for f in floods] == sorted(f["year"] for f in floods)
    assert all(f["when"] and f["what"] and f["source"] and f["url"].startswith("https://") for f in floods)
    section = sections.history_for(city, "seksyen-25")
    assert section["floods"] and all("seksyen-25" in f["sections"] for f in section["floods"])


def test_a_business_is_found_in_whichever_area_holds_it():
    kota_id = areas.premises(KOTA_TINGGI)[0]["id"]
    premise, area = areas.business(kota_id)
    assert premise["id"] == kota_id and area.id == KOTA_TINGGI
    assert areas.business("node-nope") is None and areas.business(["node-1"]) is None
    with pytest.raises(KeyError):
        areas.premises("nope")


def test_a_business_id_in_two_areas_is_refused(monkeypatch):
    twin = areas.premises(CITY)[0]
    monkeypatch.setattr(areas, "premises", lambda area_id: (twin,))   # every area now lists the same business
    areas._businesses.cache_clear()
    try:
        with pytest.raises(areas.AreaError, match="unique"):
            areas.business(twin["id"])
    finally:
        areas._businesses.cache_clear()   # rebuilt from the real files on the next lookup


def test_area_config_is_read_only_and_a_response_gets_its_own_copy():
    with pytest.raises(TypeError):
        areas.get(KOTA_TINGGI).notes["shelters"] = "An official list."
    sent = sections.details(areas.get("kuantan"))
    sent["history"]["floods"].clear()
    assert len(areas.get("kuantan").history["floods"]) == 5


# ---------- area.json is checked when it loads

GOOD = {"id": "test-town", "default": True, "name": "Test Town", "display_name": "Test Town, Somewhere",
        "view": [100.0, 2.0, 100.1, 2.1], "zoom": 15, "ai_name": "Test Town, Somewhere", "news_place": "Test Town",
        "news_region": "Test Town, Somewhere", "council": None, "notes": {}, "history": None}


def write_area(root: Path, folder: str, config) -> None:
    (root / folder).mkdir()
    (root / folder / "area.json").write_text(json.dumps(config))


HISTORY = {"first_year": 2000, "recent_from": 2010, "last_year": 2020,
           "floods": [{"when": "May 2005", "year": 2005.4, "what": "Shops flooded.", "source": "A newspaper"}]}


def test_a_well_formed_area_folder_loads_and_other_folders_are_skipped(tmp_path):
    write_area(tmp_path, "test-town", {**GOOD, "history": HISTORY})
    for parked in (".cache", "_parked"):
        (tmp_path / parked).mkdir()
    (tmp_path / "readme.txt").write_text("not an area")
    (area,) = areas.load_all(tmp_path)
    assert area.id == "test-town" and area.view == (100.0, 2.0, 100.1, 2.1)
    assert area.history["floods"] == tuple(HISTORY["floods"]) and area.history["last_year"] == 2020   # read-only copy
    assert area.centre() == pytest.approx((2.05, 100.05)) and area.contains(2.05, 100.05)


def history_with(**change) -> dict:
    flood = {**HISTORY["floods"][0], **change.pop("flood", {})}
    return {**HISTORY, "floods": [flood], **change}


@pytest.mark.parametrize("change, problem", [
    ({"id": "other-town"}, "folder"),
    ({"view": [100.1, 2.0, 100.0, 2.1]}, "view"),
    ({"view": [100.0, 2.0, 100.1]}, "view"),
    ({"view": [100.0, float("nan"), 100.1, 2.1]}, "view"),
    ({"view": [100.0, "2", 100.1, 2.1]}, "view"),
    ({"view": [181.0, 2.0, 182.0, 2.1]}, "view"),
    ({"view": [100.0, -91.0, 100.1, 2.1]}, "view"),
    ({"zoom": 15.5}, "zoom"),
    ({"zoom": True}, "zoom"),
    ({"zoom": 0}, "zoom"),
    ({"zoom": 20}, "zoom"),
    ({"name": " "}, "text"),
    ({"council": ""}, "council"),
    ({"notes": {"shelters": 3}}, "notes"),
    ({"history": {"floods": []}}, "history"),
    ({"history": history_with(recent_from=1990)}, "history"),
    ({"history": history_with(flood={"year": 1999.5})}, "history"),
    ({"history": history_with(flood={"year": "2005"})}, "history"),
    ({"history": history_with(flood={"source": ""})}, "history"),
    ({"history": history_with(flood={"account": "yes"})}, "history"),
    ({"history": [HISTORY]}, "history"),
    ({"colour": "blue"}, "unknown"),
    ({"default": False}, "default"),
    ({"default": "yes"}, "default"),
])
def test_a_malformed_area_is_rejected_with_the_reason(tmp_path, change, problem):
    write_area(tmp_path, "test-town", {**GOOD, **change})
    with pytest.raises(areas.AreaError, match=problem):
        areas.load_all(tmp_path)


@pytest.mark.parametrize("folder", ["Test-Town", "test_town", "a" * 41])
def test_an_area_id_must_be_a_short_lower_case_folder_name(tmp_path, folder):
    write_area(tmp_path, folder, {**GOOD, "id": folder})
    with pytest.raises(areas.AreaError, match="folder"):
        areas.load_all(tmp_path)


def test_built_data_must_fit_its_area(tmp_path):
    write_area(tmp_path, "test-town", GOOD)
    (area,) = areas.load_all(tmp_path)
    town = {"view": GOOD["view"], "cells": [], "shelters": []}
    inside = {"id": "node-1", "lat": 2.05, "lon": 100.05}
    areas.check_built(area, (inside,), town)
    for shown, built, problem in (
        ((inside,), {**town, "view": [100.0, 2.0, 100.2, 2.1]}, "same view"),
        ((inside,), {"view": GOOD["view"], "shelters": []}, "cells"),
        ((inside,), [], "same view"),
        (({**inside, "lat": 3.0},), town, "inside the view"),
        (({**inside, "lat": "2.05"},), town, "inside the view"),
        (({**inside, "id": 7},), town, "text id"),
        (("node-1",), town, "text id"),
    ):
        with pytest.raises(areas.AreaError, match=problem):
            areas.check_built(area, shown, built)


def test_a_missing_field_a_list_or_bad_json_is_rejected(tmp_path):
    write_area(tmp_path, "test-town", {k: v for k, v in GOOD.items() if k != "ai_name"})
    with pytest.raises(areas.AreaError, match="missing"):
        areas.load_all(tmp_path)
    for folder, text in (("listed", "[]"), ("broken", "{")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "area.json").write_text(text)
        with pytest.raises(areas.AreaError, match=folder):
            areas.load_all(tmp_path)
        (tmp_path / folder / "area.json").unlink()
        (tmp_path / folder).rmdir()


def test_a_folder_without_area_json_or_a_second_default_is_rejected(tmp_path):
    write_area(tmp_path, "test-town", GOOD)
    (tmp_path / "stray").mkdir()
    with pytest.raises(areas.AreaError, match="area.json"):
        areas.load_all(tmp_path)
    (tmp_path / "stray").rmdir()
    write_area(tmp_path, "other-town", {**GOOD, "id": "other-town"})
    with pytest.raises(areas.AreaError, match="default"):
        areas.load_all(tmp_path)


# ---------- the HTTP endpoints

def test_the_area_list_gives_each_area_with_its_counts(client):
    body = client.get("/api/areas").json()
    assert body["success"] is True and body["data"]["default"] == CITY
    listed = {area["id"]: area for area in body["data"]["areas"]}
    first = body["data"]["areas"][0]
    assert set(first) == {"id", "name", "display_name", "view", "zoom", "counts", "has_history", "has_shelters",
                          "has_sections", "aliases"}
    assert all((area["has_sections"], area["aliases"]) == (False, []) for area in body["data"]["areas"][1:])
    assert (first["has_sections"], [alias["id"] for alias in first["aliases"]]) == (True, ["sri-muda"])
    assert (first["id"], first["counts"], first["has_history"], first["has_shelters"]) == (
        CITY, {"businesses": 2445, "squares": 12477, "shelters": 6}, True, True)
    kota = listed[KOTA_TINGGI]
    assert (kota["counts"], kota["has_history"], kota["has_shelters"]) == (
        {"businesses": 27, "squares": 382, "shelters": 2}, False, True)
    assert len(listed) == 5 and all(listed[i]["has_history"] for i in ("kuantan", "kota-bharu", "kuala-terengganu"))


def test_area_data_carries_the_area_and_its_data(client):
    data = client.get(f"/api/areas/{KOTA_TINGGI}/data").json()["data"]
    assert set(data) == {"area", "premises", "town", "limits"}
    assert len(data["premises"]) == 27 and len(data["town"]["shelters"]) == 2
    assert data["area"]["id"] == KOTA_TINGGI and data["area"]["history"] is None
    assert data["area"]["notes"] == areas.get(KOTA_TINGGI).notes


def test_api_data_is_the_default_area_in_full_so_the_page_need_not_wait_for_the_list(client):
    # with no area in the link the page asks for /api/data at once, beside /api/areas: it must carry the area too
    old = client.get("/api/data").json()["data"]
    new = client.get(f"/api/areas/{CITY}/data").json()["data"]
    assert old == new and set(old) == {"area", "sections", "index", "premises", "town", "limits"}
    assert new["area"]["view"] == [101.4277, 2.9496, 101.5914, 3.2298] and new["area"]["zoom"] == 12
    assert len(new["area"]["history"]["floods"]) == 54 and len(new["sections"]) == 56 and len(new["index"]) == 2445


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/api/areas/nope/data", None),
    ("GET", "/api/rain?area=nope", None),
    ("POST", "/api/news", {"area_id": "nope"}),
    ("POST", "/api/ask", {"question": "hi", "area_id": "nope"}),
])
def test_an_unknown_area_is_a_404_in_the_envelope(client, monkeypatch, method, path, body):
    calls = []
    monkeypatch.setattr(ai, "ask", lambda *args: calls.append(args) or "x")
    monkeypatch.setattr(ai, "flood_news", lambda *args: calls.append(args) or {})
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda *args: calls.append(args) or {})
    response = client.request(method, path, json=body)
    assert response.status_code == 404 and response.json() == UNKNOWN_AREA and calls == []


def test_rain_is_asked_for_the_middle_of_the_chosen_area(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    seen = []
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: seen.append((lat, lon)) or {"total_mm": 0})
    assert client.get(f"/api/rain?area={KOTA_TINGGI}").status_code == 200
    assert client.get("/api/rain").status_code == 200
    assert seen == [areas.get(KOTA_TINGGI).centre(), areas.default().centre()]   # no area: the default's middle


def test_news_is_asked_about_the_chosen_area(client, monkeypatch):
    seen = []
    answer = {"answer": "x", "sources": [], "search_html": None}
    monkeypatch.setattr(ai, "flood_news", lambda area, section=None: seen.append(area.id) or answer)
    for body in ({"area_id": KOTA_TINGGI}, {}, None, {"question": "write me a poem"}):
        assert client.post("/api/news", json=body).status_code == 200
    assert seen == [KOTA_TINGGI, CITY, CITY, CITY]


def test_a_question_is_about_the_area_asked_for_or_the_selected_business(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "ask", lambda question, business_id, history, area, section=None: seen.append(area.id) or "ok")
    kota_id = areas.premises(KOTA_TINGGI)[0]["id"]
    bodies = ({"area_id": KOTA_TINGGI}, {"business_id": kota_id}, {}, {"area_id": KOTA_TINGGI, "business_id": kota_id})
    assert [client.post("/api/ask", json={"question": "hi", **b}).status_code for b in bodies] == [200] * 4
    assert seen == [KOTA_TINGGI, KOTA_TINGGI, CITY, KOTA_TINGGI]
    elsewhere = client.post("/api/ask", json={"question": "hi", "area_id": CITY, "business_id": kota_id})
    assert elsewhere.status_code == 404 and elsewhere.json()["error"] == "Unknown business."


def test_kota_tinggi_businesses_work_in_the_business_endpoints(client, monkeypatch):
    kota = areas.premises(KOTA_TINGGI)[0]
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(googlemaps, "place_status", lambda name, lat, lon: {"status": "open"})
    estimate = client.post("/api/estimate", json={"business_id": kota["id"], "value_at_risk_rm": 10_000})
    assert estimate.status_code == 200 and estimate.json()["data"]["business"] == kota["name"]
    assert client.get(f"/api/place/{kota['id']}").json()["data"]["place"] == {"status": "open"}


# ---------- prompts and tools filled from the area config

def recording_client(calls: list):
    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="Ok.", function_calls=None)
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_the_kota_tinggi_prompt_names_its_area_and_no_city_text(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "_client", lambda: recording_client(calls))
    ai.ask("Banjir tak?", None, [], areas.get(KOTA_TINGGI))
    ai.ask("Banjir tak?", None, [])
    kota, default = (call["config"].system_instruction for call in calls)
    assert areas.get(KOTA_TINGGI).ai_name in kota and not place_words_in(kota)
    assert f"the tool's page for small businesses around {areas.get(CITY).ai_name}." in default


def gemini_says(*parts: dict):
    body = {"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": "STOP"}]}
    return genai.types.HttpResponse(headers={}, body=json.dumps(body))


def test_a_kota_tinggi_question_gets_kota_tinggi_tool_results(monkeypatch):
    sent = []
    sdk = genai.Client(api_key="test-key")
    tools_first = gemini_says({"functionCall": {"name": "area_summary"}},
                              {"functionCall": {"name": "find_business", "args": {"name": "a"}}})
    monkeypatch.setattr(sdk._api_client, "request", lambda method, path, body, http_options=None:
                        sent.append(body) or (tools_first if len(sent) == 1 else gemini_says({"text": "Ok."})))
    monkeypatch.setattr(ai, "_client", lambda: sdk)
    area = areas.get(KOTA_TINGGI)

    assert ai.ask("Kedai mana kena banjir?", None, [], area) == "Ok."

    answers = {p["functionResponse"]["name"]: p["functionResponse"]["response"]["result"]
               for p in sent[1]["contents"][-1]["parts"]}
    summary = answers["area_summary"]
    assert summary["total_businesses"] == 27 and summary["area_notes"] == area.notes
    assert summary["shelters"] == [s["name"] for s in areas.town(KOTA_TINGGI)["shelters"]]
    assert answers["find_business"] and {b["id"] for b in answers["find_business"]} <= ids_in(KOTA_TINGGI)
    assert not place_words_in(json.dumps(sent))   # the prompt, the tool declarations and the tool results
    assert len(floodtools.premises()) == 2445     # the question's scope ended with the question


def test_the_news_question_uses_the_area_news_place(monkeypatch):
    seen = []

    class Models:
        def generate_content(self, model, contents, config):
            seen.append((contents, config.system_instruction))
            return SimpleNamespace(text="Nothing recent.", candidates=[])

    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(models=Models()))
    ai.flood_news(areas.get(KOTA_TINGGI))
    ai.flood_news()
    (kota_question, kota_system), (default_question, default_system) = seen
    assert areas.get(KOTA_TINGGI).news_place in kota_question and not place_words_in(kota_question + kota_system)
    assert default_question == ("What is the latest news on floods, river levels, rain warnings or flood works "
                                "around Shah Alam, Selangor?")
    assert "works around Shah Alam and the Klang Valley, Selangor, Malaysia, using Google Search" in default_system


def test_a_question_scope_holds_its_area_and_one_lookup_allowance_for_all_tools(monkeypatch):
    seen = []
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: seen.append((lat, lon)) or {"total_mm": 0})
    monkeypatch.setattr(googlemaps, "place_status", lambda name, lat, lon: None)
    kota = areas.get(KOTA_TINGGI)
    token = floodtools.start_question(kota)
    try:
        answers = [floodtools.rain_forecast(), floodtools.business_status(areas.premises(KOTA_TINGGI)[0]["id"]),
                   floodtools.rain_forecast(), floodtools.rain_forecast()]
        inside = floodtools.current_area()
    finally:
        floodtools.end_question(token)
    assert inside == kota and seen == [kota.centre(), kota.centre()]
    assert ["error" in a for a in answers] == [False, False, False, True]
    assert answers[-1]["error"] == floodtools.MAPS_SPENT
    assert floodtools.current_area() == areas.default() and "error" not in floodtools.rain_forecast()   # scope ended


def test_the_lookup_cap_holds_across_tool_calls_in_one_model_turn(monkeypatch):
    sent = []
    sdk = genai.Client(api_key="test-key")
    kota_id = areas.premises(KOTA_TINGGI)[0]["id"]
    four_calls = gemini_says(*[{"functionCall": {"name": "business_status", "args": {"business_id": kota_id}}}] * 4)
    monkeypatch.setattr(sdk._api_client, "request", lambda method, path, body, http_options=None:
                        sent.append(body) or (four_calls if len(sent) == 1 else gemini_says({"text": "Ok."})))
    monkeypatch.setattr(ai, "_client", lambda: sdk)
    monkeypatch.setattr(googlemaps, "place_status", lambda name, lat, lon: None)

    assert ai.ask("Kedai ni buka tak?", kota_id, [], areas.get(KOTA_TINGGI)) == "Ok."

    results = [p["functionResponse"]["response"]["result"] for p in sent[1]["contents"][-1]["parts"]]
    assert [r.get("error") for r in results] == [None, None, None, floodtools.MAPS_SPENT]


def test_the_no_shelter_message_takes_the_council_from_the_area():
    council = areas.default().council
    assert floodtools.no_shelters(areas.default()).endswith(f"JPS Public Infobanjir, the local council ({council}) or 999.")
    without_council = replace(areas.get(KOTA_TINGGI), council=None)
    assert floodtools.no_shelters(without_council).endswith("JPS Public Infobanjir, the local council or 999.")


def test_tool_docstrings_name_no_place():
    for tool in floodtools.TOOLS:
        assert not place_words_in(tool.__doc__ or ""), tool.__name__


def test_the_backend_python_names_no_place():
    names = {*PLACE_WORDS, *(a.name for a in areas.load_all()), *(a.council for a in areas.load_all() if a.council)}
    hits = [f"{path.name}: {name}" for path in sorted((ROOT / "app").glob("*.py"))
            for name in sorted(names) if name.lower() in path.read_text(encoding="utf-8").lower()]
    assert not hits, hits


# ---------- the towns added from the screen of 3 Oct 2026 (05_Raw_Data_Sources/town_screen_2026-10-03)

@pytest.mark.parametrize("area_id, businesses, wet, squares, floods", [
    ("kuantan", 300, {"10": 27, "20": 136, "50": 191}, 1085, 5),
    ("kota-bharu", 491, {"10": 85, "20": 93, "50": 100}, 618, 3),
    ("kuala-terengganu", 158, {"10": 29, "20": 46, "50": 85}, 588, 5),
])
def test_the_screened_towns_hold_what_was_built(area_id, businesses, wet, squares, floods):
    area = areas.get(area_id)
    found = areas.premises(area_id)
    assert len(found) == businesses and len(areas.town(area_id)["cells"]) == squares
    assert {rp: sum(1 for p in found if p["depth_m"][rp]) for rp in wet} == wet
    assert len(area.history["floods"]) == floods and area.council and areas.counts(area)["shelters"] == 0
    assert "not checked on the ground" in area.notes["businesses"]
    assert all(flood["source"] for flood in area.history["floods"])


@pytest.mark.parametrize("area_id, over_5_m", [("kota-bharu", 52), ("kuantan", 12), ("kuala-terengganu", 10)])
def test_the_depth_check_note_counts_what_the_data_holds(area_id, over_5_m):
    deep = sum(1 for p in areas.premises(area_id) if (p["depth_m"]["50"] or 0) > 5)
    note = areas.get(area_id).notes["depths"]
    assert deep == over_5_m and f"more than 5 m of water at {over_5_m} of these businesses in a 1 in 50 years flood" in note


# ---------- past losses to business premises (Reference tab)

LOSSES = {"places": ["State", "District"], "years": [{"year": 2021, "rm_thousand": [396400, 193600]},
                                                     {"year": 2023, "rm_thousand": [0, 0]}],
          "note": "A note.", "source": "Data source: a statistics office."}


def test_losses_load_and_reach_the_page(tmp_path):
    write_area(tmp_path, "test-town", {**GOOD, "losses": LOSSES})
    (area,) = areas.load_all(tmp_path)
    assert areas._thaw(area.losses) == LOSSES
    assert areas._thaw(areas.get(CITY).losses)["years"][0] == {"year": 2021, "rm_thousand": [396400, 193600, 82400]}


def test_the_city_sends_its_losses_with_the_area_data(client):
    losses = client.get(f"/api/areas/{CITY}/data").json()["data"]["area"]["losses"]
    assert losses["places"][0] == "Selangor" and [row["year"] for row in losses["years"]] == [2021, 2022, 2023, 2024, 2025]
    assert all(len(row["rm_thousand"]) == len(losses["places"]) for row in losses["years"])
    assert losses["source"].startswith("Data source: Department of Statistics Malaysia")
    section = client.get(f"/api/areas/{CITY}/sections/seksyen-25/data").json()["data"]["area"]
    assert section["losses"] == losses   # a section's page keeps its city's losses


@pytest.mark.parametrize("bad", [
    {**LOSSES, "years": [{"year": 2021, "rm_thousand": [1]}]},             # one number for two places
    {**LOSSES, "years": [{"year": 2021, "rm_thousand": [1, -1]}]},         # a negative loss
    {**LOSSES, "places": []},
    {**LOSSES, "note": ""},
    {key: value for key, value in LOSSES.items() if key != "source"},
    [],
    {**LOSSES, "years": []},                                              # a table with no rows
    {**LOSSES, "years": [LOSSES["years"][1], LOSSES["years"][0]]},          # newest first
    {**LOSSES, "years": [LOSSES["years"][0], LOSSES["years"][0]]},          # a year twice
    {**LOSSES, "places": ["State", "State"]},
])
def test_malformed_losses_are_rejected(tmp_path, bad):
    write_area(tmp_path, "test-town", {**GOOD, "losses": bad})
    with pytest.raises(areas.AreaError, match="losses must be"):
        areas.load_all(tmp_path)
