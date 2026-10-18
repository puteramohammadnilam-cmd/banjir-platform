"""tools/fetch_mbsa_sections.py, on a recorded Overpass relation (tests/fixtures/mbsa_sections) and small made-up ones, no network.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_fetch_sections.py
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
import fetch_mbsa_sections as fms  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "mbsa_sections"
R = fms.EARTH_RADIUS_KM


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the tests make no network request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(fms.time, "sleep", lambda seconds: None)


def way(*points):
    return {"type": "way", "role": "outer", "geometry": [{"lon": lon, "lat": lat} for lon, lat in points]}


def box_ways(west=0.0, south=0.0, east=0.1, north=0.1, role="outer"):
    """The four sides of a box as four ways, each starting where the one before ends."""
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    return [{**way(corners[i], corners[i + 1]), "role": role} for i in range(4)]


def relation(osm_id, name, members, **tags):
    return {"type": "relation", "id": osm_id, "tags": {"name": name, "admin_level": "10", **tags}, "members": members}


def sphere_box_km2(west, south, east, north):
    return R * R * math.radians(east - west) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))


# ---------- rings

def test_ways_that_meet_end_to_end_become_one_closed_ring_whatever_their_order_and_direction():
    sides = [w["geometry"] for w in box_ways()]
    shuffled = [[(p["lon"], p["lat"]) for p in sides[2]][::-1], [(p["lon"], p["lat"]) for p in sides[0]],
                [(p["lon"], p["lat"]) for p in sides[3]], [(p["lon"], p["lat"]) for p in sides[1]][::-1]]
    rings, open_ways = fms.stitch_rings(shuffled)
    assert open_ways == 0 and len(rings) == 1
    assert rings[0][0] == rings[0][-1] and len(rings[0]) == 5


def test_ways_that_do_not_close_are_counted_not_drawn():
    rings, open_ways = fms.stitch_rings([[(0.0, 0.0), (0.1, 0.0), (0.1, 0.1)]])
    assert rings == [] and open_ways == 1


def test_two_separate_rings_stay_two():
    rings, open_ways = fms.stitch_rings([[(p["lon"], p["lat"]) for p in w["geometry"]] for w in box_ways() + box_ways(5, 5, 5.1, 5.1)])
    assert len(rings) == 2 and open_ways == 0


# ---------- areas

def test_a_box_has_the_area_a_sphere_gives_it():
    ring = [(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1), (0.0, 0.0)]
    assert fms.ring_area_km2(ring) == pytest.approx(sphere_box_km2(0, 0, 0.1, 0.1), rel=1e-9)
    assert fms.ring_area_km2(ring) == pytest.approx(123.6, abs=0.3)   # 11.1 km by 11.1 km at the equator
    assert fms.ring_area_km2(ring[::-1]) == fms.ring_area_km2(ring), "the winding does not matter"
    far = [(101.5, 3.0), (101.6, 3.0), (101.6, 3.1), (101.5, 3.1), (101.5, 3.0)]
    assert fms.ring_area_km2(far) == pytest.approx(sphere_box_km2(101.5, 3.0, 101.6, 3.1), rel=1e-9)


def test_a_hole_is_taken_out_of_the_area_and_a_hole_outside_every_outer_ring_is_ignored():
    outer, hole = box_ways(0, 0, 0.1, 0.1), box_ways(0.02, 0.02, 0.04, 0.04, role="inner")
    stray = box_ways(0.5, 0.5, 0.6, 0.6, role="inner")
    feature = fms.feature_of(relation(1, "Seksyen 7", outer + hole + stray))
    expected = sphere_box_km2(0, 0, 0.1, 0.1) - sphere_box_km2(0.02, 0.02, 0.04, 0.04)
    assert feature["properties"]["area_km2"] == pytest.approx(expected, abs=0.001)
    assert [len(poly) for poly in feature["geometry"]["coordinates"]] == [2], "one outer ring with one hole"


# ---------- features

def test_a_feature_carries_its_name_section_and_id_and_says_when_a_ring_did_not_close():
    feature = fms.feature_of(relation(42, "Seksyen U5", box_ways(), **{"name:en": "Section U5"}))
    assert feature["geometry"]["type"] == "MultiPolygon"
    assert feature["properties"] == {"osm_id": 42, "name": "Seksyen U5", "name_en": "Section U5", "section": "U5",
                                     "admin_level": "10", "area_km2": round(sphere_box_km2(0, 0, 0.1, 0.1), 3)}
    broken = fms.feature_of(relation(43, "Seksyen 1", box_ways()[:3]))
    assert broken["properties"]["open_rings"] == 1 and broken["properties"]["area_km2"] == 0


def test_the_recorded_relation_is_a_closed_section_of_a_plausible_size():
    answer = json.loads((FIXTURES / "sections_one.json").read_text(encoding="utf-8"))
    [feature] = fms.sections_of(answer)
    assert feature["properties"]["name"] == "Seksyen 10" and feature["properties"]["section"] == "10"
    assert "open_rings" not in feature["properties"]
    assert 0.1 < feature["properties"]["area_km2"] < 1, "Seksyen 10 is a small section: a quarter of a square kilometre"
    for polygon in feature["geometry"]["coordinates"]:
        for ring in polygon:
            assert ring[0] == ring[-1]
            assert all(101.4 < lon < 101.6 and 3.0 < lat < 3.2 for lon, lat in ring)


def test_sections_come_in_number_order_then_the_u_sections():
    names = ["Seksyen U2", "Seksyen 10", "Seksyen 2", "Seksyen U10", "Seksyen 1", "Seksyen U1"]
    answer = {"elements": [relation(i, n, box_ways()) for i, n in enumerate(names)]}
    assert [f["properties"]["name"] for f in fms.sections_of(answer)] == [
        "Seksyen 1", "Seksyen 2", "Seksyen 10", "Seksyen U1", "Seksyen U2", "Seksyen U10"]


def test_the_outline_is_the_city_relation_and_nothing_else_will_do():
    answer = {"elements": [relation(fms.CITY_RELATION, "Shah Alam", box_ways(), admin_level="7")]}
    assert fms.outline_of(answer)["properties"]["osm_id"] == fms.CITY_RELATION
    with pytest.raises(RuntimeError, match=str(fms.CITY_RELATION)):
        fms.outline_of({"elements": [relation(1, "Seksyen 1", box_ways())]})


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


def test_overpass_gets_a_descriptive_user_agent_and_the_query_in_the_body(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(agent=request.get_header("User-agent"), body=request.data.decode(), url=request.full_url)
        return Reply(b'{"elements": []}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert fms.overpass_post(fms.SECTIONS_QUERY) == {"elements": []}
    assert "myflood-research" in seen["agent"], "without one Overpass answers 406"
    assert "@" not in seen["agent"], "no personal address in the User-Agent"
    assert seen["url"] == fms.OVERPASS_URL
    assert "rel%28" in seen["body"] and "subarea" in seen["body"]


def test_a_busy_server_is_asked_again_after_a_longer_wait_and_a_refusal_is_not(monkeypatch):
    answers = [urllib.error.HTTPError(fms.OVERPASS_URL, 504, "Gateway Timeout", {}, None), Reply(b'{"elements": [1]}')]
    waits = []

    def fake_urlopen(request, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fms.time, "sleep", waits.append)
    assert fms.overpass_post("q") == {"elements": [1]}
    assert waits == [fms.PAUSE_SECONDS, fms.PAUSE_SECONDS * fms.RETRY_WAIT_FACTOR]

    def refused(request, timeout):
        raise urllib.error.HTTPError(fms.OVERPASS_URL, 406, "Not Acceptable", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    with pytest.raises(urllib.error.HTTPError):
        fms.overpass_post("q")


# ---------- the files

def fake_post(query: str) -> dict:
    stamp = {"timestamp_osm_base": "2026-10-04T08:01:00Z"}
    if query == fms.SECTIONS_QUERY:
        return {"osm3s": stamp, "elements": [relation(2, "Seksyen 2", box_ways(0, 0, 0.1, 0.1)),
                                             relation(1, "Seksyen 1", box_ways(1, 1, 1.1, 1.1))]}
    assert query == fms.OUTLINE_QUERY
    return {"osm3s": stamp, "elements": [relation(fms.CITY_RELATION, "Shah Alam", box_ways(0, 0, 2, 2), admin_level="7")]}


def test_build_writes_the_raw_answers_the_geojson_files_and_sources(tmp_path):
    counts = fms.build(tmp_path, "2026-10-04", fake_post)
    assert counts["sections"] == 2
    assert counts["sections_km2"] == pytest.approx(sphere_box_km2(0, 0, 0.1, 0.1) + sphere_box_km2(1, 1, 1.1, 1.1), abs=0.01)
    assert (tmp_path / "raw_2026-10-04" / "sections.json").is_file() and (tmp_path / "raw_2026-10-04" / "outline.json").is_file()
    sections = json.loads((tmp_path / "sections.geojson").read_text(encoding="utf-8"))
    assert [f["properties"]["name"] for f in sections["features"]] == ["Seksyen 1", "Seksyen 2"]
    outline = json.loads((tmp_path / "city_outline.geojson").read_text(encoding="utf-8"))
    assert len(outline["features"]) == 1 and outline["features"][0]["properties"]["name"] == "Shah Alam"
    text = (tmp_path / "SOURCES.md").read_text(encoding="utf-8")
    for expected in ("ODbL", "OpenStreetMap contributors", "2 section relations", "expected 56", "all rings closed",
                     "2026-10-04T08:01:00Z", fms.SECTIONS_QUERY, "HTTP 406"):
        assert expected in text, expected


def test_main_succeeds_with_the_56_sections_and_fails_loudly_with_any_other_count(tmp_path, monkeypatch, capsys):
    counts = {"sections": 56, "sections_km2": 302.2, "city_km2": 302.4}
    monkeypatch.setattr(fms, "build", lambda out, date: counts)
    assert fms.main(["--out", str(tmp_path), "--date", "2026-01-02"]) == 0
    assert "56 sections (expected 56)" in capsys.readouterr().out
    monkeypatch.setattr(fms, "build", lambda out, date: {**counts, "sections": 55})
    assert fms.main(["--out", str(tmp_path)]) == 1
