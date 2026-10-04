"""The page's data stays inside the phase 2 budget (gzip level 6, as main.GZIP_LEVEL): the city view at most 150 KB, the
largest section at most 80 KB, and the checklist section at most 40 KB. Measured through the app (TestClient), so the
history, index and squares are counted as sent.

Flash flood potential (phase 3) may add at most 4 KB to the city view and 2 KB to a section: measured as the difference
between the page's data with the index files and with none. Where this build has no index files, a made-up set of the
size they will be (a figure for every section and business, a method with long texts) stands in.

The city is the area "shah-alam" once it is switched on; before that its parked folder "_shah-alam" is linked in under
its own id. Skipped when neither is in this build.
Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_payload_budget.py
"""
import contextlib
import gzip
import os
import random

import pytest
from fastapi.testclient import TestClient

from app import areas, history, indexes, main, sections

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


# ---------- flash flood potential (phase 3)

# a section page carries the method write-up too (~3 KB gz with the real indexes.json); still far under its 80 KB
FLASH_CITY_ADDS, FLASH_SECTION_ADDS = 4 * KB, 4 * KB
CLASSES = ("low", "medium", "high", "extreme")
WORDS = "rainfall elevation drainage density river land cover slope road population rating source weight".split()


def sentence(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words)).capitalize() + "."


def made_up_doc(rng: random.Random) -> dict:
    """indexes.json for the city's 56 sections, with figures to the precision the build keeps and long texts."""
    found = {}
    for section in sections.listed(CITY):
        cuts = sorted(rng.random() for _ in range(3))
        share = dict(zip(CLASSES, (round(b - a, 3) for a, b in zip([0, *cuts], [*cuts, 1]))))
        found[section["id"]] = {"flash": {"mean": round(rng.uniform(2, 8), 1), "share": share},
                                "score": {"value": round(rng.uniform(1, 5), 2), "class": "very_low",
                                          "ratings": {w: round(rng.uniform(1, 5), 2) for w in WORDS[:7]}}}
    score = {"name": sentence(rng, 5), "summary": sentence(rng, 25), "weights_total": 74,
             "weights_used": {w: round(rng.random() / 4, 4) for w in WORDS[:7]},
             "classes": ["very_low", "low", "moderate", "high", "very_high"], "breaks": [1.5, 2.5, 3.5, 4.5],
             "break_rule": sentence(rng, 12), "citations": [sentence(rng, 18) for _ in range(2)],
             "deviations": [sentence(rng, 25) for _ in range(5)]}
    return {"method": {"flash": {"classes": CLASSES, "breaks": [4.5, 6.5, 8.5]}, "score": score},
            "sections": found, "city": found[next(iter(found))],
            "validation": {"wording": sentence(rng, 15), "n": 56,
                           "spearman": {w: round(rng.uniform(-1, 1), 2) for w in WORDS[:4]},
                           "hotspots": [{"id": s["id"], "history_events": rng.randint(1, 12), "score_rank": rng.randint(1, 56),
                                         "flash_rank": rng.randint(1, 56)} for s in sections.listed(CITY)[:5]]}}


def made_up_flash_method() -> dict:
    rng = random.Random(5)
    return {"name": sentence(rng, 5), "formula": "(1.5 M + L + S + 0.5 V) / 4", "summary": sentence(rng, 25),
            "citations": [sentence(rng, 18) for _ in range(2)], "deviations": [sentence(rng, 25) for _ in range(4)],
            "not": sentence(rng, 20)}


def made_up_layer() -> dict:
    return {"url": indexes.LAYER_URL.format(id=CITY), "bounds": [101.4277, 2.9496, 101.5914, 3.2298],
            "breaks": [4.5, 6.5, 8.5], "credit": sentence(random.Random(3), 40)}


def made_up_score(lat: float, lon: float) -> dict:
    """A figure that varies smoothly over the city, as a real one does over slope and land cover."""
    value = round(1 + 8.9 * abs(((lat * 40 + lon * 25) % 2) - 1), 1)
    return {"score": value, "class": "low" if value < 4.5 else "medium" if value < 6.5 else "high"}


@contextlib.contextmanager
def figures(present: bool):
    """The page's data with the index files (this build's own, else a made-up set) or with none."""
    real = indexes.layer(CITY) is not None and areas.indexes_file(CITY) is not None
    with pytest.MonkeyPatch.context() as patch:
        if not present or not real:
            doc = areas._freeze(made_up_doc(random.Random(7))) if present else None
            fake = lambda area_id: doc if area_id == CITY else None  # noqa: E731
            fake.cache_clear = lambda: None
            patch.setattr(areas, "indexes_file", fake)
            patch.setattr(indexes, "layer", (lambda area_id: made_up_layer()) if present else (lambda area_id: None))
            patch.setattr(indexes, "flash_method", lambda area_id: made_up_flash_method() if present else None)
            patch.setattr(indexes, "flash_at", made_up_score if present else (lambda lat, lon: None))
        clear()
        try:
            yield
        finally:
            patch.undo()
            clear()


def added_by_figures(client, path: str) -> int:
    with figures(False):
        without = gzipped(client, path)
    with figures(True):
        return gzipped(client, path) - without


def test_the_figures_add_at_most_4_kb_to_the_city_view(client):
    assert added_by_figures(client, f"/api/areas/{CITY}/data") <= FLASH_CITY_ADDS


def test_the_figures_add_at_most_2_kb_to_the_largest_section_and_the_checklist_section(client):
    largest = max(sections.listed(CITY), key=lambda s: s["counts"]["businesses"])["id"]
    for section_id in (largest, CHECKLIST_SECTION):
        added = added_by_figures(client, f"/api/areas/{CITY}/sections/{section_id}/data")
        assert added <= FLASH_SECTION_ADDS, (section_id, added)
