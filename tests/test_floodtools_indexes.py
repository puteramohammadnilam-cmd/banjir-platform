"""Flash flood potential in the AI tools (app/floodtools.py) and the prompts (app/ai.py), on the made-up city of
tests/sectioned_fixture.py and the small files of tests/index_fixture.py. Docstrings and names here name no real place.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_floodtools_indexes.py
"""
import json

import pytest

import index_fixture as ix
import tiff_fixture as fx
from app import ai, areas, floodtools, places, sections
from index_fixture import CITY_GRID, centre
from sectioned_fixture import CITY, PLAIN, city  # noqa: F401  (city is a fixture)

PLACE_WORDS = ("Sri Muda", "Shah Alam", "Seksyen", "MBSA", "Kuantan", "Kota Tinggi", "Kota Bharu", "Terengganu")
SHARES = {"zon-1": {"low": 0.7, "medium": 0.2, "high": 0.05, "extreme": 0.05},
          "zon-2": {"low": 0.2, "medium": 0.2, "high": 0.3, "extreme": 0.3},
          "zon-u3": {"low": 0.4, "medium": 0.1, "high": 0.4, "extreme": 0.1}}
SCORES = {"zon-1": 3.4, "zon-2": 2.1, "zon-u3": 4.2}


@pytest.fixture
def question(city):
    tokens = []

    def start(section_id=None, place=None, area_id=CITY):
        area = areas.get(area_id)
        found = places.resolve(place) if place else None
        tokens.append(floodtools.start_question(area, found, sections.get(area, section_id)))

    yield start
    for token in reversed(tokens):
        floodtools.end_question(token)


@pytest.fixture
def figures(city, tmp_path, monkeypatch):
    """The city's files and indexes.json, with a different share and score for each section."""
    where = ix.write_set(tmp_path / "indexes", CITY, CITY_GRID)
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(where))
    doc = ix.indexes_doc(list(SHARES))
    for sid, found in doc["sections"].items():
        found["flash"]["share"] = SHARES[sid]
        found["score"] = {"value": SCORES[sid], "class": "very_high" if SCORES[sid] > 3.5 else "moderate", "ratings": {}}
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    show_score(city, True)   # these tests are about the score as shown; the held-back case has its own test
    return where


def show_score(city, shown: bool):
    config_path = city / CITY / "area.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_path.write_text(json.dumps({**config, "show_index_score": shown}), encoding="utf-8")
    sections.clear_caches()


def test_the_score_is_held_back_until_the_area_says_to_show_it(question, figures, city):
    show_score(city, False)
    question("zon-2")
    found = floodtools.area_summary("zon-2")
    assert "flash_flood_potential" in found and "section_score" not in found
    question()
    whole = floodtools.area_summary()
    assert "area_score" not in whole and "highest_score" not in whole["flash_flood_by_section"]
    assert sections.index_method(CITY)["show_score"] is False


# ---------- flood_check

def test_flood_check_gives_a_business_its_flash_flood_potential(question, figures):
    question()
    found = floodtools.flood_check("node-990000003")
    assert found["flash_flood"] == {"score": 4.0, "class": "medium"}
    assert "flash floods are not in the river model" in found["limits"]


def test_flood_check_gives_null_where_no_file_covers_the_business(question, city, monkeypatch, tmp_path):
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(tmp_path / "missing"))
    question()
    assert floodtools.flood_check("node-990000003")["flash_flood"] is None


def test_the_selected_point_gets_its_figure_and_never_its_square(question, figures, tmp_path, monkeypatch):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(fx.write_depth_set(tmp_path / "rasters")))
    ix.write_set(figures, "test-area")   # the flood model fixture's grid, beside the city's
    point = places.point(*centre(14, 4))
    question(place=point["id"])
    found = floodtools.flood_check("selected")
    assert found["flash_flood"] == {"score": 3.0, "class": "low"} and found["place"] == floodtools.SELECTED_POINT
    lat, lon = places.parse_point_id(point["id"])
    assert str(lat) not in json.dumps(found) and str(lon) not in json.dumps(found)
    assert point["id"] not in json.dumps(found)


# ---------- area_summary

def test_a_section_summary_gives_its_shares_its_mean_and_its_score(question, figures):
    question()
    found = floodtools.area_summary("Zon 2")
    assert found["flash_flood_potential"] == {"average_score": 6.1, "share_of_section": SHARES["zon-2"]}
    assert found["section_score"] == {"value": 2.1, "class": "moderate", "meaning": floodtools.SCORE_MEANING}
    assert "flash floods are not in the river model" in found["limits"]


