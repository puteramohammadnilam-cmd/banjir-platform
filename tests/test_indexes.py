"""app/indexes.py (flash flood potential at a spot, the map layer), the premise and point fields, indexes.json for the
sections, and the layer's route, on small fixture files (tests/index_fixture.py, every number known) and the made-up
city of tests/sectioned_fixture.py. Names and docstrings here name no real place.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_indexes.py
"""
import json
import logging
import re
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import index_fixture as ix
import tiff_fixture as fx
from app import areas, indexes, main, places, raster, sections
from index_fixture import CITY_GRID, DEPTH_GRID, centre, score
from sectioned_fixture import CITY, PLAIN, city  # noqa: F401  (city is a fixture)

LAYER_URL = f"/api/areas/{CITY}/layers/flash-flood.png"
NO_LAYER = {"success": False, "data": None, "error": "No layer."}


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """BANJIR_INDEX_DIR pointed at a folder holding the fixture set on the flood model fixture's grid."""
    where = ix.write_set(tmp_path / "indexes")
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(where))
    return where


# --- the lookup ---

def test_a_square_gives_its_own_score_and_the_class_it_falls_in(folder):
    assert indexes.flash_at(*centre(5, 7)) == {"score": 6.6, "class": "high"} == {"score": score(5, 7), "class": "high"}
    assert indexes.flash_at(*centre(15, 16)) == {"score": 7.3, "class": "high"}   # across four tiles
    assert indexes.flash_at(*centre(19, 23)) == {"score": 3.2, "class": "low"}    # the last square


def test_a_score_on_a_break_is_in_the_class_above_it(folder):
    assert [indexes.flash_at(*centre(0, c)) for c in (4, 1, 2, 3, 6)] == [
        {"score": 3.4, "class": "low"}, {"score": 3.5, "class": "medium"}, {"score": 6.0, "class": "high"},
        {"score": 8.0, "class": "extreme"}, {"score": 10.0, "class": "extreme"}]


def test_no_data_nan_and_outside_the_grid_are_none(folder, tmp_path, monkeypatch):
    assert indexes.flash_at(*centre(0, 0)) is None and indexes.flash_at(*centre(0, 5)) is None
    west, north = DEPTH_GRID["origin"]
    south = north - DEPTH_GRID["rows"] * DEPTH_GRID["pixel"]
    assert indexes.flash_at(south - 0.01, west + 1) is None
    assert indexes.flash_at(north - 1, west + DEPTH_GRID["cols"] * DEPTH_GRID["pixel"]) is None   # the east edge is out
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(tmp_path / "missing"))
    assert indexes.flash_at(*centre(5, 7)) is None and indexes.layer("test-area") is None


def test_a_second_area_is_read_where_the_first_does_not_reach(folder):
    ix.write_set(folder, "test-city", CITY_GRID)
    assert indexes.flash_at(*centre(2, 3, CITY_GRID)) == {"score": score(2, 3), "class": "low"}
    assert indexes.flash_at(*centre(5, 7)) == {"score": 6.6, "class": "high"}
    assert indexes.classes("test-city") == ("low", "medium", "high", "extreme") and indexes.classes("nope") is None


@pytest.mark.parametrize(("changes", "words"), [
    ({"breaks": [6.0, 3.5, 8.0]}, "breaks must rise"),
    ({"breaks": [3.5, 6.0]}, "one fewer than the classes"),
    ({"breaks": [3.5, 6.0, "8"]}, "breaks"),
    ({"classes": ["low", "", "high", "extreme"]}, "classes"),
    ({"classes": ["low", "medium", "high", "high"]}, "classes"),
    ({"credit": ""}, "credit"),
])
def test_files_whose_breaks_do_not_fit_their_classes_are_refused(tmp_path, changes, words):
    where = ix.write_set(tmp_path / "bad", meta=changes)
    with pytest.raises(raster.RasterError, match=words):
        indexes.load(where)


