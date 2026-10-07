"""Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_gauges.py"""
import json
from datetime import datetime, timezone

import pytest

from app import areas, gauges, tide

RESTAURANT = (3.0297599, 101.5364982)   # a mapped business beside the Sg. Klang gauge


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A gauge list of our own: an older station and an "(F2)" one 100 m apart, and one far away."""
    def use(rows):
        path = tmp_path / "gauges.json"
        path.write_text(json.dumps({"version": 1, "gauges": rows}))
        monkeypatch.setattr(gauges, "GAUGES_FILE", path)
        gauges.listed.cache_clear()
    yield use
    gauges.listed.cache_clear()


def test_the_nearest_gauge_has_its_id_name_river_and_distance():
    found = gauges.nearest(*RESTAURANT)
    assert set(found) == {"id", "name", "river", "distance_m"}
    assert gauges.ID.fullmatch(found["id"]) and found["name"] and 0 < found["distance_m"] < 10_000


def test_an_older_station_at_the_same_site_is_preferred_to_an_f2_one(fake):
    fake([{"id": "NEW", "name": "Sg. A (F2)", "river": "Sg. A", "lat": 3.0, "lon": 101.5},
          {"id": "OLD", "name": "Sg. A", "river": "Sg. A", "lat": 3.0009, "lon": 101.5}])   # about 100 m north
    assert gauges.nearest(3.0, 101.5)["id"] == "OLD"


def test_an_f2_station_is_kept_when_the_older_one_is_not_at_the_same_site(fake):
    fake([{"id": "NEW", "name": "Sg. A (F2)", "river": "Sg. A", "lat": 3.0, "lon": 101.5},
          {"id": "OLD", "name": "Sg. B", "river": "Sg. B", "lat": 3.01, "lon": 101.5}])     # about 1.1 km north
    assert gauges.nearest(3.0, 101.5)["id"] == "NEW"


def test_no_gauge_beyond_ten_km(fake):
    fake([{"id": "FAR", "name": "Sg. C", "river": "", "lat": 3.2, "lon": 101.5}])          # about 22 km
    assert gauges.nearest(3.0, 101.5) is None


@pytest.mark.parametrize("bad", [
    {"id": "X", "name": "", "lat": 3.0, "lon": 101.5},
    {"id": "X&next=1", "name": "Sg. A", "lat": 3.0, "lon": 101.5},     # an id that would change the link's query
    {"id": "X", "name": "<b>Sg. A</b>", "lat": 3.0, "lon": 101.5},
    {"id": "X", "name": "Sg. A", "lat": "3.0", "lon": 101.5},
])
def test_a_bad_list_is_an_error_not_a_silent_gap(fake, bad):
    fake([bad])
    with pytest.raises(ValueError, match="gauges.json"):
        gauges.nearest(3.0, 101.5)


def test_a_real_name_with_an_apostrophe_and_an_id_with_a_space_are_fine(fake):
    fake([{"id": "SG MUAR", "name": "Kg. Ma'ang", "river": "Sg. Muar", "lat": 3.0, "lon": 101.5}])
    assert gauges.nearest(3.0, 101.5)["id"] == "SG MUAR"


def test_every_mapped_business_carries_its_gauge():
    for area in areas.load_all():
        assert all("gauge" in p for p in areas.premises(area.id))


def test_the_tide_outlook_gives_the_next_run_of_big_tides_or_until_when():
    ahead = tide.today("shah-alam", datetime(2026, 10, 7, 4, tzinfo=timezone.utc))
    assert ahead["next_big"] == {"from": "2026-10-09", "to": "2026-10-13"}
    during = tide.today("shah-alam", datetime(2026, 10, 10, 4, tzinfo=timezone.utc))
    assert during["next_big"]["from"] == during["date"] and during["big"] is True
