"""tools/build_history.py: curated events plus the public ArcGIS flood points -> app/data/areas/shah-alam/history.json.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_build_history.py
The rebuild test reads the raw files from ../05_Raw_Data_Sources, or BANJIR_RAW_DIR when that is set (a worktree), and
skips, saying why, when they are not on this machine.
"""
import copy
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_history as bh  # noqa: E402
from app import history  # noqa: E402

RAW = Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources") / "shah_alam"
BUILT = ROOT / "app" / "data" / "areas" / "shah-alam" / "history.json"
TODAY = date(2026, 10, 4)
BUILT_ON = date(2026, 10, 8)   # the shipped file: the JPS Selangor hotspot list was read on 8 Oct 2026


def square(label, west, south, east, north):
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"id": f"seksyen-{label.lower()}", "name": f"Seksyen {label}", "number_label": label,
            "geometry": {"type": "Polygon", "coordinates": [ring]}, "bbox": (west, south, east, north)}


# two sections side by side, 0.1 degree (about 11 km) square, meeting along lon 101.1
SECTIONS = [square("1", 101.0, 3.0, 101.1, 3.1), square("U2", 101.1, 3.0, 101.2, 3.1)]
ALIASES = {"old town": "seksyen-u2"}
DATASETS = {"2021": {"title": "A public 2021 layer by someone", "url": "https://example.org/2021"},
            "2022": {"title": "A public 2022 layer by someone", "url": "https://example.org/2022"}}


def point(lon, lat, day=None, place="A street", depth="0.1-0.3", layer="2021", district="KLANG"):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"Date": day, "KWSN_BANJIR": place, "KEDALAMAN": depth, "DAERAH": district, "source_layer": layer}}


def curated(event_id="sa-2021-05-18", day="2021-05-18", sections=("seksyen-1",), **change):
    return {"id": event_id, "date": day, "when": day, "place": "A street", "sections": list(sections), "depth": None,
            "what": "A flood.", "confidence": "high", "account": False,
            "sources": [{"title": "A paper", "url": "https://example.org/news", "type": "news"}], **change}


def curated_doc(*events):
    return {"checked": "2026-10-04", "first_year": 1992, "recent_from": 2019, "place_sections": ALIASES,
            "datasets": DATASETS, "events": list(events)}


def build(events=(), points=()):
    return bh.build(curated_doc(*events), {"type": "FeatureCollection", "features": list(points)}, SECTIONS, TODAY)


# ---------- where a point goes

def test_section_ids_and_names_come_from_the_label():
    assert bh.section_names(SECTIONS) == {"seksyen-1": {"en": "Seksyen 1", "ms": "Seksyen 1"},
                                          "seksyen-u2": {"en": "Seksyen U2", "ms": "Seksyen U2"}}


@pytest.mark.parametrize("lon, lat, expected", [
    (101.0512, 3.0533, ("section", "seksyen-1")),     # inside, given to 4 decimals
    (101.1512, 3.0533, ("section", "seksyen-u2")),
    (101.2010, 3.0533, ("section", "seksyen-u2")),    # about 110 m outside: the nearest section within 300 m
    (101.2100, 3.0533, ("outside", None)),            # about 1.1 km outside: dropped
    (101.05, 3.05, ("section", "seksyen-1")),         # given to 2 decimals, but the whole 0.01 square is in one section
    (101.10, 3.05, ("city", None)),                   # given to 2 decimals on the line between two: in the city, no section
])
def test_a_point_lands_in_the_section_that_holds_it(lon, lat, expected):
    assert bh.place_point(point(lon, lat), SECTIONS, ALIASES) == expected


def test_a_section_named_in_the_text_wins_over_the_point():
    assert bh.place_point(point(101.0512, 3.0533, place="Jalan 9, Seksyen U2"), SECTIONS, ALIASES) == ("section", "seksyen-u2")
    assert bh.place_point(point(101.0512, 3.0533, place="Kg. Baru, Sek. U2"), SECTIONS, ALIASES) == ("section", "seksyen-u2")
    assert bh.place_point(point(101.0512, 3.0533, place="Taman X Seksyen1"), SECTIONS, ALIASES) == ("section", "seksyen-1")


def test_a_known_place_name_wins_over_a_point_that_was_typed_in_the_wrong_place():
    assert bh.place_point(point(101.0512, 3.0533, place="Taman Old Town, Klang"), SECTIONS, ALIASES) == ("section", "seksyen-u2")


