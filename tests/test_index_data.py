"""The shipped index files against tests/fixtures/index_contract.json and the plan's budgets: app/data/indexes/
shah-alam_ffpi.{tif,png,json}, SOURCES.txt, and app/data/areas/shah-alam/indexes.json. No network; the files are read
as the app reads them (app/raster.py for the tif)."""
import gzip
import hashlib
import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

from app import raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_ffpi as bf  # noqa: E402
import build_section_scores as bs  # noqa: E402
import index_inputs as ii  # noqa: E402

INDEX_DIR = ROOT / "app" / "data" / "indexes"
AREA_DIR = ROOT / "app" / "data" / "areas" / "shah-alam"
CONTRACT = json.loads((ROOT / "tests" / "fixtures" / "index_contract.json").read_text(encoding="utf-8"))
DOC = json.loads((INDEX_DIR / "shah-alam_ffpi.json").read_text(encoding="utf-8"))
INDEXES = json.loads((AREA_DIR / "indexes.json").read_text(encoding="utf-8"))
TIF, PNG = INDEX_DIR / "shah-alam_ffpi.tif", INDEX_DIR / "shah-alam_ffpi.png"
TIF_BUDGET, PNG_GZ_BUDGET = 1_300_000, 120_000
SRI_MUDA_POINT = (3.02998, 101.53667)     # the app's Sri Muda test point (lat, lon)


def test_the_contract_fixture_names_every_file():
    assert set(CONTRACT) >= {"ffpi_json", "ffpi_tif", "ffpi_png", "spot", "indexes_json", "area_json"}


def test_the_ffpi_json_has_the_contract_s_keys_and_the_tool_s_values():
    example = CONTRACT["ffpi_json"]["example"]
    assert set(DOC) == set(example) and set(DOC["method"]) == set(example["method"])
    assert DOC["classes"] == list(bf.CLASSES) and DOC["breaks"] == list(bf.BREAKS)
    assert DOC["legend"] == bf.legend() and DOC["nodata"] == -9999
    grid = ii.grid_window()
    assert DOC["grid"] == {"west": grid.west, "north": grid.north, "px": grid.px, "py": grid.py, "rows": grid.rows,
                           "cols": grid.cols}
    assert DOC["bounds"] == list(grid.bounds())
    assert DOC["png"]["index_of_class"] == {"low": 1, "medium": 2, "high": 3, "extreme": 4}


def test_the_tif_is_within_budget_and_reads_through_app_raster_on_the_json_grid():
    assert TIF.stat().st_size <= TIF_BUDGET
    crop = raster.DepthFile.open(TIF, "ffpi")
    grid = DOC["grid"]
    assert (crop.grid.rows, crop.grid.cols, crop.grid.x0, crop.grid.y0) == (grid["rows"], grid["cols"],
                                                                           grid["west"], grid["north"])
    for row in range(0, crop.grid.rows, 97):
        for col in range(0, crop.grid.cols, 13):
            value = crop.value_at(row, col, float)
            assert value == -9999 or (1 <= value <= 10 and abs(value * 10 - round(value * 10)) < 1e-4), (row, col)


def test_spot_values_stay_as_built():
    crop = raster.DepthFile.open(TIF, "ffpi")
    lat, lon = SRI_MUDA_POINT
    value = crop.value_at(*crop.grid.cell(lon, lat), float)
    assert round(value, 1) == 7.0 and bf.class_of(value) == "high"


def test_the_tif_has_no_score_outside_the_city_outline():
    """The grid is the city's box plus 2 km: its north-west corner is outside the city, so it has no score, at the
    tif and at flash_at, as the PNG shows nothing there."""
    from app import indexes
    crop = raster.DepthFile.open(TIF, "ffpi")
    assert crop.value_at(0, 0, float) == -9999 and crop.value_at(0, crop.grid.cols - 1, float) == -9999
    lat, lon = DOC["grid"]["north"] - DOC["grid"]["py"] / 2, DOC["grid"]["west"] + DOC["grid"]["px"] / 2
    assert indexes.flash_at(lat, lon) is None
    assert indexes.flash_at(*SRI_MUDA_POINT) == {"score": 7.0, "class": "high"}


