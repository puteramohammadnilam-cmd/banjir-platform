"""The index tools for a whole state (Johor), on small made-up inputs, no network: 3 arc second squares that each hold
the lowest of their nine GLO-30 heights (tools/build_elevation.py --step 3), the area settings (index_inputs.PLACES),
10 m sources read in bands, the Overpass tiling of tools/fetch_state_osm.py, and app/elevation.py and
tools/build_lowground.py reading such squares on their own."""
import json
import math
import sys
from array import array
from pathlib import Path

import pytest

from app import elevation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_elevation as be  # noqa: E402
import build_lowground as bl  # noqa: E402
import fetch_area_osm as fa  # noqa: E402
import fetch_state_osm as fs  # noqa: E402
import ffpi_text  # noqa: E402
import geotiff_write as gw  # noqa: E402
import grid_ops as go  # noqa: E402
import index_inputs as ii  # noqa: E402

ND = -9999.0
ARC = 1 / 3600


# --- the lowest of each block ---

def test_each_block_takes_its_lowest_height_leaving_out_no_data():
    fine = be.Window(0, 0, 3, 6, ARC, ARC)
    values = array("f", [5, 4, 9, ND, ND, ND,
                         6, 7, 8, ND, ND, ND,
                         3, 9, 9, ND, 2, ND])
    assert list(be.block_lowest(values, fine, 3)) == [3.0, 2.0]
    assert list(be.block_lowest(array("f", [ND] * 9), be.Window(0, 0, 3, 3, ARC, ARC), 3)) == [ND]


def test_a_coarse_square_holds_the_nine_glo30_squares_centred_on_it():
    work = be.Window(102 * 1200, 2 * 1200, 2, 2, 3 * ARC, 3 * ARC)
    seen = {}

    def fake_mosaic(cogs, fine):
        seen["fine"] = fine
        return array("f", range(fine.rows * fine.cols))

    original, be.mosaic = be.mosaic, fake_mosaic
    try:
        lowest = be.surface_for([type("Cog", (), {"px": ARC, "py": ARC})()], work, 3)
    finally:
        be.mosaic = original
    fine = seen["fine"]
    assert (fine.gx0, fine.gy0, fine.rows, fine.cols) == (3 * work.gx0 - 1, 3 * work.gy0 + 1, 6, 6)
    # the fine squares' centres are 3 gx - 1 .. 3 gx + 1: the coarse square's own centre is the middle one
    assert fine.gx0 + 1 == 3 * work.gx0 and fine.gy0 - 1 == 3 * work.gy0
    assert list(lowest) == [0.0, 3.0, 18.0, 21.0]


# --- the area settings ---

def test_johor_is_on_3_arc_second_squares_and_shah_alam_on_glo30_s_own():
    johor, shah_alam = ii.PLACES["johor"], ii.PLACES["shah-alam"]
    assert (johor.step, johor.window, shah_alam.step, shah_alam.window) == (3, 0, 1, 1)
    grid = ii.grid_window(johor)
    assert math.isclose(grid.px, 3 * ARC) and math.isclose(grid.py, 3 * ARC)
    part = be.Window.around(be.expand(johor.bbox, ii.MARGIN_KM * 1000), 3 * ARC, 3 * ARC)
    assert (grid.rows, grid.cols) == (part.rows, part.cols) and (grid.west, grid.north) == part.origin()
    assert ii.grid_window() == ii.grid_window(shah_alam), "the default is still Shah Alam's"
    assert ii.raw_root(johor).name == "johor" and ii.raw_root().name == "shah_alam"


def test_the_coarse_method_says_92_m_and_why():
    coarse, own = ffpi_text.method(3), ffpi_text.method()
    assert "92 m" in coarse["summary"] and "30 m" in own["summary"]
    assert coarse["deviations"][0] == ffpi_text.COARSE_SQUARES and ffpi_text.COARSE_SQUARES not in own["deviations"]
    assert coarse["factors"]["M"] == ffpi_text.COARSE_SLOPE and own["factors"]["M"] == ffpi_text.FACTORS["M"]
    assert len(coarse["deviations"]) == len(own["deviations"]) + 1


# --- 10 m sources in bands ---

def test_bands_cover_the_window_with_their_own_north_edges(monkeypatch):
    monkeypatch.setattr(ii, "BAND_ROWS", 4)
    found = ii._bands((10, 3, 10, 7), (100.0, 5.0, 0.5, 0.25, 7))
    assert [part for part, _ in found] == [(10, 3, 4, 7), (14, 3, 4, 7), (18, 3, 2, 7)]
    assert [src[1] for _, src in found] == [5.0, 4.0, 3.0]