def test_the_jsons_bounds_must_be_the_tifs_grid(tmp_path):
    for bounds in ([100.0, 5.0, 106.0, 10.5], [100.0, 5.0, 106.0], "all", [100.0, 5.0, 106.0, "10"]):
        with pytest.raises(raster.RasterError, match="bounds are not the grid of test-area_ffpi.tif"):
            indexes.load(ix.write_set(tmp_path / f"b{len(str(bounds))}", meta={"bounds": bounds}))
    assert len(indexes.load(ix.write_set(tmp_path / "ok", meta={"bounds": None}))) == 1   # bounds are optional


def test_a_set_with_a_file_missing_or_unreadable_json_is_refused(tmp_path):
    with pytest.raises(raster.RasterError, match="no json file"):
        indexes.load(ix.write_set(tmp_path / "a", files=("tif", "png")))
    with pytest.raises(raster.RasterError, match="no tif file"):
        indexes.load(ix.write_set(tmp_path / "b", files=("json",)))
    with pytest.raises(raster.RasterError, match="test-area_ffpi.json"):
        indexes.load(ix.write_set(tmp_path / "c", meta="{not json"))
    assert indexes.load(tmp_path / "none") == ()
    assert indexes.load(ix.write_set(tmp_path / "d", files=("tif", "json")))[0].png is None


def test_a_bad_set_gives_none_and_a_log_that_names_the_file(folder, caplog):
    (folder / "test-area_ffpi.json").write_text('{"classes": []}', encoding="utf-8")
    indexes.crops.cache_clear()
    with caplog.at_level(logging.DEBUG, logger="banjir"):
        assert indexes.flash_at(*centre(5, 7)) is None and indexes.layer("test-area") is None
    assert "test-area_ffpi.json" in caplog.text


def test_a_damaged_file_logs_its_name_and_tile_but_never_the_point(tmp_path, monkeypatch, caplog):
    where = ix.write_set(tmp_path / "broken", chunks={0: b"not deflate data"})
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(where))
    lat, lon = centre(3, 4)
    with caplog.at_level(logging.DEBUG, logger="banjir"):
        assert indexes.flash_at(lat, lon) is None
    assert "test-area_ffpi.tif: tile 0" in caplog.text
    assert (lat, lon) == (9.125, 101.125)
    assert not re.search(r"9\.12|101\.12", caplog.text)


# --- the map layer ---

def test_the_layer_gives_its_url_bounds_breaks_and_credit(folder):
    assert indexes.layer("test-area") == {"url": "/api/areas/test-area/layers/flash-flood.png",
                                          "bounds": [100.0, 5.0, 106.0, 10.0], "breaks": [3.5, 6.0, 8.0],
                                          "credit": ix.CREDIT}
    assert indexes.png_path("test-area") == folder / "test-area_ffpi.png"
    assert indexes.flash_method("test-area") == {key: ix.FLASH_METHOD[key] for key in indexes.METHOD_KEYS}
    assert "factors" not in indexes.flash_method("test-area") and indexes.breaks("test-area") == (3.5, 6.0, 8.0)
    assert indexes.flash_method("other") is None and indexes.breaks("other") is None
    assert indexes.layer("other") is None and indexes.png_path("other") is None
    assert indexes.png_path("../test-area") is None and indexes.png_path(None) is None
    (folder / "test-area_ffpi.png").unlink()
    indexes.crops.cache_clear()
    assert indexes.layer("test-area") is None and indexes.png_path("test-area") is None


# --- premises and points ---

PREMISE_SQUARES = {"node-990000001": (4, 1), "node-990000002": (3, 2), "node-990000003": (3, 3),
                   "node-990000004": (2, 4), "node-990000005": (2, 5)}


@pytest.fixture
def city_indexes(city, tmp_path, monkeypatch):
    where = ix.write_set(tmp_path / "indexes", CITY, CITY_GRID)
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(where))
    return where


def test_each_premise_carries_the_figure_of_its_own_square(city_indexes):
    found = {p["id"]: p["flash_flood"] for p in areas.premises(CITY)}
    for premise_id, (row, col) in PREMISE_SQUARES.items():
        assert found[premise_id]["score"] == score(row, col), premise_id
        assert set(found[premise_id]) == {"score", "class"}
    assert found["node-990000006"] in ({"score": score(1, 1), "class": "low"}, {"score": score(0, 1), "class": "medium"})
    assert found["node-990000003"] == {"score": 4.0, "class": "medium"}
    assert places.resolve("node-990000003")["flash_flood"] == found["node-990000003"]


