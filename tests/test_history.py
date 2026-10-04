"""app/history.py: the built flood history of an area split into sections (history.json), checked on load, and cut to
the whole area or one section for the page and the assistant.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_history.py
"""
import copy
import json
from datetime import date
from pathlib import Path

import pytest

from app import history

ROOT = Path(__file__).resolve().parent.parent
BUILT = ROOT / "app" / "data" / "areas" / "_shah-alam" / "history.json"

NAMES = {"sec-1": {"en": "Part 1", "ms": "Bahagian 1"}, "sec-2": {"en": "Part 2", "ms": "Bahagian 2"},
         "sec-3": {"en": "Part 3", "ms": "Bahagian 3"}}


def event(event_id, day, sections, **change):
    year = int(day[:4])
    return {"id": event_id, "date": day, "when": day, "year": year + 0.5, "place": "Somewhere", "sections": sections,
            "depth": None, "what": "A flood.", "confidence": "high", "account": False,
            "sources": [{"title": "A paper", "url": "https://example.org/a", "type": "news"}], **change}


DOC = {
    "first_year": 1992, "recent_from": 2019, "last_year": 2026, "checked": "2026-10-04", "section_names": NAMES,
    "events": [
        event("e-1995", "1995-12-24", ["sec-1"], depth="a little over 1 m"),
        event("e-2021", "2021-09-26", ["sec-1", "sec-2"], date_end="2021-09-27", confidence="medium",
              sources=[{"title": "One", "url": "https://example.org/1", "type": "official"},
                       {"title": "Two", "url": "https://example.org/2", "type": "dataset"}]),
        event("e-2024", "2024-06-26", []),
    ],
}


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "town").mkdir()
    (tmp_path / "town" / "history.json").write_text(json.dumps(DOC), encoding="utf-8")
    history.load.cache_clear()
    yield tmp_path
    history.load.cache_clear()


# ---------- scopes

def test_the_whole_area_gets_every_event_in_today_s_shape_plus_the_new_fields(folder):
    found = history.for_scope("town", None, folder=folder)
    assert (found["first_year"], found["recent_from"], found["last_year"], found["scope"]) == (1992, 2019, 2026, None)
    assert [f["id"] for f in found["floods"]] == ["e-1995", "e-2021", "e-2024"]
    flood = found["floods"][1]
    assert flood["when"] == "2021-09-26" and flood["what"] == "A flood." and flood["year"] == 2021.5
    assert flood["source"] == "One; Two" and flood["url"] == "https://example.org/1" and flood["source_type"] == "official"
    assert flood["confidence"] == "medium" and flood["sections"] == ["sec-1", "sec-2"] and flood["depth"] is None
    assert [s["type"] for s in flood["sources"]] == ["official", "dataset"]
    assert found["floods"][0]["depth"] == "a little over 1 m" and flood["account"] is False


def test_a_section_gets_only_the_events_that_name_it(folder):
    assert [f["id"] for f in history.for_scope("town", "sec-1", folder=folder)["floods"]] == ["e-1995", "e-2021"]
    assert [f["id"] for f in history.for_scope("town", "sec-2", folder=folder)["floods"]] == ["e-2021"]


def test_a_section_with_no_event_gets_an_empty_list_and_its_own_name_not_a_missing_record(folder):
    found = history.for_scope("town", "sec-3", folder=folder)
    assert found["floods"] == [] and found["scope"] == "sec-3"
    assert found["section_names"] == {"sec-3": NAMES["sec-3"]}
    assert (found["first_year"], found["last_year"]) == (1992, 2026)


def test_section_names_are_those_the_scope_uses(folder):
    assert set(history.for_scope("town", None, folder=folder)["section_names"]) == {"sec-1", "sec-2"}
    assert set(history.for_scope("town", "sec-2", folder=folder)["section_names"]) == {"sec-1", "sec-2"}


def test_an_unknown_section_is_refused(folder):
    with pytest.raises(history.HistoryError, match="Unknown section"):
        history.for_scope("town", "sec-9", folder=folder)


def test_an_area_without_a_history_file_has_none_and_a_bad_id_is_not_a_path(folder):
    assert history.for_scope("elsewhere", None, folder=folder) is None
    assert history.for_scope("../town", None, folder=folder) is None
    assert history.for_scope("", None, folder=folder) is None


