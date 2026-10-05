"""The low ground layer: tools/build_lowground.py on a tiny height-above-river tif (every number known), app/lowground.py,
its route, `layers.low_ground` in the area data, and the committed pictures against their JSON and SOURCES.txt. Names
and docstrings here name no real place.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_lowground.py
"""
import hashlib
import json
import logging
import struct
import sys
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import areas, lowground, main, sections
from sectioned_fixture import CITY, PLAIN, city  # noqa: F401  (city is a fixture)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_lowground as bl  # noqa: E402
import geotiff_write as gw  # noqa: E402
import grid_ops as go  # noqa: E402

DEM = ROOT / "app" / "data" / "dem"
ORIGIN, PIXEL, TILE = (100.0, 10.0), 0.25, 16
ND = -9999.0
# Every row the same: the 3 x 3 lowest of column c is the lowest of columns c - 1 to c + 1, and no data keeps no data.
COLUMNS = [0.5, 1.5, 2.5, 4.0, 6.0, ND]
HEIGHTS = [[-2.0] + COLUMNS[1:]] + [list(COLUMNS) for _ in range(2)]   # one square below the river's level
EXPECTED = {   # level: one row's PNG indices
    1: [1, 1, 0, 0, 0, 0],
    2: [1, 1, 2, 0, 0, 0],
    3: [1, 1, 2, 3, 0, 0],
    5: [1, 1, 2, 3, 4, 0],
}
NO_LAYER = {"success": False, "data": None, "error": "No layer."}


def write_dem(folder: Path, name: str = "test-area") -> Path:
    """The tiny crop: above_river as HEIGHTS, and a surface (app/elevation.py wants both) 10 m higher."""
    folder.mkdir(parents=True, exist_ok=True)
    surface = [[ND if v == ND else v + 10 for v in row] for row in HEIGHTS]
    for layer, rows in (("above_river", HEIGHTS), ("surface", surface)):
        gw.write_tiff(folder / f"{name}_{layer}.tif", rows, tile=TILE, origin=ORIGIN, pixel=(PIXEL, PIXEL), padding=ND)
    return folder