def test_the_city_summary_ranks_ten_sections_by_score_and_by_high_and_extreme_share(question, figures):
    question()
    found = floodtools.area_summary()["flash_flood_by_section"]
    assert [(s["section"], s["score"], s["class"]) for s in found["highest_score"]] == [
        ("Zon U3", 4.2, "very high"), ("Zon 1", 3.4, "moderate"), ("Zon 2", 2.1, "moderate")]
    assert [(s["section"], s["share_high_or_extreme"]) for s in found["most_high_or_extreme"]] == [
        ("Zon 2", 0.6), ("Zon U3", 0.5), ("Zon 1", 0.1)]
    assert found["meaning"] == floodtools.SCORE_MEANING


def test_the_city_summary_gives_the_citys_own_figures(question, figures):
    question()
    summary = floodtools.area_summary()
    assert summary["flash_flood_potential"] == {"average_score": 6.5, "share_of_area": ix.SHARE}
    assert summary["area_score"] == {"value": 2.5, "class": "moderate", "meaning": floodtools.SCORE_MEANING}
    assert "section_score" not in summary
    assert "share_of_area" not in floodtools.area_summary("Zon 2")["flash_flood_potential"]


def test_the_city_lists_stop_at_ten_sections(question, figures, monkeypatch):
    monkeypatch.setattr(floodtools, "MAX_TOP_SECTIONS", 2)
    question()
    found = floodtools.area_summary()["flash_flood_by_section"]
    assert [s["section"] for s in found["highest_score"]] == ["Zon U3", "Zon 1"]
    assert [s["section"] for s in found["most_high_or_extreme"]] == ["Zon 2", "Zon U3"]


def test_a_section_with_no_land_square_is_left_out_of_both_lists(question, figures, city):
    doc = ix.indexes_doc(list(SHARES))
    doc["sections"]["zon-1"].update(flash=None, score=None)
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    question()
    found = floodtools.area_summary()["flash_flood_by_section"]
    assert "Zon 1" not in json.dumps(found)
    assert not [key for key in floodtools.area_summary("Zon 1") if "flash" in key or "score" in key]


def test_a_section_with_no_score_is_left_out_of_the_score_list(question, figures, city):
    doc = ix.indexes_doc(list(SHARES))
    doc["sections"]["zon-1"]["score"] = None
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    question()
    found = floodtools.area_summary()["flash_flood_by_section"]
    assert [s["section"] for s in found["highest_score"]] == ["Zon U3", "Zon 2"]
    assert "section_score" not in floodtools.area_summary("Zon 1")


def test_an_area_without_the_files_has_no_flash_flood_keys(question, city):
    question()
    summary = floodtools.area_summary()
    assert not [key for key in [*summary, *floodtools.area_summary("Zon 1")] if "flash" in key or "score" in key]
    question(area_id=PLAIN)
    assert not [key for key in floodtools.area_summary() if "flash" in key]


# ---------- what the model is told

def test_the_tool_docstrings_name_no_place_and_say_what_the_figure_is():
    for tool in floodtools.TOOLS:
        doc = tool.__doc__ or ""
        assert not [word for word in PLACE_WORDS if word.lower() in doc.lower()], tool.__name__
    assert "flash flood potential" in floodtools.flood_check.__doc__
    assert "flash flood potential" in floodtools.area_summary.__doc__


def test_the_limits_say_it_is_susceptibility_not_a_depth_or_a_chance():
    limits = floodtools.LIMITS
    assert "Flash flood potential is susceptibility from slope, land cover, soil and vegetation" in limits
    assert "not a water depth or a chance of flooding" in limits
    assert "flash floods are not in the river model" in limits
    assert "1 in 50 years are not in the model" in limits   # the sentence before it is as it was


def test_the_chat_prompt_says_susceptibility_not_a_depth_and_not_in_the_river_model():
    prompt = " ".join(ai.SYSTEM.split())
    assert "susceptibility from slope, land cover, soil and vegetation" in prompt
    assert "not a water depth and not a chance of flooding" in prompt
    assert "flash floods are not in the river model" in prompt
    assert "never give it in metres" in prompt
    assert not [word for word in PLACE_WORDS if word.lower() in ai.SYSTEM.lower()]
