"""tools/sections_io.py: the 56 sections read from sections.geojson (a small made-up file always; the real one when the raw
folder is there, BANJIR_RAW_DIR or ../05_Raw_Data_Sources).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_sections_io.py
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from app import geo  # noqa: E402
import sections_io  # noqa: E402

RAW = Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources")
REAL = RAW / "shah_alam" / "mbsa_sections" / "sections.geojson"
needs_real = pytest.mark.skipif(not REAL.exists(), reason="the raw sections file is not here (set BANJIR_RAW_DIR)")
ORDER = [*(str(n) for n in range(1, 37)), *(f"U{n}" for n in range(1, 21))]


def feature(label, west=0.0, osm_id=1, name=None):
    ring = [[west, 0], [west + 0.1, 0], [west + 0.1, 0.1], [west, 0.1], [west, 0]]
    props = {"osm_id": osm_id, "name": name or f"Seksyen {label}", "section": label}
    return {"type": "Feature", "properties": props, "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}


def write(tmp_path, features):
    path = tmp_path / "sections.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return path


# ---------- the small fixture, always

def test_the_slug_is_the_word_and_the_label_in_lower_case():
    assert sections_io.slug("25") == "seksyen-25"
    assert sections_io.slug("U13") == "seksyen-u13"


def test_sections_come_out_in_natural_order_whatever_the_file_order(tmp_path):
    labels = ["U2", "10", "2", "U10", "1", "36", "U1"]
    path = write(tmp_path, [feature(label, west=i, osm_id=i) for i, label in enumerate(labels)])
    sections = sections_io.load_sections(path, expected=len(labels))
    assert [s["number_label"] for s in sections] == ["1", "2", "10", "36", "U1", "U2", "U10"]
    assert [s["id"] for s in sections] == ["seksyen-1", "seksyen-2", "seksyen-10", "seksyen-36", "seksyen-u1", "seksyen-u2", "seksyen-u10"]


def test_a_section_has_its_id_name_label_geometry_bbox_and_area(tmp_path):
    section = sections_io.load_sections(write(tmp_path, [feature("25", west=101.5)]), expected=1)[0]
    assert set(section) == {"id", "name", "number_label", "osm_id", "geometry", "bbox", "area_km2"}
    assert section["name"] == "Seksyen 25" and section["geometry"]["type"] == "MultiPolygon"
    assert section["bbox"] == (101.5, 0.0, 101.6, 0.1)
    assert section["area_km2"] == pytest.approx(geo.geometry_area_km2(section["geometry"]), abs=0.001)


def test_the_label_falls_back_to_the_name_when_the_section_property_is_missing(tmp_path):
    odd = feature("7")
    del odd["properties"]["section"]
    assert sections_io.load_sections(write(tmp_path, [odd]), expected=1)[0]["id"] == "seksyen-7"


def test_two_sections_with_the_same_label_are_refused(tmp_path):
    path = write(tmp_path, [feature("5", osm_id=1), feature("5", west=1, osm_id=2)])
    with pytest.raises(sections_io.SectionsError, match="seksyen-5"):
        sections_io.load_sections(path, expected=2)


def test_the_wrong_number_of_sections_is_refused(tmp_path):
    with pytest.raises(sections_io.SectionsError, match="56"):
        sections_io.load_sections(write(tmp_path, [feature("1"), feature("2", west=1)]))


@pytest.mark.parametrize("label", ["", "0", "37", "U0", "U21", "X5", "5a"])
def test_a_label_outside_1_to_36_and_u1_to_u20_is_refused(tmp_path, label):
    with pytest.raises(sections_io.SectionsError, match="label"):
        sections_io.load_sections(write(tmp_path, [feature(label, name="Seksyen odd")]), expected=1)


def test_a_feature_that_is_not_an_area_is_refused(tmp_path):
    point = feature("1")
    point["geometry"] = {"type": "Point", "coordinates": [101, 3]}
    with pytest.raises(sections_io.SectionsError, match="Polygon"):
        sections_io.load_sections(write(tmp_path, [point]), expected=1)


def test_a_missing_file_says_which_one(tmp_path):
    with pytest.raises(sections_io.SectionsError, match="nowhere.geojson"):
        sections_io.load_sections(tmp_path / "nowhere.geojson", expected=1)


def test_the_expected_ids_are_the_56_in_natural_order():
    ids = sections_io.expected_ids()
    assert len(ids) == 56 == len(set(ids))
    assert ids == [sections_io.slug(label) for label in ORDER]


# ---------- the real file

@needs_real
def test_the_real_file_gives_56_unique_ordered_sections():
    sections = sections_io.load_sections(REAL)
    ids = [s["id"] for s in sections]
    assert len(ids) == 56 == len(set(ids))
    assert ids == sections_io.expected_ids()
    assert [s["number_label"] for s in sections] == ORDER


@needs_real
def test_the_real_areas_add_to_about_302_square_kilometres_and_match_the_tool():
    sections = sections_io.load_sections(REAL)
    assert sum(s["area_km2"] for s in sections) == pytest.approx(302, rel=0.01)
    recorded = {f["properties"]["osm_id"]: f["properties"]["area_km2"] for f in json.loads(REAL.read_text(encoding="utf-8"))["features"]}
    for s in sections:
        assert s["area_km2"] == pytest.approx(recorded[s["osm_id"]], abs=0.002)


@needs_real
def test_the_real_taman_sri_muda_point_is_in_section_25():
    found = geo.containing(101.53667, 3.02998, sections_io.load_sections(REAL))
    assert found["id"] == "seksyen-25"


@needs_real
def test_the_real_bboxes_hold_their_own_outlines_and_sit_in_shah_alam():
    for s in sections_io.load_sections(REAL):
        west, south, east, north = s["bbox"]
        assert 101.3 < west < east < 101.7 and 2.9 < south < north < 3.25
        assert s["bbox"] == geo.bbox(s["geometry"])


# ---------- a named set (a state's districts): every feature carries its own id

def named(sid, name, west=0.0):
    ring = [[west, 0], [west + 0.1, 0], [west + 0.1, 0.1], [west, 0.1], [west, 0]]
    return {"type": "Feature", "properties": {"id": sid, "name": name, "osm_id": 7},
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def test_a_named_set_keeps_its_ids_names_and_file_order_and_any_count(tmp_path):
    path = write(tmp_path, [named("muar", "Muar", west=2), named("kota-tinggi", "Kota Tinggi"), named("batu-pahat", "Batu Pahat", west=1)])
    sections = sections_io.load_sections(path)
    assert [s["id"] for s in sections] == ["muar", "kota-tinggi", "batu-pahat"], "the file's order, not sorted"
    assert sections[1]["name"] == "Kota Tinggi" and sections[1]["number_label"] is None
    assert set(sections[0]) == {"id", "name", "number_label", "osm_id", "geometry", "bbox", "area_km2"}
    assert sections[0]["bbox"] == (2.0, 0.0, 2.1, 0.1)
    with pytest.raises(sections_io.SectionsError, match="Expected 2"):
        sections_io.load_sections(path, expected=2)


@pytest.mark.parametrize("sid", ["Kota Tinggi", "kota_tinggi", "-muar", "muar-", "kota--tinggi", "../x"])
def test_a_named_id_that_cannot_go_in_an_address_is_refused(tmp_path, sid):
    with pytest.raises(sections_io.SectionsError, match="lower case"):
        sections_io.load_sections(write(tmp_path, [named(sid, "X")]))


def test_a_named_set_needs_names_one_kind_of_feature_and_ids_once(tmp_path):
    with pytest.raises(sections_io.SectionsError, match="no name"):
        sections_io.load_sections(write(tmp_path, [named("muar", "  ")]))
    with pytest.raises(sections_io.SectionsError, match="one kind"):
        sections_io.load_sections(write(tmp_path, [named("muar", "Muar"), feature("1")]))
    with pytest.raises(sections_io.SectionsError, match="repeat"):
        sections_io.load_sections(write(tmp_path, [named("muar", "Muar"), named("muar", "Muar 2", west=1)]))