def test_premises_have_a_null_figure_where_no_file_covers_them(city, monkeypatch, tmp_path):
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(tmp_path / "missing"))
    assert all(p["flash_flood"] is None for p in areas.premises(CITY))
    assert all(p["flash_flood"] is None for p in areas.premises(PLAIN))


def test_a_point_carries_the_figure_at_its_squares_centre(folder, tmp_path, monkeypatch):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(fx.write_depth_set(tmp_path / "rasters")))
    place = places.point(*centre(14, 4))   # inside the Peninsula box, covered by the depth fixture
    assert place["flash_flood"] == indexes.flash_at(*places.parse_point_id(place["id"])) == \
        {"score": 3.0, "class": "low"} == {"score": score(14, 4), "class": "low"}
    monkeypatch.setenv("BANJIR_INDEX_DIR", str(tmp_path / "missing"))
    assert places.point(*centre(14, 4))["flash_flood"] is None   # no files: null, the place still answers


# --- indexes.json for the sections ---

def write_doc(root, **changes):
    return ix.write_indexes(root / CITY, [s["id"] for s in sections.listed(CITY)], **changes)


def test_a_section_without_the_file_is_sent_as_it_was(city):
    assert sections.index_doc(CITY) is None
    assert "indexes" not in sections.public(sections.listed(CITY)[0], CITY)
    sent = sections.details(areas.get(CITY))
    assert sent["index_method"] is None and sent["layers"] == {"flash_flood": None}
    plain = sections.details(areas.get(PLAIN))
    assert plain["index_method"] is None and plain["layers"] == {"flash_flood": None}


def test_a_section_carries_its_flash_and_score_figures(city):
    write_doc(city)
    sections.clear_caches()
    first = sections.public(sections.listed(CITY)[0], CITY)
    assert first["indexes"] == {"flash": {"mean": 6.0, "share": ix.SHARE},
                                "score": {"value": 2.0, "class": "moderate"}}
    assert "ratings" not in first["indexes"]["score"]
    assert sections.public(sections.listed(CITY)[0])["id"] == first["id"]   # without an area, no figures
    assert "indexes" not in sections.public(sections.listed(CITY)[0])


def test_a_section_with_no_land_square_has_null_figures(city):
    doc = ix.indexes_doc([s["id"] for s in sections.listed(CITY)])
    doc["sections"]["zon-1"].update(flash=None, score=None)
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    sections.preload()
    assert sections.public(sections.listed(CITY)[0], CITY)["indexes"] == {"flash": None, "score": None}


def test_a_section_with_no_score_has_flash_figures_and_a_null_score(city):
    doc = ix.indexes_doc([s["id"] for s in sections.listed(CITY)])
    for found in doc["sections"].values():
        del found["score"]
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    assert sections.public(sections.listed(CITY)[1], CITY)["indexes"]["score"] is None
    assert sections.public(sections.listed(CITY)[1], CITY)["indexes"]["flash"]["mean"] == 6.1


def test_the_details_carry_the_method_the_validation_and_the_layer(city, city_indexes):
    write_doc(city)
    sections.clear_caches()
    sent = sections.details(areas.get(CITY), "zon-2")
    method = sent["index_method"]
    assert method["flash"] == {key: ix.FLASH_METHOD[key] for key in indexes.METHOD_KEYS}
    assert method["score"]["deviations"] == ["Rainfall was left out: no source varies inside the city."]
    assert method["score"]["citations"] == ["Leeonis, A. N. et al. (2024) (criteria weights)"]
    assert method["score"]["credit"] == "Fixture score credit: people and drains."
    assert method["score"]["classes"] == ix.SCORE_CLASSES and method["score"]["breaks"] == [1.5, 2.5, 3.5, 4.5]
    assert method["score"]["weights_used"] == {"slope": 0.6, "elevation": 0.4} and "criteria" not in method["score"]
    assert method["validation"]["n"] == 3 and method["validation"]["hotspots"][0]["score_rank"] == 20
    assert sent["layers"]["flash_flood"]["url"] == LAYER_URL
    assert sent["layers"]["flash_flood"]["bounds"] == [101.5, 3.0, 101.56, 3.06]
    assert sections.details(areas.get(CITY)) == {**sent, "history": sections.details(areas.get(CITY))["history"]}
    method["score"]["deviations"].clear()   # a response gets its own copy
    method["flash"]["deviations"].clear()
    again = sections.details(areas.get(CITY))["index_method"]
    assert len(again["score"]["deviations"]) == 1 and len(again["flash"]["deviations"]) == 1


