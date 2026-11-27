"""tools/fetch_state_districts.py: a state's districts from made-up Overpass answers, no network.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_fetch_state_districts.py
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import fetch_state_districts as fsd  # noqa: E402
import sections_io  # noqa: E402


def way(*points):
    return {"type": "way", "role": "outer", "geometry": [{"lon": x, "lat": y} for x, y in points]}


def district(osm_id, name, west, town=True):
    """A 0.1 degree square district drawn as two ways that meet, with its main town in the middle."""
    e = west + 0.1
    members = [way((west, 1.0), (e, 1.0), (e, 1.1)), way((e, 1.1), (west, 1.1), (west, 1.0))]
    if town:
        members.append({"type": "node", "role": "admin_centre", "ref": 9, "lat": 1.05, "lon": west + 0.05})
    return {"type": "relation", "id": osm_id, "tags": {"name": name}, "members": members}


def answers(*districts):
    state = district(1, "State", 100.0, town=False)
    state["id"] = 1
    queue = iter([{"elements": list(districts)}, {"elements": [state]}])
    return lambda query: next(queue)


def test_districts_are_written_in_name_order_with_slugs_areas_and_main_towns(tmp_path):
    found = fsd.build(tmp_path, "2026-11-27", state_id=1, expected=2,
                      post=answers(district(20, "Kota Tinggi", 100.2), district(10, "Batu Pahat", 100.4, town=False)))
    props = [f["properties"] for f in found["districts"]]
    assert [p["id"] for p in props] == ["batu-pahat", "kota-tinggi"]
    assert props[0]["town"] is None and props[1]["town"] == [100.25, 1.05]
    assert props[1]["area_km2"] == pytest.approx(123.9, rel=0.01)
    loaded = sections_io.load_sections(tmp_path / "districts.geojson", expected=2)
    assert [s["id"] for s in loaded] == ["batu-pahat", "kota-tinggi"] and loaded[1]["town"] == [100.25, 1.05]
    assert (tmp_path / "raw_2026-11-27" / "districts.json").is_file()
    assert "ODbL" in (tmp_path / "SOURCES.md").read_text(encoding="utf-8")


def test_a_missing_district_or_an_open_ring_stops_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError, match="expected 2 districts"):
        fsd.build(tmp_path, "2026-11-27", state_id=1, expected=2, post=answers(district(20, "Kota Tinggi", 100.2)))
    broken = district(20, "Kota Tinggi", 100.2)
    broken["members"] = broken["members"][:1]
    with pytest.raises(ValueError, match="do not close"):
        fsd.build(tmp_path, "2026-11-27", state_id=1, expected=1, post=answers(broken))
    assert not any(tmp_path.iterdir())


def test_a_slug_is_lower_case_words_and_digits_joined_by_hyphens():
    assert fsd.slug("Johor Bahru") == "johor-bahru" and fsd.slug(" Kota  Tinggi ") == "kota-tinggi"


def test_a_main_town_outside_its_outline_is_refused(tmp_path):
    feature = fsd.feature_of(district(20, "Kota Tinggi", 100.2))
    feature["properties"]["town"] = [101.0, 1.05]
    path = tmp_path / "d.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    with pytest.raises(sections_io.SectionsError, match="town must be"):
        sections_io.load_sections(path)
