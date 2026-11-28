"""The "Next 5 days" card (app/outlook.py, GET /api/outlook): Google Weather's daily rain, MetMalaysia's forecast words
and warnings (data.gov.my), big-tide days, and the fixed rules that give each day a level. No network: Google and
data.gov.my are faked with answers shaped like the real ones of 26 Nov 2026.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_outlook.py
"""
import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import googlemaps, main, outlook, tide

MYT = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=MYT)
DATES = ["2026-11-26", "2026-11-27", "2026-11-28", "2026-11-29", "2026-11-30"]


def google_day(iso, day_mm, night_mm, day_pct=30, night_pct=40, unit="MILLIMETERS"):
    year, month, day = (int(x) for x in iso.split("-"))
    half = lambda mm, pct: {"precipitation": {"qpf": {"unit": unit, "quantity": mm}, "probability": {"type": "RAIN", "percent": pct}}}
    return {"displayDate": {"year": year, "month": month, "day": day}, "daytimeForecast": half(day_mm, day_pct),
            "nighttimeForecast": half(night_mm, night_pct)}


GOOGLE = {"forecastDays": [google_day("2026-11-26", 0.97, 5.28), google_day("2026-11-27", 12.1, 36.04, 75, 75),
                           google_day("2026-11-28", 16.36, 8.0, 75, 75), google_day("2026-11-29", 8.37, 9.0, 65, 70),
                           google_day("2026-11-30", 5.36, 1.9, 55, 55)], "timeZone": {"id": "Asia/Kuala_Lumpur"}}
RAIN = [{"date": d, "mm": mm, "chance_pct": pct} for d, mm, pct in
        zip(DATES, (6.3, 48.1, 24.4, 17.4, 7.3), (40, 75, 75, 70, 55))]
MET_ROWS = [{"location": {"location_id": "Tn070", "location_name": "Shah Alam"}, "date": d, "summary_forecast": text,
             "summary_when": when} for d, text, when in
            (("2026-11-26", "Ribut petir", "Petang dan Malam"), ("2026-11-27", "Ribut petir", "Sepanjang Hari"),
             ("2026-11-28", "Tiada Hujan", "Sepanjang Hari"), ("2026-11-29", "Hujan", "Pagi"))]


def warning(title_en, title_ms, text, start, end, heading="WARNING"):
    return {"warning_issue": {"issued": start, "title_en": title_en, "title_bm": title_ms}, "valid_from": start,
            "valid_to": end, "heading_en": heading, "heading_bm": heading, "text_en": text}


HULU_ONLY = warning("Thunderstorms Warning", "Amaran Ribut Petir",
                    "Thunderstorms, heavy rain and strong winds are expected over the states of Kedah (Kuala Muda, Sik) "
                    "• Selangor (Hulu Selangor) • Sabah: Interior (Tambunan) until 5:00 PM; Thursday, 26 November 2026.",
                    "2026-11-26T14:00:00", "2026-11-26T17:00:00")
SEA = warning("Strong Winds and Rough Seas Warning", "Amaran Angin Kencang dan Laut Bergelora",
              "THUNDERSTORMS WARNING Thunderstorms, heavy rain and strong winds are expected over the waters of Perak "
              "• Selangor • Pahang until 6:00 PM", "2026-11-23T00:00:00", "2026-11-28T23:59:59")
PETALING = warning("Thunderstorms Warning", "Amaran Ribut Petir",
                   "Thunderstorms, heavy rain and strong winds are expected over the states of Selangor (Petaling, Klang "
                   "and Kuala Langat) • Johor (Muar) until 9:00 PM; Saturday, 28 November 2026.",
                   "2026-11-28T15:00:00", "2026-11-28T21:00:00")
STATE_WIDE = warning("Continuous Rain Warning", "Amaran Hujan Berterusan",
                     "Continuous rain is expected to occur over the states of Kelantan (Pasir Puteh, Kota Bharu) • "
                     "Terengganu until Sunday, 29 November 2026.", "2026-11-26T00:00:00", "2026-11-29T23:59:59",
                     "CONTINUOUS RAIN WARNING (ALERT)")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    outlook._cache.clear()
    main._hits.clear()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")