@pytest.mark.parametrize(("change", "words"), [
    (lambda doc: doc["sections"].pop("zon-1"), "sections must be exactly"),
    (lambda doc: doc["sections"].update({"zon-9": doc["sections"]["zon-1"]}), "sections must be exactly"),
    (lambda doc: doc.pop("validation"), "validation"),
    (lambda doc: doc["method"]["score"].pop("deviations"), "method must hold"),
    (lambda doc: doc["method"].pop("flash"), "method must hold"),
    (lambda doc: doc["sections"]["zon-1"]["flash"].update(mean="high"), "zon-1: flash"),
    (lambda doc: doc["sections"]["zon-1"]["score"].update(value=None), "zon-1: score"),
    (lambda doc: doc["sections"]["zon-1"]["flash"]["share"].pop("low"), "zon-1: flash shares.*classes"),
    (lambda doc: doc["city"]["flash"]["share"].pop("low"), "city: flash shares.*classes"),
    (lambda doc: doc["sections"]["zon-1"].update(flash=None), "zon-1: score must be null where flash is"),
    (lambda doc: doc["method"]["flash"].update(breaks=[3.25, 5.5, 7.75]), "method.flash must give the classes and breaks"),
    (lambda doc: doc["method"]["flash"].update(classes=["a", "b", "c", "d"]), "method.flash must give the classes"),
])
def test_an_indexes_file_that_does_not_fit_the_sections_stops_the_server_at_start_up(
        city, city_indexes, change, words):
    doc = ix.indexes_doc([s["id"] for s in sections.listed(CITY)])
    change(doc)
    (city / CITY / "indexes.json").write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=words):
        sections.preload()


def test_figures_by_other_classes_or_breaks_than_the_files_are_refused(city, city_indexes):
    ix.write_set(city_indexes, CITY, CITY_GRID, meta={"classes": ["a", "b", "c", "d"]})
    write_doc(city)
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=f"{CITY}: indexes.json.*classes and breaks.*shares.*classes"):
        sections.preload()
    ix.write_set(city_indexes, CITY, CITY_GRID, meta={"breaks": [3.25, 5.5, 7.75]})
    indexes.crops.cache_clear()
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=f"{CITY}: indexes.json: method.flash must give the classes and breaks"):
        sections.preload()
    ix.write_set(city_indexes, CITY, CITY_GRID)   # the files' own again: the figures fit
    indexes.crops.cache_clear()
    sections.clear_caches()
    sections.preload()


def test_an_indexes_file_in_an_area_not_split_into_sections_is_refused(city, monkeypatch):
    doc = ix.indexes_doc(["zon-1"])
    fake = lambda area_id: areas._freeze(doc) if area_id == PLAIN else None  # noqa: E731
    fake.cache_clear = lambda: None
    monkeypatch.setattr(areas, "indexes_file", fake)
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match=f"{PLAIN}: indexes.json.*not split"):
        sections.preload()


def test_the_figures_are_in_the_city_and_section_data(city, city_indexes):
    write_doc(city)
    sections.clear_caches()
    area = areas.get(CITY)
    sent = sections.city_data(area)
    assert all(s["indexes"]["flash"]["share"] == ix.SHARE for s in sent["sections"])
    assert sent["area"]["layers"]["flash_flood"]["breaks"] == [3.5, 6.0, 8.0]
    one = sections.section_data(area, sections.get(area, "zon-2"))
    assert one["section"]["indexes"]["score"] == {"value": 2.1, "class": "moderate"}
    assert all(p["flash_flood"] is not None for p in one["premises"])


