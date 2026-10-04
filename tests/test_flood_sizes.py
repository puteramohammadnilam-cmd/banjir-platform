"""Flood sizes: 1 in 10, 20 and 50 years everywhere, and nothing left of the old 1 in 100 and 500 (plan WS-A).

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_flood_sizes.py

The server, the page, the built data and the deploy scripts must all name the same three sizes. A size the data does
not hold would show as "no water" (a depth key that is missing reads as dry), so the scan below looks for any trace of
the old sizes in code, data and scripts, not only for the constants.
"""
import json
import re
from pathlib import Path

import pytest

from app import ai, areas, floodtools, plan, raster

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
SIZES = ("10", "20", "50")
DOM_JS = ROOT / "app" / "static" / "js" / "dom.js"
PICK_JS = ROOT / "app" / "static" / "js" / "pick.js"
SCANNED = ("app", "tools")
SCANNED_SUFFIXES = {".py", ".js", ".json", ".html", ".txt", ".sh"}
DEPLOY_SCRIPTS = (ROOT / "deploy.sh", PROJECT / "deploy_vps" / "deploy_vps.sh", PROJECT / "deploy_vps" / "server_setup.sh")
OLD_SIZES = re.compile(r'RP(100|500)(?!\d)|"(100|500)":|1 in (100|500)\b|1 dalam (100|500)\b|\b(100|500)[- ]year')


def js_list(path: Path, name: str) -> list[str]:
    found = re.search(rf"export const {name} = \[([^\]]*)\]", path.read_text(encoding="utf-8"))
    return re.findall(r'"(\d+)"', found.group(1))


RESAMPLER = ROOT / "tools" / "resample_area.py"   # reads the old files on purpose, to re-sample an area built on them


def scanned_files() -> list[Path]:
    found = (p for folder in SCANNED for p in (ROOT / folder).rglob("*") if p.suffix in SCANNED_SUFFIXES and p.is_file())
    return sorted(p for p in found if "vendor" not in p.parts and p != RESAMPLER)


# ---------- one list of sizes, server and page

def test_the_server_and_the_page_name_the_same_three_flood_sizes():
    assert raster.RETURN_PERIODS == (10, 20, 50)
    assert tuple(str(rp) for rp in raster.RETURN_PERIODS) == SIZES
    assert js_list(DOM_JS, "SCENARIOS") == list(SIZES)
    assert tuple(floodtools.SCENARIOS) == SIZES
    assert plan.SCENARIOS == SIZES


def test_the_page_opens_on_the_biggest_size_shown():
    assert re.search(r'export const DEFAULT_RP = "50";', PICK_JS.read_text(encoding="utf-8"))


def test_every_area_holds_depths_for_exactly_the_three_sizes():
    for area in areas.load_all():
        town = areas.town(area.id)
        assert town["return_periods"] == [10, 20, 50], area.id
        assert all(len(cell) == 2 + len(SIZES) for cell in town["cells"]), area.id
        for p in areas.premises(area.id):
            assert tuple(p["depth_m"]) == SIZES and tuple(p["road"]["depth_m"]) == SIZES, p["id"]


def test_a_bigger_flood_never_wets_fewer_businesses_or_squares():
    for area in areas.load_all():
        shown = areas.premises(area.id)
        wet = [sum(1 for p in shown if p["depth_m"][rp]) for rp in SIZES]
        squares = [sum(1 for cell in areas.town(area.id)["cells"] if cell[2 + i]) for i in range(len(SIZES))]
        assert wet == sorted(wet) and squares == sorted(squares), area.id


# ---------- nothing of 1 in 100 or 500 is left

def test_no_code_data_or_script_names_the_old_flood_sizes():
    hits = []
    for path in [*scanned_files(), *(p for p in DEPLOY_SCRIPTS if p.is_file())]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if OLD_SIZES.search(line):
                hits.append(f"{path.relative_to(PROJECT)}:{number}: {line.strip()[:100]}")
    assert hits == []


@pytest.mark.parametrize("text", ['"100": 1.2', "ID211_N10_E100_RP500_depth.tif", "a 1 in 100 years flood",
                                  "1 dalam 500 tahun", "a 100 year flood", "the 500-year flood"])
def test_the_scan_catches_each_old_form(text):
    assert OLD_SIZES.search(text)


@pytest.mark.parametrize("text", ["ID211_N10_E100_RP50_depth.tif", "1 in 10 years", "maxlength=\"500\"",
                                  "N10_E100", "50_000_000", "1 in 50 years"])
def test_the_scan_leaves_other_numbers_alone(text):
    assert not OLD_SIZES.search(text)


def test_the_shipped_raster_list_names_only_the_three_sizes():
    listed = re.findall(r"^File:\s+(\S+)", (ROOT / "app" / "data" / "rasters" / "SOURCES.txt").read_text(), re.M)
    sizes = sorted({int(raster.FILE_NAME.match(name)["rp"]) for name in listed})
    assert sizes == [10, 20, 50] and len(listed) == 9


# ---------- what the AI is told

def test_the_chat_prompt_names_only_the_three_sizes_and_says_bigger_floods_are_not_in_the_model():
    for prompt in (ai.SYSTEM, ai.PLAN_SYSTEM):
        assert "1 in 10, 1 in 20 and 1 in 50 years" in prompt
        assert "bigger than 1 in 50 years are not in the model" in prompt
        assert not OLD_SIZES.search(prompt)


def test_the_limits_the_model_reads_say_bigger_floods_are_not_shown():
    assert "bigger than 1 in 50 years are not in the model" in floodtools.LIMITS


# ---------- the example of a bigger flood an area may give

def test_only_sri_muda_names_a_bigger_flood_and_the_data_route_sends_it():
    examples = {area.id: area.bigger_flood_example for area in areas.load_all()}
    assert examples.pop("sri-muda") == "such as December 2021"
    assert set(examples.values()) == {None}
    assert areas.details(areas.get("sri-muda"))["bigger_flood_example"] == "such as December 2021"
    assert areas.details(areas.get("kuantan"))["bigger_flood_example"] is None


@pytest.mark.parametrize("value", ["", "  ", 5, ["such as 2021"]])
def test_a_bigger_flood_example_must_be_text_or_null(tmp_path, value):
    folder = tmp_path / "test-town"
    folder.mkdir()
    config = {"id": "test-town", "default": True, "name": "T", "display_name": "T", "view": [100.0, 2.0, 100.1, 2.1],
              "zoom": 15, "ai_name": "T", "news_place": "T", "news_region": "T", "bigger_flood_example": value}
    (folder / "area.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(areas.AreaError, match="bigger_flood_example must"):
        areas.load_all(tmp_path)
