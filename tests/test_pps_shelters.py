"""tools/pps_shelters.py: past relief centres from pps.csv, only the ones placed with confidence drawn. No network.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_pps_shelters.py
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pps_shelters as pps  # noqa: E402

RAW = Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources")
REAL = RAW / "shah_alam" / "pps" / "pps.csv"
HEADER = "name,lat,lon,section,source_url,date_used,geocode_source,verified,note\n"
ROWS = [
    '"Hall A (listed as Big Hall A on OSM)",3.01,101.51,25,https://example.org/a,2021-12-23,osm,yes,n',
    '"School B, Seksyen 16",3.02,101.52,16,https://example.org/b; https://example.org/c,2025-04-11; 2025-11-24,osm,probable,n',
    '"Village hall C",3.03,101.53,32,https://example.org/d,2021-12-18,osm,area only,n',
    '"Mosque D, Kampung E",,,36,https://example.org/e,2021-12-23,not found,no,n',
    '"Hall F, Seksyen 35",,,35,https://example.org/f,2025-04-11,not found,no,n',
]


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "pps.csv"
    path.write_text(HEADER + "\n".join(ROWS) + "\n", encoding="utf-8")
    return path


def test_only_rows_with_a_point_verified_yes_or_probable_are_located(csv_file):
    result = pps.shelters(pps.read_rows(csv_file))
    assert [s["name"] for s in result["located"]] == ["Hall A", "School B, Seksyen 16"]
    assert result["located"][0] == {"name": "Hall A", "lat": 3.01, "lon": 101.51, "section": "seksyen-25",
                                    "verified": "yes", "date_used": "2021-12-23", "source_url": "https://example.org/a"}
    assert result["located"][1]["source_url"] == "https://example.org/b", "the first of several links"
    assert [s["name"] for s in result["not_located"]] == ["Village hall C", "Mosque D, Kampung E", "Hall F, Seksyen 35"]


def test_the_note_carries_the_label_the_months_and_names_what_is_not_shown(csv_file):
    text = pps.shelters(pps.read_rows(csv_file))["note"]
    assert "used in past floods, not an official list" in text
    assert "2 centres" in text and "1 of them by a nearly matching name" in text
    assert "December 2021, April 2025 and November 2025" in text
    assert "Village hall C (Seksyen 32), only the village is on the map" in text
    assert "Mosque D, Kampung E (Seksyen 36)" in text and "Hall F, Seksyen 35;" not in text and "Hall F, Seksyen 35." in text


def test_a_bracketed_remark_is_dropped_from_a_name():
    assert pps.clean_name("SK Kemuning 2 (listed as Sekolah Kebangsaan Bukit Kemuning 2 on OSM)") == "SK Kemuning 2"
    assert pps.clean_name("Masjid Al Falah, Kampung Budiman (Seksyen U14)") == "Masjid Al Falah, Kampung Budiman"
    assert pps.clean_name("Plain name") == "Plain name"


def test_main_writes_a_file_build_area_can_read(csv_file, tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    import build_area as ba
    out = tmp_path / "shelters.json"
    assert pps.main(["--csv", str(csv_file), "--out", str(out)]) == 0
    assert [s["name"] for s in ba.load_shelters(out)] == ["Hall A", "School B, Seksyen 16"]
    assert json.loads(out.read_text(encoding="utf-8"))["note"].startswith("Relief centres (PPS)")


@pytest.mark.skipif(not REAL.is_file(), reason="the raw PPS list is not here (set BANJIR_RAW_DIR)")
def test_the_real_list_gives_six_located_centres_and_four_named_only():
    result = pps.shelters(pps.read_rows(REAL))
    assert len(result["located"]) == 6 and len(result["not_located"]) == 4
    assert all(s["verified"] in ("yes", "probable") and s["source_url"].startswith("https://") for s in result["located"])