def read_png(path: Path) -> tuple[dict, list[list[int]]]:
    """(header and chunks, rows of palette indices) of an indexed PNG written with filter 0."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, at = {}, 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        chunks[kind.decode()] = chunks.get(kind.decode(), b"") + data[at + 8:at + 8 + length]
        at += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks["IHDR"][:10])
    raw, row_bytes = zlib.decompress(chunks["IDAT"]), -(-width * depth // 8)
    rows = []
    for r in range(height):
        line = raw[r * (row_bytes + 1):(r + 1) * (row_bytes + 1)]
        bits = "".join(format(b, "08b") for b in line[1:])
        rows.append([int(bits[i * depth:(i + 1) * depth], 2) for i in range(width)])
    return {"width": width, "height": height, "depth": depth, "colour": colour, **chunks}, rows


@pytest.fixture
def built(tmp_path, monkeypatch):
    """BANJIR_DEM_DIR pointed at a folder holding the tiny crop and its built layer."""
    folder = write_dem(tmp_path / "dem")
    bl.build(folder, "test-area")
    monkeypatch.setenv("BANJIR_DEM_DIR", str(folder))
    lowground.sets.cache_clear()
    return folder


# --- the build ---

@pytest.mark.parametrize(("height", "level", "index"), [
    (-3.0, 1, 1), (0.0, 1, 1), (1.0, 1, 1), (1.1, 1, 0), (1.1, 2, 2), (2.0, 2, 2), (2.1, 3, 3), (3.0, 5, 3),
    (3.1, 5, 4), (5.0, 5, 4), (5.1, 5, 0), (ND, 5, 0),
    (struct.unpack("<f", struct.pack("<f", 1.9))[0], 2, 2), (struct.unpack("<f", struct.pack("<f", 2.0))[0], 2, 2),
])
def test_a_height_at_or_below_the_level_gets_the_tone_of_its_band(height, level, index):
    assert bl.tone_of(height, level) == index


def test_one_png_per_level_holds_the_tones_of_the_3_by_3_lowest(built):
    for level, row in EXPECTED.items():
        info, rows = read_png(built / f"test-area_lowground_{level}m.png")
        assert (info["width"], info["height"], info["depth"], info["colour"]) == (6, 3, 4, 3)
        assert rows == [row, row, row], level
        palette = [info["PLTE"][i:i + 3].hex() for i in range(0, len(info["PLTE"]), 3)]
        assert palette[1:] == [tone["colour"][1:] for tone in bl.tones()]
        assert info["tRNS"] == b"\x00", "index 0 is transparent, the tones opaque (the map sets the opacity)"


def test_the_tones_darken_toward_the_lowest_ground():
    tones = bl.tones()
    assert [t["up_to_m"] for t in tones] == [1.0, 2.0, 3.0, 5.0] and [t["above_m"] for t in tones] == [None, 1.0, 2.0, 3.0]
    assert [t["oklch"][0] for t in tones] == sorted(t["oklch"][0] for t in tones)


def test_no_data_stays_transparent_even_beside_shaded_squares(tmp_path):
    grid = go.Grid(*ORIGIN, PIXEL, PIXEL, 1, 3)
    assert list(bl.lowest_heights([ND, 0.5, ND], grid)) == [ND, 0.5, ND]
    assert bl.png_rows(grid, bl.lowest_heights([ND, 0.5, ND], grid), 5) == [[0, 1, 0]]


def test_the_build_is_deterministic_and_its_json_records_the_pngs(built):
    first = {p.name: p.read_bytes() for p in built.glob("test-area_lowground*")}
    bl.build(built, "test-area")
    assert {p.name: p.read_bytes() for p in built.glob("test-area_lowground*")} == first
    doc = json.loads((built / "test-area_lowground.json").read_text(encoding="utf-8"))
    assert doc["levels"] == [1, 2, 3, 5] and doc["bounds"] == [100.0, 9.25, 101.5, 10.0]
    assert doc["credit"] == "Ground height: Copernicus GLO-30; rivers © OpenStreetMap contributors"
    for level, entry in doc["files"].items():
        data = (built / entry["file"]).read_bytes()
        assert entry["file"] == f"test-area_lowground_{level}m.png"
        assert (entry["bytes"], entry["sha256"]) == (len(data), hashlib.sha256(data).hexdigest())


def test_sources_keeps_its_text_and_holds_one_low_ground_part(built):
    path = built / "SOURCES.txt"
    path.write_text("Elevation crops\n\nFile:     test-area_surface.tif\n", encoding="utf-8")
    bl.build(built, "test-area")
    bl.build(built, "test-area")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("Elevation crops\n\nFile:     test-area_surface.tif\n\nLow ground map layer\n")
    assert text.count("Low ground map layer") == 1 and text.count("test-area_lowground_5m.png") == 1


# --- app/lowground.py ---

def test_the_layer_gives_its_levels_url_bounds_and_credit(built):
    assert lowground.layer("test-area") == {
        "levels": [1, 2, 3, 5], "url": "/api/areas/test-area/layers/low-ground-{level}.png",
        "bounds": [100.0, 9.25, 101.5, 10.0], "credit": bl.CREDIT}
    assert lowground.png_path("test-area", "2") == built / "test-area_lowground_2m.png"


@pytest.mark.parametrize(("area_id", "level"), [
    ("test-area", "4"), ("test-area", "02"), ("test-area", "1.0"), ("test-area", ""), ("other", "2"), ("Test-Area", "2"),
    ("../test-area", "2"), (None, "2")])
def test_an_unknown_area_or_level_has_no_picture(built, area_id, level):
    assert lowground.png_path(area_id, level) is None


def test_a_level_whose_png_is_gone_is_left_out_and_no_png_is_no_layer(built):
    (built / "test-area_lowground_3m.png").unlink()
    lowground.sets.cache_clear()
    assert lowground.layer("test-area")["levels"] == [1, 2, 5]
    for level in (1, 2, 5):
        (built / f"test-area_lowground_{level}m.png").unlink()
    lowground.sets.cache_clear()
    assert lowground.layer("test-area") is None


@pytest.mark.parametrize(("change", "words"), [
    ({"levels": [1, 4]}, "levels"), ({"levels": []}, "levels"), ({"levels": [True]}, "levels"),
    ({"bounds": [101.5, 9.25, 100.0, 10.0]}, "bounds"), ({"bounds": [1, 2, 3]}, "bounds"), ({"credit": " "}, "credit")])
def test_a_json_that_does_not_fit_costs_the_layer_and_logs_its_name(built, caplog, change, words):
    path = built / "test-area_lowground.json"
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), **change}), encoding="utf-8")
    lowground.sets.cache_clear()
    with caplog.at_level(logging.DEBUG, logger="banjir"):
        assert lowground.layer("test-area") is None and lowground.png_path("test-area", "2") is None
    assert "test-area_lowground.json" in caplog.text and words in caplog.text


def test_a_folder_without_the_files_has_no_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("BANJIR_DEM_DIR", str(tmp_path / "missing"))
    assert lowground.layer("test-area") is None


# --- the route ---

@pytest.fixture
def client(built):
    main._hits.clear()
    return TestClient(main.app)


def test_each_level_is_a_png_checked_again_on_every_load(client, built):
    for level in (1, 2, 3, 5):
        url = f"/api/areas/test-area/layers/low-ground-{level}.png"
        found = client.get(url)
        assert found.status_code == 200 and found.headers["content-type"] == "image/png"
        assert found.content == (built / f"test-area_lowground_{level}m.png").read_bytes()
        assert found.headers["cache-control"] == "no-cache"
        assert client.get(url, headers={"If-None-Match": f'W/{found.headers["etag"]}'}).status_code == 304
        head = client.head(url)
        assert head.status_code == 200 and head.content == b"" and head.headers["etag"] == found.headers["etag"]


@pytest.mark.parametrize("path", ["test-area/layers/low-ground-4.png", "test-area/layers/low-ground-02.png",
                                  "test-area/layers/low-ground-x.png", "other/layers/low-ground-2.png",
                                  "Test-Area/layers/low-ground-2.png"])
def test_an_unknown_level_or_area_is_a_404_in_the_envelope(client, path):
    for method in (client.get, client.head):
        assert method(f"/api/areas/{path}").status_code == 404
    assert client.get(f"/api/areas/{path}").json() == NO_LAYER


def test_the_route_takes_no_post(client):
    assert client.post("/api/areas/test-area/layers/low-ground-2.png").status_code == 405


# --- the area data ---

def test_the_area_details_carry_the_layer_and_others_null(city, tmp_path, monkeypatch):
    folder = write_dem(tmp_path / "dem", CITY)
    bl.build(folder, CITY)
    monkeypatch.setenv("BANJIR_DEM_DIR", str(folder))
    lowground.sets.cache_clear()
    sent = sections.details(areas.get(CITY))["layers"]["low_ground"]
    assert sent == {"levels": [1, 2, 3, 5], "url": f"/api/areas/{CITY}/layers/low-ground-{{level}}.png",
                    "bounds": [100.0, 9.25, 101.5, 10.0], "credit": bl.CREDIT}
    assert sections.city_data(areas.get(CITY))["area"]["layers"]["low_ground"] == sent
    assert sections.details(areas.get(PLAIN))["layers"]["low_ground"] is None


# --- the committed pictures ---

def test_the_committed_pngs_are_the_ones_their_json_and_sources_list():
    doc = json.loads((DEM / "shah-alam_lowground.json").read_text(encoding="utf-8"))
    sources = (DEM / "SOURCES.txt").read_text(encoding="utf-8")
    assert doc["levels"] == [1, 2, 3, 5] and sorted(p.name for p in DEM.glob("*_lowground_*m.png")) == \
        [f"shah-alam_lowground_{level}m.png" for level in (1, 2, 3, 5)]
    for entry in doc["files"].values():
        data = (DEM / entry["file"]).read_bytes()
        assert (entry["bytes"], entry["sha256"]) == (len(data), hashlib.sha256(data).hexdigest()), entry["file"]
        assert f"File:     {entry['file']}\nBytes:    {entry['bytes']}\nSHA-256:  {entry['sha256']}" in sources
        assert len(data) < 150_000, "small enough to keep in git"
    source = DEM / doc["source"]["file"]
    assert doc["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_the_committed_layer_sits_on_the_crop_s_grid(monkeypatch):
    monkeypatch.delenv("BANJIR_DEM_DIR", raising=False)
    lowground.sets.cache_clear()
    grid, _ = bl.read_heights(DEM / "shah-alam_above_river.tif")
    info, _ = read_png(DEM / "shah-alam_lowground_2m.png")
    assert (info["width"], info["height"]) == (grid.cols, grid.rows)
    found = lowground.layer("shah-alam")
    assert found["levels"] == [1, 2, 3, 5]
    assert found["bounds"] == [round(edge, 6) for edge in grid.bounds()]