def test_counts_added_band_by_band_are_the_counts_of_the_whole():
    grid = go.Grid(0.0, 2.0, 1.0, 1.0, 2, 2)
    values = [10, 10, 50, 50, 10, 80, 50, 50, 10, 10, 10, 50, 80, 80, 50, 50]   # 4 x 4 pixels of 0.5 degrees
    whole = go.fractions_from(grid, values, (0.0, 2.0, 0.5, 0.5, 4), (10, 50, 80))
    into = go.fractions_from(grid, values[:8], (0.0, 2.0, 0.5, 0.5, 4), (10, 50, 80))
    go.fractions_from(grid, values[8:], (0.0, 1.0, 0.5, 0.5, 4), (10, 50, 80), into=into)
    assert {k: list(v) for k, v in into.items()} == {k: list(v) for k, v in whole.items()}
    assert list(whole[10]) == [3, 0, 2, 1] and list(whole[80]) == [1, 0, 2, 0]


def test_many_shapes_can_be_marked_into_one_mask():
    grid = go.Grid(0.0, 3.0, 1.0, 1.0, 3, 3)
    square = lambda w, s: {"type": "Polygon", "coordinates": [[(w, s), (w + 1, s), (w + 1, s + 1), (w, s + 1), (w, s)]]}  # noqa: E731
    mask = bytearray(grid.size)
    go.polygon_mask(grid, square(0, 2), into=mask)
    go.polygon_mask(grid, square(2, 0), into=mask)
    assert list(mask) == [1, 0, 0, 0, 0, 0, 0, 0, 1]


# --- asking Overpass tile by tile ---

def test_tiles_cut_the_box_without_gaps():
    parts = fs.tiles((100.0, 1.0, 103.0, 4.0), 3)
    assert len(parts) == 9 and parts[0] == (100.0, 3.0, 101.0, 4.0) and parts[-1] == (102.0, 1.0, 103.0, 2.0)
    assert sum((e - w) * (n - s) for w, s, e, n in parts) == pytest.approx(9.0)


def test_a_part_that_times_out_is_asked_again_in_four(monkeypatch):
    asked = []

    def post(query):
        asked.append(query)
        if len(asked) == 1:
            raise fa.OverpassTimeout("runtime error: timed out")
        return {"elements": [{"type": "way", "id": len(asked)}], "osm3s": {"timestamp_osm_base": "2026-11-28T00:00:00Z"}}

    answers = fs.ask_box(fs.roads_query, (100.0, 1.0, 102.0, 3.0), post)
    assert len(asked) == 5 and len(answers) == 4
    assert "service" not in asked[0] and "residential" in asked[0]


def test_a_part_that_still_times_out_at_the_last_split_is_raised():
    def post(query):
        raise fa.OverpassTimeout("runtime error: timed out")

    with pytest.raises(fa.OverpassTimeout):
        fs.ask_box(fs.drains_query, (100.0, 1.0, 102.0, 3.0), post, splits=1)


# --- reading 3 arc second squares on their own ---