# --- the layer's route ---

@pytest.fixture
def client(city, city_indexes):
    main._hits.clear()
    return TestClient(main.app)


def test_the_layer_is_a_png_checked_again_on_every_load(client):
    found = client.get(LAYER_URL)
    assert found.status_code == 200 and found.headers["content-type"] == "image/png"
    assert found.content == ix.png_bytes()
    assert found.headers["cache-control"] == "no-cache" and found.headers["etag"]
    again = client.get(LAYER_URL, headers={"If-None-Match": found.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_a_weak_or_listed_etag_is_matched_too(client):
    tag = client.get(LAYER_URL).headers["etag"]
    for wanted in (f"W/{tag}", f'"other", {tag}'):
        assert client.get(LAYER_URL, headers={"If-None-Match": wanted}).status_code == 304
    assert client.get(LAYER_URL, headers={"If-None-Match": '"other"'}).status_code == 200


def test_head_gives_the_headers_of_the_same_answer(client):
    got, head = client.get(LAYER_URL), client.head(LAYER_URL)
    assert head.status_code == 200 and head.content == b""
    assert {k: head.headers[k] for k in ("content-type", "etag", "cache-control")} == \
           {k: got.headers[k] for k in ("content-type", "etag", "cache-control")}
    assert head.headers["content-length"] == str(len(ix.png_bytes()))


@pytest.mark.parametrize("area_id", [PLAIN, "nowhere", "Test-City", "test_city"])
def test_an_area_with_no_layer_is_a_404_in_the_envelope(client, area_id):
    for method in (client.get, client.head):
        found = method(f"/api/areas/{area_id}/layers/flash-flood.png")
        assert found.status_code == 404
    assert client.get(f"/api/areas/{area_id}/layers/flash-flood.png").json() == NO_LAYER


def test_the_layer_is_a_404_when_the_files_are_gone(client, city_indexes):
    (city_indexes / f"{CITY}_ffpi.png").unlink()
    indexes.crops.cache_clear()
    assert client.get(LAYER_URL).json() == NO_LAYER
    assert client.post(LAYER_URL).status_code == 405


# --- the example place area.json may name ---

BASE = {"id": "test-town", "name": "T", "display_name": "T", "view": [100.0, 2.0, 100.1, 2.1], "zoom": 15,
        "ai_name": "T", "news_place": "T", "news_region": "T"}


@pytest.mark.parametrize(("value", "fine"), [
    (None, True), ("seksyen-13", True), ("zon-1", True),
    ("", False), ("  ", False), (5, False), ([], False), ({"section": "zon-1"}, False), ("Zon 1", False)])
def test_the_flash_flood_example_is_null_or_a_section_id(value, fine):
    problems = areas._problems({**BASE, "flash_flood_example": value}, "test-town")
    assert (problems == []) is fine, problems


def test_the_example_must_name_a_section_of_the_area_and_a_plain_area_has_none(city):
    area = areas.get(CITY)
    assert areas.check_built(area, areas.premises(CITY), areas.town(CITY), areas.section_ids(CITY)) is None
    named = replace(area, flash_flood_example="zon-9")
    with pytest.raises(areas.AreaError, match="flash_flood_example must name a known section"):
        areas.check_built(named, areas.premises(CITY), areas.town(CITY), areas.section_ids(CITY))
    plain = replace(areas.get(PLAIN), flash_flood_example="zon-1")
    with pytest.raises(areas.AreaError, match="flash_flood_example needs a sections.json"):
        areas.check_built(plain, areas.premises(PLAIN), areas.town(PLAIN), None)


def test_the_example_is_read_from_area_json_and_sent_in_the_details(city):
    assert areas.get(CITY).flash_flood_example is None
    assert sections.details(areas.get(CITY))["flash_flood_example"] is None
    path = city / CITY / "area.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**config, "flash_flood_example": "zon-2"}), encoding="utf-8")
    sections.clear_caches()
    assert sections.details(areas.get(CITY))["flash_flood_example"] == "zon-2"
    sections.preload()