def test_a_section_number_the_area_does_not_have_is_ignored():
    assert bh.place_point(point(101.0512, 3.0533, place="Seksyen 99"), SECTIONS, ALIASES) == ("section", "seksyen-1")


def test_a_point_in_a_district_outside_the_city_is_dropped():
    assert bh.place_point(point(101.0512, 3.0533, district="HULU LANGAT"), SECTIONS, ALIASES) == ("district", None)
    assert bh.place_point(point(101.0512, 3.0533, district=None), SECTIONS, ALIASES) == ("section", "seksyen-1")
    assert bh.place_point(point(101.0512, 3.0533, district=" PETA LING"), SECTIONS, ALIASES) == ("section", "seksyen-1")


@pytest.mark.parametrize("text, expected", [
    ("0.1-0.3", (0.1, 0.3)), ("0.1 – 0.5", (0.1, 0.5)), ("0.1m – 0.3m", (0.1, 0.3)), ("0.30", (0.3, 0.3)),
    ("", None), (None, None), ("not stated", None),
])
def test_depth_ranges_are_read_as_typed(text, expected):
    assert bh.parse_depth(text) == expected


# ---------- groups of points

def test_points_on_one_day_in_one_section_become_one_event_with_the_depth_range():
    doc = build(points=[point(101.0512, 3.0533, "2021-05-18", "Jalan A", "0.1-0.3"),
                        point(101.0612, 3.0633, "2021-05-18", "Jalan B", "0.3 – 0.6"),
                        point(101.1512, 3.0533, "2021-05-18", "Jalan C")])
    events = {e["id"]: e for e in doc["events"]}
    assert set(events) == {"ds-2021-05-18-seksyen-1", "ds-2021-05-18-seksyen-u2"}
    one = events["ds-2021-05-18-seksyen-1"]
    assert one["what"] == "2 reports in a public 2021 dataset." and one["depth"] == "0.1 to 0.6 m in the reports"
    assert one["sections"] == ["seksyen-1"] and one["confidence"] == "medium" and one["when"] == "18 May 2021"
    assert one["place"] == "Jalan A; Jalan B" and one["sources"] == [{**DATASETS["2021"], "type": "dataset"}]
    assert events["ds-2021-05-18-seksyen-u2"]["what"] == "1 report in a public 2021 dataset."


def test_undated_points_group_by_the_layer_year_with_low_confidence():
    doc = build(points=[point(101.0512, 3.0533, None, layer="2022"), point(101.0612, 3.0533, None, layer="2022")])
    (event,) = doc["events"]
    assert event["id"] == "ds-2022-undated-seksyen-1" and event["date"] == "2022" and event["undated"] is True
    assert event["confidence"] == "low" and event["when"] == "2022, day not given" and "2 reports" in event["what"]


def test_a_point_in_the_city_but_no_one_section_makes_a_city_event_and_outside_points_are_counted():
    points = [point(101.10, 3.05, "2021-06-01"), point(101.5, 3.05, "2021-06-01"),
              point(101.0512, 3.0533, "2021-06-01", district="SEPANG")]
    (event,) = build(points=points)["events"]
    assert event["id"] == "ds-2021-06-01-city" and event["sections"] == []
    groups, drops = bh.group_points(points, SECTIONS, ALIASES)
    assert list(groups) == [("2021-06-01", "2021", None)] and drops == {"outside": 1, "district": 1}


def test_a_group_on_the_day_and_in_the_section_of_a_curated_event_becomes_its_second_source():
    doc = build([curated()], [point(101.0512, 3.0533, "2021-05-18")])
    (event,) = doc["events"]
    assert event["id"] == "sa-2021-05-18" and [s["type"] for s in event["sources"]] == ["news", "dataset"]


def test_a_curated_event_that_spans_days_takes_a_group_from_any_of_them():
    doc = build([curated(date_end="2021-05-20")], [point(101.0512, 3.0533, "2021-05-20")])
    assert [e["id"] for e in doc["events"]] == ["sa-2021-05-18"]


def test_a_group_in_another_section_stays_its_own_event():
    doc = build([curated()], [point(101.1512, 3.0533, "2021-05-18")])
    assert [e["id"] for e in doc["events"]] == ["ds-2021-05-18-seksyen-u2", "sa-2021-05-18"]


