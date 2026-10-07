"""Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_tide.py"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import areas, main, tide

CITY = "shah-alam"
BUILT = json.loads((Path(__file__).resolve().parents[1] / "app/data/areas" / CITY / "tide.json").read_text())


@pytest.fixture
def fresh():
    tide.doc.cache_clear()
    yield
    tide.doc.cache_clear()


def test_the_built_table_covers_2026_and_2027_with_about_four_turns_a_day_alternating():
    turns = BUILT["turns"]
    assert turns[0][0].startswith("2026-01-01") and turns[-1][0].startswith("2027-12-31")
    assert 3.7 < len(turns) / 730 < 4.0
    assert all(a[1] != b[1] for a, b in zip(turns, turns[1:])), "highs and lows take turns"
    assert all(t[2] > 0 for t in turns if t[1] == "high") and all(t[2] < 0 for t in turns if t[1] == "low")
    assert BUILT["station"] and 2 < BUILT["big_range_m"] < 6


def test_today_is_read_in_malaysian_time_with_the_next_high_from_now():
    morning = tide.today(CITY, datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc))      # 09:00 in Malaysia
    assert (morning["date"], morning["highs"], morning["lows"]) == ("2026-10-07", ["03:18", "15:48"], ["09:54", "22:06"])
    assert morning["next_high"] == {"time": "15:48", "tomorrow": False}
    night = tide.today(CITY, datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc))         # 23:00
    assert night["next_high"] == {"time": "04:12", "tomorrow": True}
    late_utc = tide.today(CITY, datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc))      # 01:00 on the 7th in Malaysia
    assert late_utc["date"] == "2026-10-07"


def test_a_big_tide_is_a_day_whose_range_reaches_the_table_s_threshold():
    days = {}
    for when, _, height in BUILT["turns"]:
        days.setdefault(when[:10], []).append(height)
    big_day = next(d for d, h in days.items() if max(h) - min(h) >= BUILT["big_range_m"])
    small_day = next(d for d, h in days.items() if max(h) - min(h) < BUILT["big_range_m"])
    noon = lambda d: datetime.fromisoformat(d + "T04:00:00+00:00")   # noqa: E731  12:00 in Malaysia
    assert tide.today(CITY, noon(big_day))["big"] is True
    assert tide.today(CITY, noon(small_day))["big"] is False


def test_no_tide_outside_the_table_or_for_an_area_without_one():
    assert tide.today(CITY, datetime(2030, 1, 1, tzinfo=timezone.utc)) is None
    plain = next(a for a in areas.load_all() if a.id != CITY)
    assert tide.today(plain.id) is None


@pytest.mark.parametrize("change", [
    lambda d: d.update(turns=[]),
    lambda d: d["turns"].reverse(),                         # not in time order
    lambda d: d["turns"][0].__setitem__(1, "middle"),
    lambda d: d.pop("station"),
])
def test_a_tide_table_that_does_not_fit_stops_the_server_naming_the_area(monkeypatch, fresh, change):
    doc = json.loads(json.dumps(BUILT))
    change(doc)
    real = areas._read
    monkeypatch.setattr(areas, "_read", lambda area_id, name: doc if name == tide.TIDE_FILE else real(area_id, name))
    with pytest.raises(areas.AreaError, match=f"{CITY}: tide.json"):
        tide.doc(CITY)


def test_the_endpoint_answers_for_the_area_and_null_elsewhere():
    main._hits.clear()
    client = TestClient(main.app)
    found = client.get(f"/api/tide?area={CITY}&section=seksyen-25").json()["data"]["tide"]
    assert found["station"] == BUILT["station"] and found["highs"]
    plain = next(a for a in areas.load_all() if a.id != CITY)
    assert client.get(f"/api/tide?area={plain.id}").json()["data"]["tide"] is None
    assert client.get("/api/tide?area=nope").status_code == 404