def met(monkeypatch, rows=MET_ROWS, warnings=(HULU_ONLY, SEA, PETALING, STATE_WIDE)):
    monkeypatch.setattr(outlook, "_fetch_forecast", lambda location_id: [r for r in rows if r["location"]["location_id"].startswith(location_id)])
    monkeypatch.setattr(outlook, "_fetch_warnings", lambda: list(warnings))


# ---------- Google Weather daily rain

def test_rain_days_adds_day_and_night_and_keeps_the_higher_chance(monkeypatch):
    seen = {}
    monkeypatch.setattr(googlemaps, "_get", lambda url, params, headers: seen.update(url=url, params=params) or GOOGLE)
    days = googlemaps.rain_days(3.07, 101.52, 5)
    assert seen["url"] == googlemaps.DAYS and seen["params"]["days"] == 5 and "key" not in seen["params"]
    assert days[1] == {"date": "2026-11-27", "mm": 48.1, "chance_pct": 75}
    assert [d["date"] for d in days] == DATES


def test_rain_days_is_counted_in_the_free_cap_and_an_empty_answer_is_an_error(monkeypatch):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "1")
    monkeypatch.setattr(googlemaps, "_get", lambda url, params, headers: {"forecastDays": []})
    with pytest.raises(googlemaps.UpstreamError):
        googlemaps.rain_days(3.07, 101.52, 5)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_days(3.07, 101.52, 5)


def test_rain_days_converts_inches_and_skips_a_day_without_a_date(monkeypatch):
    broken = {**google_day("2026-11-27", 1, 1), "displayDate": {"year": 2026}}
    monkeypatch.setattr(googlemaps, "_get", lambda *a: {"forecastDays": [google_day("2026-11-26", 0.1, 0.1, unit="INCHES"), broken]})
    assert googlemaps.rain_days(3.07, 101.52, 5) == [{"date": "2026-11-26", "mm": 5.1, "chance_pct": 40}]


# ---------- MetMalaysia warnings: which ones cover the area

@pytest.mark.parametrize("text, covered", [
    (HULU_ONLY["text_en"], False),          # Selangor, but only Hulu Selangor
    (PETALING["text_en"], True),            # a district of the area is listed
    (STATE_WIDE["text_en"], False),         # other states
    ("Continuous rain is expected over the states of Selangor until Sunday, 29 November 2026.", True),   # the whole state
    ("Heavy rain is expected over the states of Selangor (Hulu Langat) • Klang Valley", False),
    ("Continuous rain is expected over the states of Selangor and Johor until Sunday.", True),   # whole state, "and"
    ("Continuous rain is expected over the states of Johor and Selangor until Sunday.", True),
    ("Thunderstorms are expected over the states of Selangor (Hulu Selangor and Sepang) and Johor until 5 PM.", False),
])
def test_a_warning_covers_the_area_only_for_its_state_whole_or_one_of_its_districts(text, covered):
    assert outlook.covers(text, "Selangor", ("Petaling", "Klang", "Shah Alam")) is covered


def test_only_rain_and_thunderstorm_warnings_on_land_are_kept(monkeypatch):
    met(monkeypatch)
    kept = outlook.warnings_for("shah-alam", NOW)
    assert [w["title_en"] for w in kept] == ["Thunderstorms Warning"] and kept[0]["valid_from"] == "2026-11-28T15:00:00"
    assert kept[0]["kind"] == "thunderstorm"
    found = outlook.warnings_for("kuala-terengganu", NOW)[0]
    assert found["heading_en"] == "CONTINUOUS RAIN WARNING (ALERT)" and found["kind"] == "rain"


def test_ended_warnings_are_dropped_before_the_list_is_cut(monkeypatch):
    old = [warning("Thunderstorms Warning", "Amaran Ribut Petir", "Thunderstorms over the states of Selangor (Petaling).",
                   f"2026-11-2{d}T14:00:00", f"2026-11-2{d}T17:00:00") for d in (3, 4, 5)]
    met(monkeypatch, warnings=(*old, PETALING))
    assert [w["valid_from"] for w in outlook.warnings_for("shah-alam", NOW)] == ["2026-11-28T15:00:00"]
    met(monkeypatch, warnings=(PETALING,))
    assert outlook.warnings_for("shah-alam", datetime(2026, 11, 28, 21, 0, tzinfo=MYT)) == [], "ended at 9 pm"


