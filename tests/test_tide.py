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
    for cached in (tide.doc, tide.gauges, tide.day_ranges):
        cached.cache_clear()
    yield
    for cached in (tide.doc, tide.gauges, tide.day_ranges):
        cached.cache_clear()


def test_the_built_table_covers_2026_and_2027_with_about_four_turns_a_day_alternating():
    turns = BUILT["turns"]
    assert turns[0][0].startswith("2026-01-01") and turns[-1][0].startswith("2027-12-31")
    assert 3.7 < len(turns) / 730 < 4.0
    assert all(a[1] != b[1] for a, b in zip(turns, turns[1:])), "highs and lows take turns"
    assert all(t[2] > 0 for t in turns if t[1] == "high") and all(t[2] < 0 for t in turns if t[1] == "low")
    assert BUILT["station"] and 2 < BUILT["big_range_m"] < 6


def test_today_is_read_in_malaysian_time_with_the_next_high_from_now():
    morning = tide.today(CITY, datetime(2026, 10, 7, 1, 0, tzinfo=timezone.utc))      # 09:00 in Malaysia
    assert (morning["date"], morning["highs"], morning["lows"]) == ("2026-10-07", ["03:20", "15:50"], ["09:55", "22:05"])
    assert morning["next_high"] == {"time": "15:50", "tomorrow": False}
    night = tide.today(CITY, datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc))         # 23:00
    assert night["next_high"] == {"time": "04:10", "tomorrow": True}
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


@pytest.mark.parametrize("clock, rounded", [("03:18", "03:20"), ("15:48", "15:50"), ("12:32", "12:30"),
                                             ("00:02", "00:00"), ("23:58", "23:55")])
def test_times_are_shown_to_five_minutes_and_stay_on_their_day(clock, rounded):
    assert tide.shown(clock) == rounded


def test_the_last_day_of_the_table_has_its_tides_but_no_next_high():
    last = tide.today(CITY, datetime(2027, 12, 31, 15, 30, tzinfo=timezone.utc))   # 23:30 on 31 Dec 2027
    assert last["highs"] and last["next_high"] is None


def test_a_warning_comes_when_the_table_is_about_to_run_out(caplog):
    tide.check(CITY, datetime(2027, 12, 1, tzinfo=timezone.utc))
    assert "rebuild it with tools/build_tide.py" in caplog.text
    caplog.clear()
    tide.check(CITY, datetime(2026, 10, 7, tzinfo=timezone.utc))
    assert caplog.text == ""


def test_no_tide_outside_the_table_or_for_an_area_without_one():
    assert tide.today(CITY, datetime(2030, 1, 1, tzinfo=timezone.utc)) is None
    plain = next(a for a in areas.load_all() if a.id != CITY)
    assert tide.today(plain.id) is None


@pytest.mark.parametrize("change", [
    lambda d: d.update(turns=[]),
    lambda d: d["turns"].reverse(),                         # not in time order
    lambda d: d["turns"][0].__setitem__(1, "middle"),
    lambda d: d.pop("station"),
    lambda d: d.pop("typical_error_m"),
    lambda d: d.update(big_range_m=0),
    lambda d: d["turns"][1].__setitem__(1, d["turns"][0][1]),   # two highs (or lows) in a row
    lambda d: d["turns"][0].__setitem__(0, "2026-13-45T99:99"),
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


STATE = "johor"
COASTAL = {"tangkak", "muar", "batu-pahat", "pontian", "johor-bahru", "kota-tinggi", "mersing"}


def test_each_coastal_district_of_a_state_has_its_gauges_tide_and_how_far_it_is():
    from app import sections
    listed = tide.gauges(STATE)
    assert set(listed) == COASTAL and COASTAL < {s["id"] for s in sections.listed(STATE)}
    tide.check(STATE)   # every gauge file there and well formed
    when = datetime(2026, 12, 1, 1, 0, tzinfo=timezone.utc)
    for section_id in COASTAL:
        found = tide.today(STATE, when, section_id)
        assert found["highs"] and found["km"] == listed[section_id]["km"] and 0 < found["typical_error_m"] < 0.2, section_id
    assert tide.today(STATE, when, "muar")["station"] == "Keling" and tide.today(STATE, when, "johor-bahru")["km"] == 3
    for nowhere in ("kluang", "kulai", "segamat", None):   # no coast, and no one tide for the whole state
        assert tide.today(STATE, when, nowhere) is None, nowhere
    assert tide.today(CITY, when)["km"] is None and tide.today(CITY, when, "seksyen-25")["station"] == BUILT["station"]


def test_a_districts_gauge_list_that_does_not_fit_stops_the_server(monkeypatch, fresh):
    real = areas._read
    monkeypatch.setattr(areas, "_read", lambda area_id, name: {"sections": {"muar": {"gauge": "keling"}}}
                        if name == tide.SECTIONS_FILE else real(area_id, name))
    with pytest.raises(areas.AreaError, match="tide/sections.json"):
        tide.gauges(STATE)


def test_a_gauge_named_with_no_tide_file_stops_the_server(monkeypatch, fresh):
    real = areas._read
    monkeypatch.setattr(areas, "_read", lambda area_id, name: {"sections": {"muar": {"gauge": "nowhere", "km": 5}}}
                        if name == tide.SECTIONS_FILE else real(area_id, name))
    with pytest.raises(areas.AreaError, match="no tide file for muar"):
        tide.check(STATE)


def test_the_endpoint_answers_for_a_states_coastal_district():
    main._hits.clear()
    client = TestClient(main.app)
    found = client.get(f"/api/tide?area={STATE}&section=muar").json()["data"]["tide"]
    assert (found["station"], found["km"]) == ("Keling", 50)
    assert client.get(f"/api/tide?area={STATE}&section=kluang").json()["data"]["tide"] is None
    assert client.get("/api/tide?area=kota-tinggi").json()["data"]["tide"]["station"] == "Sedili", "the old town id: its district"