def test_events_come_out_oldest_first_with_a_year_inside_their_date():
    doc = build([curated("sa-2001", "2001", [], account=True, confidence="low"), curated("sa-1995-12", "1995-12", []),
                 curated("sa-2021-12-31", "2021-12-31", [])])
    assert [e["id"] for e in doc["events"]] == ["sa-1995-12", "sa-2001", "sa-2021-12-31"]
    assert [e["year"] for e in doc["events"]] == [1995.96, 2001.5, 2021.99]
    assert (doc["first_year"], doc["recent_from"], doc["last_year"], doc["checked"]) == (1992, 2019, 2026, "2026-10-04")


def test_the_input_is_not_changed():
    events, points = [curated()], [point(101.0512, 3.0533, "2021-05-18")]
    before = copy.deepcopy((events, points))
    build(events, points)
    assert (events, points) == before


# ---------- the checks run on every build

@pytest.mark.parametrize("change, words", [
    (lambda e: e.update(sources=[]), "at least one source"),
    (lambda e: e["sources"][0].update(url=""), "https"),
    (lambda e: e["sources"][0].update(url="javascript:alert(1)"), "https"),
    (lambda e: e["sources"][0].update(url="http://example.org/news"), "https"),
    (lambda e: e.update(what="<img src=x onerror=alert(1)>"), "markup"),
    (lambda e: e.update(sections=["seksyen-99"]), "section"),
    (lambda e: e.update(date="1990-01-01"), "date"),
    (lambda e: e.update(date="2027-01-01"), "date"),
])
def test_a_bad_curated_event_stops_the_build(change, words):
    bad = curated()
    change(bad)
    with pytest.raises(history.HistoryError, match=words):
        build([bad])


def test_two_events_with_one_id_stop_the_build():
    with pytest.raises(history.HistoryError, match="unique"):
        build([curated(), curated(day="2021-06-01")])


# ---------- the real files

def raw_inputs():
    paths = (RAW / "flood_history" / "events.json", RAW / "arcgis_flood_points" / "shah_alam.geojson",
             RAW / "mbsa_sections" / "sections.geojson")
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip("raw files not on this machine: " + ", ".join(missing))
    return paths


def test_a_fresh_build_from_the_raw_files_matches_the_shipped_file():
    events, _, sections = raw_inputs()   # the ArcGIS points are left out by default since 5 Oct 2026
    doc = bh.build_from_files(events, None, sections, today=BUILT_ON)
    assert bh.dumps(doc) == BUILT.read_text(encoding="utf-8")


def test_the_shipped_file_has_every_section_known_sources_and_the_named_floods():
    doc = json.loads(BUILT.read_text(encoding="utf-8"))
    assert history.problems(doc) == []
    by_id = {e["id"]: e for e in doc["events"]}
    assert by_id["sa-2006-02-26"]["date_note"] and "seksyen-25" in by_id["sa-2021-12-18"]["sections"]
    assert not any(e["id"].startswith(("sa-2007", "sa-2008")) for e in doc["events"])
    assert all(source["url"].startswith("https://") for e in doc["events"] for source in e["sources"])
    assert not any(e["id"].startswith("ds-") for e in doc["events"]), "no events from the ArcGIS layer"
    assert not any("d1anameera" in source["title"] for e in doc["events"] for source in e["sources"])
    jps = [e for e in doc["events"] if any("Laporan Banjir Tahunan" in source["title"] for source in e["sources"])]
    assert len(jps) == 22 and all(" p. " in source["title"] for e in jps for source in e["sources"] if "Laporan" in source["title"])
    assert by_id["jps-2022-12-02"]["date"] == "2022-12-02" and by_id["jps-2022-03-07"]["date"] == "2022-03-07", "the swapped dates, put right"


# ---------- the official hotspot list

def test_the_hotspot_list_is_copied_without_its_about_and_a_bad_one_stops_the_build():
    spots = {"about": "notes for us", "checked": "2026-10-04", "list_year": 2026,
             "source": {"title": "JPS Selangor hotspots", "url": "https://example.org/h", "type": "official"},
             "places": [{"name": "Kampung One", "sections": ["seksyen-1"]}]}
    doc = bh.build({**curated_doc(curated()), "hotspots": spots}, {"features": []}, SECTIONS, TODAY)
    assert doc["hotspots"] == {key: spots[key] for key in ("checked", "list_year", "source", "places")}
    assert "hotspots" not in build([curated()])
    for bad in (None, {**spots, "places": [{"name": "Kampung One", "sections": ["seksyen-9"]}]}):
        with pytest.raises(history.HistoryError, match="hotspot"):
            bh.build({**curated_doc(curated()), "hotspots": bad}, {"features": []}, SECTIONS, TODAY)