def test_a_warning_ending_at_midnight_does_not_mark_the_next_day():
    ends = [{"valid_from": "2026-11-28T15:00:00", "valid_to": "2026-11-29T00:00:00"}]
    assert outlook._covers_day("2026-11-28", ends) and not outlook._covers_day("2026-11-29", ends)


def test_no_metmalaysia_answer_is_none_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(outlook, "_cached", lambda key, fetch, clock: None)
    assert outlook.warnings_for("shah-alam", NOW) is None and outlook.forecast_for("shah-alam") is None


# ---------- the rules

@pytest.mark.parametrize("mm, warned, level", [   # warned: a continuous-rain warning covers the day
    (0, False, "low"), (19.9, False, "low"), (20, False, "watch"), (29.9, False, "watch"), (30, False, "high"),
    (5, True, "high"), (None, True, "high"), (None, False, None),
])
def test_each_day_gets_its_level_from_the_rain_and_any_warning(mm, warned, level):
    assert outlook.level(mm, warned) == level


@pytest.mark.parametrize("levels, trend", [
    (["low", "high", "low", "low", "low"], "rising"), (["high", "low", "low", "low", "low"], "easing"),
    (["watch", "watch", "low", "low", "low"], "steady"), (["low", None, "low", "low", "low"], None),
])
def test_the_trend_compares_today_with_the_days_ahead(levels, trend):
    assert outlook.trend(levels) == trend


def test_the_thresholds_are_the_ones_the_past_floods_gave():
    assert (outlook.WATCH_MM, outlook.HIGH_MM, outlook.DAYS) == (20, 30, 5)
    assert outlook.CALIBRATION == {"since": 2024, "floods": 10, "watch_days": 79, "watch_floods": 8, "high_days": 28,
                                   "high_floods": 5}


# ---------- the whole answer

def big_tide_day():
    ranges, big = tide.day_ranges("shah-alam"), tide.doc("shah-alam")["big_range_m"]
    return {day for day, r in ranges.items() if r >= big}


def test_build_gives_five_days_with_rain_words_warnings_and_tides(monkeypatch):
    met(monkeypatch)
    found = outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=lambda lat, lon, days: RAIN)
    days = found["days"]
    assert [d["date"] for d in days] == DATES
    # the 28th: a thunderstorm warning for Petaling is shown on the day but does not set its level (not calibrated)
    assert [d["level"] for d in days] == ["low", "high", "watch", "low", "low"]
    assert days[2]["warned"] and not days[3]["warned"] and days[1]["rain_mm"] == 48.1 and days[1]["chance_pct"] == 75
    assert days[0]["met"] == {"text": "Ribut petir", "when": "Petang dan Malam"} and days[4]["met"] is None
    assert [d["big_tide"] for d in days] == [d["date"] in big_tide_day() for d in days]
    assert found["trend"] == "rising" and found["rain"] == "ok" and found["met_place"] == "Shah Alam"
    assert found["levels"] is True and found["met"] == "ok"
    assert found["thresholds"] == {"watch_mm": 20, "high_mm": 30, "set_from": "Shah Alam", **outlook.CALIBRATION}
    assert [w["title_en"] for w in found["warnings"]] == ["Thunderstorms Warning"]


def test_without_googles_rain_the_card_still_gives_words_warnings_and_tides(monkeypatch):
    met(monkeypatch)
    for error, state in ((googlemaps.FreeLimitReached("cap"), "capped"), (googlemaps.NotConfigured("no key"), "off"),
                         (googlemaps.UpstreamError("HTTP 503"), "down")):
        def fail(lat, lon, days, e=error):
            raise e
        found = outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=fail)
        assert found["rain"] == state and found["trend"] is None
        assert [d["level"] for d in found["days"]] == [None] * 5 and found["days"][2]["warned"]
        assert all(d["rain_mm"] is None for d in found["days"]) and found["days"][1]["met"]["text"] == "Ribut petir"