def test_the_credits_name_the_ndvi_access_date_and_the_score_s_sources():
    ndvi = ("ESA WorldCover Sentinel-1 and Sentinel-2 10m Annual Composites accessed on 4 October 2026 from "
            "https://registry.opendata.aws/esa-worldcover-vito-composites")
    assert ndvi in DOC["credit"] and ndvi in (INDEX_DIR / "SOURCES.txt").read_text(encoding="utf-8")
    for name in ("README.md", "LICENSE"):
        assert ndvi in " ".join((ROOT / name).read_text(encoding="utf-8").split()), name
    assert "WorldPop" in INDEXES["method"]["score"]["credit"] and "ODbL" in INDEXES["method"]["score"]["credit"]


def png_chunks(data: bytes) -> dict:
    chunks, at = {}, 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        chunks[kind.decode()] = chunks.get(kind.decode(), b"") + data[at + 8:at + 8 + length]
        at += 12 + length
    return chunks


def test_the_png_is_within_budget_on_the_same_squares_with_the_legend_palette():
    data = PNG.read_bytes()
    assert len(gzip.compress(data, 9)) <= PNG_GZ_BUDGET
    chunks = png_chunks(data)
    width, height, depth, colour = struct.unpack(">IIBB", chunks["IHDR"][:10])
    assert (width, height, depth, colour) == (DOC["grid"]["cols"], DOC["grid"]["rows"], 4, 3)
    palette = ["#" + chunks["PLTE"][i:i + 3].hex() for i in range(3, len(chunks["PLTE"]), 3)]
    assert palette == [c["colour"] for c in DOC["legend"]] and chunks["tRNS"][0] == 0
    raw = zlib.decompress(chunks["IDAT"])
    assert len(raw) == height * (1 + -(-width // 2))


def test_sources_txt_lists_each_output_with_its_bytes_and_sha256():
    text = (INDEX_DIR / "SOURCES.txt").read_text(encoding="utf-8")
    for path in (TIF, PNG, INDEX_DIR / "shah-alam_ffpi.json"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert f"{path.name}: {path.stat().st_size} bytes, SHA-256 {digest}" in text
    assert len(re.findall(r"SHA-256 [0-9a-f]{64}", text)) >= 3 + 4


def test_indexes_json_has_the_contract_s_shape_for_every_section():
    example = CONTRACT["indexes_json"]["example"]
    assert set(INDEXES) == set(example) and set(INDEXES["validation"]) >= set(example["validation"])
    ids = [s["id"] for s in json.loads((AREA_DIR / "sections.json").read_text("utf-8"))["sections"]]
    assert list(INDEXES["sections"]) == ids
    criteria = [c["id"] for c in INDEXES["method"]["score"]["criteria"]]
    for sid, section in INDEXES["sections"].items():
        flash, score = section["flash"], section["score"]
        assert list(flash["share"]) == ["low", "medium", "high", "extreme"], sid
        assert sum(flash["share"].values()) == pytest.approx(1.0, abs=0.003), sid
        assert 1 <= flash["mean"] <= 10 and 1 <= score["value"] <= 5, sid
        assert score["class"] == bs.score_class(score["value"]) and list(score["ratings"]) == criteria, sid
        weighted = sum(INDEXES["method"]["score"]["weights_used"][k] * v for k, v in score["ratings"].items())
        assert weighted == pytest.approx(score["value"], abs=0.01), sid


def test_the_validation_is_plain_numbers_over_the_56_sections():
    checks = INDEXES["validation"]
    assert checks["n"] == 56 and "validate" in checks["wording"] and "does not" in checks["wording"]
    assert set(checks["spearman"]) == set(CONTRACT["indexes_json"]["example"]["validation"]["spearman"])
    assert all(v is None or -1 <= v <= 1 for v in checks["spearman"].values())
    assert [h["id"] for h in checks["hotspots"]] == list(bs.HOTSPOTS)
    assert all(1 <= h["score_rank"] <= 56 and 1 <= h["flash_rank"] <= 56 for h in checks["hotspots"])


def test_the_flash_flood_example_section_is_scored():
    section = INDEXES["sections"][CONTRACT["area_json"]["example"]["flash_flood_example"]]
    assert section["flash"]["mean"] == 6.3 and not math.isnan(section["score"]["value"])