def write_coarse(folder: Path, name: str, heights: list[list[float]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for layer, rows in (("surface", [[v + 10 if v != ND else ND for v in row] for row in heights]),
                        ("above_river", heights)):
        gw.write_tiff(folder / f"{name}_{layer}.tif", rows, tile=16, origin=(103.0, 2.0), pixel=(3 * ARC, 3 * ARC),
                      padding=ND)
    return folder


def test_a_coarse_crop_gives_the_spot_s_own_square_not_its_neighbours(tmp_path, monkeypatch):
    folder = write_coarse(tmp_path / "dem", "state", [[5.0, 1.0, 5.0], [5.0, 7.0, 5.0], [5.0, 5.0, 5.0]])
    monkeypatch.setenv("BANJIR_DEM_DIR", str(folder))
    elevation.crops.cache_clear()
    try:
        lat, lon = 2.0 - 1.5 * 3 * ARC, 103.0 + 1.5 * 3 * ARC   # the middle square's centre
        assert elevation.at(lat, lon) == {"ground_m": 17.0, "above_river_m": 7.0}
    finally:
        elevation.crops.cache_clear()


def test_the_low_ground_of_a_coarse_crop_is_each_square_s_own_and_its_sources_its_own(tmp_path):
    folder = write_coarse(tmp_path / "dem", "state", [[0.5, 4.0, ND], [2.5, 0.5, 6.0]])
    (folder / "SOURCES.txt").write_text("the city's\n", encoding="utf-8")
    found = bl.build(folder, "state")
    assert list(found["lowest"]) == [0.5, 4.0, ND, 2.5, 0.5, 6.0]
    assert (folder / "SOURCES.txt").read_text(encoding="utf-8") == "the city's\n", "the city's sources are left alone"
    text = (folder / "SOURCES-state.txt").read_text(encoding="utf-8")
    assert text.startswith(bl.SOURCES_HEADING) and "own 92 m square" in text
    assert "about 92 m" in json.loads(found["json"].read_text(encoding="utf-8"))["rule"]


def test_low_ground_cut_to_an_outline_shades_nothing_outside_it(tmp_path):
    folder = write_coarse(tmp_path / "dem", "state", [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5]])
    west, north, size = 103.0, 2.0, 3 * ARC
    left_two = {"type": "Polygon", "coordinates": [[(west, north - 2 * size), (west + 2 * size, north - 2 * size),
                                                    (west + 2 * size, north), (west, north), (west, north - 2 * size)]]}
    outline = tmp_path / "districts.geojson"
    outline.write_text(json.dumps({"type": "FeatureCollection", "features": [{"geometry": left_two}]}), encoding="utf-8")
    found = bl.build(folder, "state", outline)
    assert list(found["lowest"]) == [0.5, 0.5, ND, 0.5, 0.5, ND]
    assert "Cut to the outline of districts.geojson" in json.loads(found["json"].read_text(encoding="utf-8"))["png"]["masked"]


# --- the committed Johor files ---

INDEX_DIR = ROOT / "app" / "data" / "indexes"
JOHOR_DOC = json.loads((INDEX_DIR / "johor_ffpi.json").read_text(encoding="utf-8"))


def test_johor_s_ffpi_json_is_on_its_92_m_grid_with_the_coarse_method():
    import build_ffpi as bf
    grid = ii.grid_window(ii.PLACES["johor"])
    assert JOHOR_DOC["grid"] == {"west": grid.west, "north": grid.north, "px": grid.px, "py": grid.py,
                                 "rows": grid.rows, "cols": grid.cols}
    assert JOHOR_DOC["classes"] == list(bf.CLASSES) and JOHOR_DOC["breaks"] == list(bf.BREAKS)
    assert JOHOR_DOC["method"] == ffpi_text.method(3) and JOHOR_DOC["area"] == "johor"
    assert "outline of its districts" in JOHOR_DOC["png"]["masked"]


def test_johor_s_files_are_small_enough_for_git_and_listed_in_its_sources():
    import hashlib
    sources = (INDEX_DIR / "SOURCES-johor.txt").read_text(encoding="utf-8")
    for name, budget in (("johor_ffpi.tif", 2_500_000), ("johor_ffpi.png", 400_000)):
        data = (INDEX_DIR / name).read_bytes()
        assert len(data) <= budget, name
        assert f"{name}: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}" in sources


@pytest.mark.parametrize(("spot", "lat", "lon", "found"), [
    ("Johor Bahru city centre", 1.4627, 103.7614, {"score": 7.4, "class": "high"}),
    ("oil palm west of Kluang", 1.9500, 103.2000, {"score": 3.8, "class": "low"}),
    ("Singapore, outside Johor's districts", 1.35, 103.82, None),
])
def test_johor_spots_stay_as_built(spot, lat, lon, found, monkeypatch):
    from app import indexes
    monkeypatch.delenv("BANJIR_INDEX_DIR", raising=False)
    indexes.crops.cache_clear()
    assert indexes.flash_at(lat, lon) == found, spot


def test_each_area_s_layer_says_its_squares_size(monkeypatch):
    from app import indexes
    monkeypatch.delenv("BANJIR_INDEX_DIR", raising=False)
    indexes.crops.cache_clear()
    assert indexes.layer("johor")["square_m"] == 90 and indexes.layer("shah-alam")["square_m"] == 30


def test_johor_s_indexes_json_has_every_district_and_its_score_stays_held_back():
    from app import areas, sections
    doc = json.loads((ROOT / "app" / "data" / "areas" / "johor" / "indexes.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in json.loads((ROOT / "app" / "data" / "areas" / "johor" / "sections.json")
                                       .read_text(encoding="utf-8"))["sections"]]
    assert list(doc["sections"]) == ids and len(ids) == 10
    for figures in doc["sections"].values():
        assert sum(figures["flash"]["share"].values()) == pytest.approx(1.0, abs=0.002)
    assert doc["method"]["score"]["deviations"][0].startswith("A whole state is worked out on 92 m squares")
    assert areas.get("johor").show_index_score is False
    sent = sections.index_method("johor")
    assert sent["show_score"] is False and "score" not in sent
    assert all("score" not in sections.public(s, "johor")["indexes"] for s in sections.listed("johor"))


# --- after the review ---

def test_rank_comparisons_over_too_few_sections_are_not_sent():
    from app import sections
    johor, shah_alam = sections.index_method("johor"), sections.index_method("shah-alam")
    assert johor["validation"]["n"] == 10 and johor["validation"]["spearman"] == {}
    assert shah_alam["validation"]["n"] == 56 and "flash_vs_history" in shah_alam["validation"]["spearman"]
    assert sections._comparable({"n": 19, "spearman": {"x": 0.9}})["spearman"] == {}
    assert sections._comparable({"n": 20, "spearman": {"x": 0.9}})["spearman"] == {"x": 0.9}


def test_a_state_s_score_words_say_92_m_and_name_no_city_s_hotspots():
    import build_section_scores as bs
    import score_text
    johor = bs.method_doc(ii.PLACES["johor"])["score"]
    assert johor["summary"].startswith("Each 92 m square") and bs.method_doc()["score"]["summary"].startswith("Each 30 m")
    assert all("city" not in d or "kept for the state" in d for d in johor["deviations"])
    elevation = next(c for c in johor["criteria"] if c["id"] == "elevation")
    assert elevation["source"] == score_text.COARSE_ELEVATION
    assert "hotspot_source" not in score_text.validation_doc(10, {}, [])
    assert "hotspot_source" in score_text.validation_doc(56, {}, [{"id": "seksyen-25"}])
    doc = json.loads((ROOT / "app" / "data" / "areas" / "johor" / "indexes.json").read_text(encoding="utf-8"))
    assert doc["method"] == bs.method_doc(ii.PLACES["johor"]) and "hotspot_source" not in doc["validation"]


def busy(code: int = 502):
    import urllib.error
    return urllib.error.HTTPError("https://overpass.example/api", code, "busy", {}, None)


def test_a_busy_server_is_asked_again_after_a_wait_and_other_errors_are_not():
    calls = []

    def post(query):
        calls.append(query)
        if len(calls) < 3:
            raise busy()
        return {"elements": []}

    assert fs.patient(post, wait_s=0, rounds=5)("q") == {"elements": []} and len(calls) == 3
    with pytest.raises(Exception) as error:
        fs.patient(lambda query: (_ for _ in ()).throw(busy(400)), wait_s=0)("q")
    assert error.value.code == 400
    tries = []
    with pytest.raises(Exception):
        fs.patient(lambda query: tries.append(query) or (_ for _ in ()).throw(busy()), wait_s=0, rounds=2)("q")
    assert len(tries) == 2


def test_kept_parts_are_named_by_their_question(tmp_path):
    asked = []

    def post(query):
        asked.append(query)
        return {"elements": [{"type": "way", "id": len(asked)}], "osm3s": {"timestamp_osm_base": "2026-11-28T00:00:00Z"}}

    box = (100.0, 1.0, 102.0, 3.0)
    fs.fetch(fs.roads_query, box, 2, tmp_path, post)
    fs.fetch(fs.roads_query, box, 2, tmp_path, post)
    assert len(asked) == 4, "the second run reuses the kept parts"
    fs.fetch(fs.drains_query, box, 2, tmp_path, post)
    assert len(asked) == 8, "another question does not take the roads' parts"


# --- Johor polish ---

def test_a_district_page_sends_the_relief_centres_in_reach_and_every_shop_s_own():
    from app import areas, sections
    johor = areas.get("johor")
    counts = {}
    for section in sections.listed("johor"):
        sent = sections.section_data(johor, section)["town"]["shelters"]
        counts[section["id"]] = len(sent)
        names = {s["name"] for s in sent}
        assert all(p["shelter"]["name"] in names for p in sections.section_premises("johor", section["id"]) if p.get("shelter"))
    assert counts["tangkak"] == 0 and counts["johor-bahru"] > 0 and max(counts.values()) < len(areas.town("johor")["shelters"])
    assert sections.city_data(johor)["town"]["shelters"] == areas.town("johor")["shelters"], "the whole state keeps all"


def test_the_chat_s_rain_for_a_whole_state_names_its_town(monkeypatch):
    from app import areas, floodtools, googlemaps, sections
    seen = []
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: seen.append((lat, lon)) or {"total_mm": 3})
    johor = areas.get("johor")
    for section, town in ((None, "Johor Bahru"), (sections.get(johor, "muar"), None)):
        token = floodtools.start_question(johor, None, section)
        try:
            found = floodtools.rain_forecast()
        finally:
            floodtools.end_question(token)
        assert found["total_mm"] == 3 and found.get("town") == town
    assert seen[0] == johor.centre() and seen[1] == sections.centre(sections.get(johor, "muar"))