def test_a_continuous_rain_warning_sets_the_day_high_even_with_little_rain(monkeypatch):
    rain = warning("Continuous Rain Warning", "Amaran Hujan Berterusan", "Continuous rain is expected over the states of "
                   "Selangor (Petaling and Klang) until Friday, 27 November 2026.", "2026-11-26T00:00:00", "2026-11-27T23:59:59")
    met(monkeypatch, warnings=(rain,))
    days = outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=lambda *a: RAIN)["days"]
    assert [d["level"] for d in days[:3]] == ["high", "high", "watch"]


def test_levels_are_given_only_where_past_floods_set_them(monkeypatch):
    met(monkeypatch)
    found = outlook.build("kuantan", 3.8, 103.3, now=NOW, rain_fn=lambda *a: RAIN)
    assert found["levels"] is False and found["trend"] is None
    assert all(d["level"] is None for d in found["days"]) and found["days"][1]["rain_mm"] == 48.1


def test_six_days_are_asked_so_the_fifth_is_there_before_7_am(monkeypatch):
    met(monkeypatch)
    asked = {}
    early = datetime(2026, 11, 27, 2, 0, tzinfo=MYT)   # Google's first day may still be the 26th (07:00 to 07:00)
    google = [{"date": d, "mm": 5.0, "chance_pct": 40} for d in ["2026-11-26", *DATES[1:], "2026-12-01"]]
    found = outlook.build("shah-alam", 3.07, 101.52, now=early, rain_fn=lambda lat, lon, days: asked.update(days=days) or google)
    assert asked["days"] == 6 and [d["date"] for d in found["days"]][0] == "2026-11-27"
    assert all(d["rain_mm"] == 5.0 for d in found["days"]) and found["trend"] == "steady"


def test_a_metmalaysia_outage_is_said_not_shown_as_no_warning(monkeypatch):
    monkeypatch.setattr(outlook, "_cached", lambda key, fetch, clock: None)
    found = outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=lambda *a: RAIN)
    assert found["met"] == "down" and found["warnings"] == [] and found["levels"] is True


def test_an_area_without_a_metmalaysia_place_or_tide_table_still_answers(monkeypatch):
    met(monkeypatch)
    monkeypatch.setattr(outlook, "place", lambda area_id, section_id=None: None)
    found = outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=lambda *a: RAIN)
    assert found["met_place"] is None and found["warnings"] == [] and all(d["met"] is None for d in found["days"])
    assert found["met"] == "none"


# ---------- data.gov.my, kept for everyone

def test_metmalaysia_is_asked_once_an_hour_for_everyone_and_kept_through_a_failure(monkeypatch, caplog):
    calls, answers = [], [MET_ROWS, outlook.FeedError("timeout"), outlook.FeedError("timeout"), MET_ROWS]

    def fetch(location_id):
        calls.append(1)
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(outlook, "_fetch_forecast", fetch)
    clock = [0.0]
    get = lambda: outlook.forecast_for("shah-alam", clock=lambda: clock[0])
    assert get()["2026-11-26"]["text"] == "Ribut petir"
    clock[0] = outlook.CACHE_S - 1
    get()
    assert len(calls) == 1
    clock[0] = outlook.CACHE_S
    assert get()["2026-11-27"]["text"] == "Ribut petir", "the last good answer is kept through a failure"
    clock[0] += outlook.RETRY_S - 1
    get()
    assert len(calls) == 2, "not asked again within RETRY_S"
    clock[0] += 1
    get()
    assert len(calls) == 3 and caplog.text.count("MetMalaysia") == 1, "one log line per outage"
    clock[0] = outlook.CACHE_S + outlook.STALE_S + 1
    assert get() is not None and len(calls) == 4


def test_a_metmalaysia_answer_that_is_not_a_list_is_a_feed_error(monkeypatch):
    class Answer:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def geturl(self):
            return outlook.FORECAST

        def read(self, size=-1):
            body, self.body = self.body, b""
            return body

    monkeypatch.setattr(outlook.urllib.request, "urlopen", lambda request, timeout: Answer(b'{"error": "rate limited"}'))
    with pytest.raises(outlook.FeedError):
        outlook._get_list(outlook.FORECAST, {"filter": "Tn070@location__location_id"})


