"""A small made-up city split into three sections (tests/fixtures/sectioned_city/test-city), loaded through
areas.AREAS_DIR beside one real area that is not split, for the tests of sections and the endpoints that serve them.

Its word for a section ("Zone" / "Zon"), section ids, names and alias are made up, so a test passes only if the code
takes them from the data. The city lies over real ground, so points in it read the real flood model files when they are
on this machine: its business "Kedai Tiga" sits at the plan's checklist point.

    zon-1   Polygon       [101.50, 3.00] to [101.53, 3.03]                                        2 businesses
    zon-2   MultiPolygon  [101.53, 3.00] to [101.56, 3.04] and [101.54, 3.05] to [101.545, 3.055]  3 businesses
    zon-u3  Polygon       [101.50, 3.04] to [101.53, 3.06]                                        1 business
    alias "old-town" (names "Old Town", "Olde Town") -> zon-2
    history.json: 3 floods (2006 in zon-u3; 2021 in zon-2 and zon-1; 2025 in zon-2), checked by app/history.py

Squares (town.json cells): one in zon-1, one across the zon-1 / zon-2 edge, two in zon-2, one north of every section's
box and one in zon-u3.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from app import areas, history, sections

FIXTURE = Path(__file__).parent / "fixtures" / "sectioned_city"
CITY, PLAIN = "test-city", "kuantan"
CHECKLIST_POINT = (3.0297599, 101.5364982)    # in zon-2; its square's id is pt:3.02998,101.53667


def install(folder: Path) -> Path:
    """The fixture city and a link to the real plain area in folder, ready to be areas.AREAS_DIR."""
    shutil.copytree(FIXTURE / CITY, folder / CITY)
    os.symlink(areas.AREAS_DIR / PLAIN, folder / PLAIN)
    return folder


def clear() -> None:
    sections.clear_caches()
    history.load.cache_clear()


@pytest.fixture
def city(tmp_path, monkeypatch):
    """areas.AREAS_DIR pointed at the fixture city (the default) and the real plain area. Every cache is cleared before
    and after, so the next test reads the real areas again. Yields the folder."""
    folder = install(tmp_path / "areas")
    monkeypatch.setattr(areas, "AREAS_DIR", folder)
    clear()
    yield folder
    clear()
