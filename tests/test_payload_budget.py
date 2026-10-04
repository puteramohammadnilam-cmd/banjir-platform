"""The page's data stays inside the phase 2 budget (gzip level 6, as main.GZIP_LEVEL): the city view at most 150 KB, the
largest section at most 80 KB, and the checklist section at most 40 KB. Measured through the app (TestClient), so the
history, index and squares are counted as sent.

The city is the area "shah-alam" once it is switched on; before that its parked folder "_shah-alam" is linked in under
its own id. Skipped when neither is in this build.
Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_payload_budget.py
"""
import gzip
import os

import pytest
from fastapi.testclient import TestClient

from app import areas, history, main, sections

CITY = "shah-alam"
PARKED = areas.AREAS_DIR / f"_{CITY}"
CHECKLIST_SECTION = "seksyen-25"
KB = 1024
CITY_BUDGET, SECTION_BUDGET, CHECKLIST_BUDGET = 150 * KB, 80 * KB, 40 * KB


def clear() -> None:
    sections.clear_caches()
    history.load.cache_clear()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if (areas.AREAS_DIR / CITY).is_dir():
        yield TestClient(main.app)
        return
    if not PARKED.is_dir():
        pytest.skip("no city split into sections in this build")
    staged = tmp_path_factory.mktemp("areas")
    os.symlink(PARKED, staged / CITY)
    real = areas.AREAS_DIR
    areas.AREAS_DIR = staged   # the city alone: it is its own default
    clear()
    try:
        yield TestClient(main.app)
    finally:
        areas.AREAS_DIR = real
        clear()


def gzipped(client, path: str) -> int:
    response = client.get(path)
    assert response.status_code == 200, path
    return len(gzip.compress(response.content, compresslevel=main.GZIP_LEVEL))


def test_the_city_view_is_within_its_budget(client):
    assert gzipped(client, f"/api/areas/{CITY}/data") <= CITY_BUDGET


def test_every_section_is_within_its_budget_and_the_checklist_section_within_its_own(client):
    sizes = {s["id"]: gzipped(client, f"/api/areas/{CITY}/sections/{s['id']}/data") for s in sections.listed(CITY)}
    largest = max(sizes, key=sizes.get)
    assert len(sizes) == 56 and sizes[largest] <= SECTION_BUDGET, (largest, sizes[largest])
    assert sizes[CHECKLIST_SECTION] <= CHECKLIST_BUDGET