def test_the_answer_is_a_copy_so_a_caller_cannot_change_the_cached_record(folder):
    first = history.for_scope("town", None, folder=folder)
    first["floods"][1]["sections"].append("sec-3")
    first["floods"][1]["sources"][0]["url"] = "https://changed.example"
    again = history.for_scope("town", None, folder=folder)
    assert again["floods"][1]["sections"] == ["sec-1", "sec-2"] and again["floods"][1]["url"] == "https://example.org/1"


def test_gaps_are_the_runs_of_years_with_no_record_in_scope(folder):
    assert history.for_scope("town", None, folder=folder)["gaps"] == [[1992, 1994], [1996, 2020], [2022, 2023], [2025, 2026]]
    assert history.for_scope("town", "sec-2", folder=folder)["gaps"] == [[1992, 2020], [2022, 2026]]
    assert history.for_scope("town", "sec-3", folder=folder)["gaps"] == [[1992, 2026]]


# ---------- the checks

def problems_after(change):
    doc = copy.deepcopy(DOC)
    change(doc)
    return history.problems(doc, today=date(2026, 10, 4))


def test_the_fixture_passes():
    assert history.problems(DOC, today=date(2026, 10, 4)) == []


@pytest.mark.parametrize("change, words", [
    (lambda d: d["events"][0].update(sources=[]), "at least one source"),
    (lambda d: d["events"][0]["sources"][0].update(url="http://example.org/a"), "https"),
    (lambda d: d["events"][0]["sources"][0].update(url="javascript:alert(1)"), "https"),
    (lambda d: d["events"][0]["sources"][0].update(url="https://"), "https"),
    (lambda d: d["events"][0]["sources"][0].update(url="https://example.org/a b"), "https"),
    (lambda d: d["events"][0]["sources"][0].update(type="blog"), "type"),
    (lambda d: d["events"][0].update(what="A <b>flood</b>."), "markup"),
    (lambda d: d["events"][0].update(place="javascript:void(0)"), "markup"),
    (lambda d: d["events"][0]["sources"][0].update(title="<script>"), "markup"),
    (lambda d: d["events"][1].update(id="e-1995"), "unique"),
    (lambda d: d["events"][1].update(id="E 1"), "id"),
    (lambda d: d["events"][0].update(date="1991-12-01", year=1991.9), "date"),
    (lambda d: d["events"][2].update(date="2026-10-05"), "date"),
    (lambda d: d["events"][0].update(date="1995-13"), "date"),
    (lambda d: d["events"][1].update(date_end="2021-09-25"), "date_end"),
    (lambda d: d["events"][0].update(sections=["sec-9"]), "section"),
    (lambda d: d["events"][0].update(sections=["sec-1", "sec-1"]), "section"),
    (lambda d: d["events"][0].update(confidence="certain"), "confidence"),
    (lambda d: d["events"][0].update(account="no"), "account"),
    (lambda d: d["events"][0].update(year=2001.5), "year"),
    (lambda d: d["events"][0].update(depth=""), "depth"),
    (lambda d: d["events"][0].update(point=[200, 3]), "point"),
    (lambda d: d.update(recent_from=1990), "years"),
    (lambda d: d["section_names"].update({"Bad Id": {"en": "x", "ms": "y"}}), "section_names"),
    (lambda d: d.update(events={}), "events"),
])
def test_a_bad_record_is_named(change, words):
    found = problems_after(change)
    assert found and any(words in problem for problem in found), found


def test_load_refuses_a_bad_file(folder):
    bad = copy.deepcopy(DOC)
    bad["events"][0]["sources"][0]["url"] = "http://plain.example"
    (folder / "town" / "history.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(history.HistoryError, match="https"):
        history.for_scope("town", None, folder=folder)


def test_a_point_inside_the_world_and_a_month_or_year_date_pass():
    def change(doc):
        doc["events"][0].update(point=[101.5, 3.0], date="1995-12", year=1995.96)
        doc["events"][2].update(date="2024", year=2024.5, undated=True, confidence="low")
    assert problems_after(change) == []


# ---------- the built file

@pytest.mark.skipif(not BUILT.exists(), reason="the built history is not in this checkout")
def test_the_built_file_passes_and_every_section_scope_works():
    doc = json.loads(BUILT.read_text(encoding="utf-8"))
    assert history.problems(doc) == []
    assert len(doc["section_names"]) == 56
    city = history.for_scope("_shah-alam", None)
    assert len(city["floods"]) == len(doc["events"]) and city["floods"]
    for section_id in doc["section_names"]:
        assert history.for_scope("_shah-alam", section_id)["scope"] == section_id
    assert history.for_scope("_shah-alam", "seksyen-25")["floods"]
    assert all(flood["url"].startswith("https://") for flood in city["floods"])