def test_metmalaysia_words_are_kept_short_and_plain():
    rows = [{**MET_ROWS[0], "summary_forecast": "Ribut  petir\n" + "x" * 200, "summary_when": None}]
    assert outlook.parse_forecast(rows, "Tn070")["2026-11-26"] == {"text": ("Ribut petir " + "x" * 200)[:80], "when": ""}
    assert outlook.parse_forecast([{"date": "2026-11-26"}, "junk"], "Tn070") == {}


# ---------- the endpoint

def test_the_endpoint_answers_for_an_area_and_a_section(monkeypatch):
    met(monkeypatch)
    monkeypatch.setattr(googlemaps, "rain_days", lambda lat, lon, days: RAIN)
    client = TestClient(main.app)
    found = client.get("/api/outlook?area=shah-alam").json()
    assert found["success"] and len(found["data"]["outlook"]["days"]) == 5
    assert client.get("/api/outlook?area=shah-alam&section=seksyen-25").json()["success"]
    assert client.get("/api/outlook?area=nowhere").status_code == 404
    assert "no-store" in client.get("/api/outlook?area=shah-alam").headers.get("cache-control", "")
    assert not math.isnan(found["data"]["outlook"]["days"][0]["rain_mm"])


def test_a_whole_state_s_weather_is_asked_at_its_main_town_and_says_so(monkeypatch):
    from app import areas
    met(monkeypatch)
    asked = []
    monkeypatch.setattr(googlemaps, "rain_days", lambda lat, lon, days: asked.append((lat, lon)) or RAIN)
    client = TestClient(main.app)
    state = client.get("/api/outlook?area=johor").json()["data"]["outlook"]
    district = client.get("/api/outlook?area=johor&section=muar").json()["data"]["outlook"]
    city = client.get("/api/outlook?area=shah-alam").json()["data"]["outlook"]
    assert (state["at"], district["at"], city["at"]) == ("Johor Bahru", None, None)
    johor = areas.get("johor")
    lon, lat = johor.weather_at["point"]
    assert asked[0] == (lat, lon) == johor.centre() and johor.contains(lat, lon)
    assert areas.get("shah-alam").weather_at is None


def test_every_area_and_every_district_of_a_state_has_a_metmalaysia_place_that_fits():
    from app import areas, sections
    for area in areas.load_all():
        found = outlook.place(area.id)
        assert found and found[2] and found[3], area.id
        parts = areas._read(area.id, outlook.MET_FILE).get("sections") or {}
        if not parts:
            assert found[0][:2] in ("Tn", "Ds"), area.id
            continue
        assert found[:2] == (None, None), "a whole state has no one place, only its districts' warnings"
        assert set(parts) == {s["id"] for s in sections.listed(area.id)}, "one place per district, and no other"
        for section_id in parts:
            own = outlook.place(area.id, section_id)
            assert own[0][:2] == "Ds" and own[1] and own[3] and set(own[3]) <= set(found[3]), section_id


JOHOR_ROWS = [{"location": {"location_id": "Ds083", "location_name": "Muar"}, "date": "2026-11-28",
               "summary_forecast": "Ribut petir", "summary_when": "Petang"}]


def test_a_states_district_gets_its_own_forecast_and_only_warnings_naming_it(monkeypatch):
    met(monkeypatch, rows=JOHOR_ROWS)   # PETALING names "Johor (Muar)"
    muar = outlook.build("johor", 2.04, 102.57, now=NOW, rain_fn=lambda *a: RAIN, section_id="muar")
    assert muar["met"] == "ok" and muar["met_place"] == "Muar" and muar["days"][2]["met"]["text"] == "Ribut petir"
    assert [w["title_en"] for w in muar["warnings"]] == ["Thunderstorms Warning"]
    tinggi = outlook.build("johor", 1.73, 103.9, now=NOW, rain_fn=lambda *a: RAIN, section_id="kota-tinggi")
    assert tinggi["met_place"] == "Kota Tinggi" and tinggi["warnings"] == [], "a warning for Muar does not cover Kota Tinggi"
    state = outlook.build("johor", 2.05, 103.5, now=NOW, rain_fn=lambda *a: RAIN)
    assert state["met"] == "ok" and state["met_place"] is None and all(d["met"] is None for d in state["days"])
    assert [w["title_en"] for w in state["warnings"]] == ["Thunderstorms Warning"], "the whole state: any district's"


def test_the_outlook_endpoint_asks_a_districts_own_place(monkeypatch):
    met(monkeypatch, rows=JOHOR_ROWS)
    monkeypatch.setattr(outlook.googlemaps, "rain_days", lambda lat, lon, days: RAIN)
    found = TestClient(main.app).get("/api/outlook?area=johor&section=muar").json()["data"]["outlook"]
    assert found["met_place"] == "Muar"
    assert TestClient(main.app).get("/api/outlook?area=kota-tinggi").json()["data"]["outlook"]["met_place"] == "Kota Tinggi", \
        "the old town area's id is its district"


def test_the_arus_link_is_there_only_when_set_and_https(monkeypatch):
    met(monkeypatch)
    build = lambda: outlook.build("shah-alam", 3.07, 101.52, now=NOW, rain_fn=lambda *a: RAIN)
    monkeypatch.delenv("ARUS_URL", raising=False)
    assert build()["arus"] is None
    monkeypatch.setenv("ARUS_URL", "https://arus.example/map?lat={lat}&lon={lon}")
    assert build()["arus"] == "https://arus.example/map?lat=3.07000&lon=101.52000"
    for bad in ("http://arus.example/", "https://arus.example/{city}", "javascript:alert(1)"):
        monkeypatch.setenv("ARUS_URL", bad)
        assert build()["arus"] is None, bad


def test_every_district_s_words_come_from_one_request_and_a_town_s_from_its_own(monkeypatch):
    asked = []
    rows = [{"location": {"location_id": loc}, "date": "2026-11-26", "summary_forecast": f"Hujan di {loc}",
             "summary_when": ""} for loc in ("Ds083", "Ds084", "Ds090", "Tn070")]
    monkeypatch.setattr(outlook, "_get_list", lambda url, params: asked.append(params) or [
        r for r in rows if r["location"]["location_id"].startswith(params.get("contains", params.get("filter", "")).split("@")[0])])
    monkeypatch.setattr(outlook, "_cache", {})
    clock = lambda: 0.0  # noqa: E731
    assert outlook.forecast_for("johor", clock, "muar")["2026-11-26"]["text"] == "Hujan di Ds083"
    assert outlook.forecast_for("johor", clock, "batu-pahat")["2026-11-26"]["text"] == "Hujan di Ds084"
    assert outlook.forecast_for("johor", clock, "johor-bahru")["2026-11-26"]["text"] == "Hujan di Ds090"
    assert outlook.forecast_for("shah-alam", clock)["2026-11-26"]["text"] == "Hujan di Tn070"
    assert asked == [{"contains": "Ds@location__location_id", "limit": outlook.ALL_LIMIT},
                     {"filter": "Tn070@location__location_id", "limit": "10"}]


def test_a_district_answer_cut_at_the_limit_is_a_failure_and_kept_rows_are_small(monkeypatch):
    row = {"location": {"location_id": "Ds083", "location_name": "Muar"}, "date": "2026-11-26",
           "summary_forecast": "Hujan", "summary_when": "Petang", "min_temp": 24, "max_temp": 33}
    monkeypatch.setattr(outlook, "_get_list", lambda url, params: [row] * int(outlook.ALL_LIMIT))
    with pytest.raises(outlook.FeedError, match="raise ALL_LIMIT"):
        outlook._fetch_forecast(outlook.ALL_DISTRICTS)
    monkeypatch.setattr(outlook, "_get_list", lambda url, params: [row, "junk"])
    kept = outlook._fetch_forecast(outlook.ALL_DISTRICTS)
    assert kept == [{"location": {"location_id": "Ds083"}, "date": "2026-11-26", "summary_forecast": "Hujan",
                     "summary_when": "Petang"}]
    assert outlook.parse_forecast(kept, "Ds083") == {"2026-11-26": {"text": "Hujan", "when": "Petang"}}
    assert outlook.FORECAST.endswith("/") and outlook.WARNINGS.endswith("/"), "no 301 first"
