"""The monthly cap on Google Maps Platform calls (app/googlemaps.py): calls stop before Google's free allowance is used
up, so the site cannot run up a bill; the count survives a restart; a new month (US Pacific, as Google bills) starts
from 0. No network: every HTTP call is faked.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_maps_budget.py
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import floodtools, googlemaps, main
from test_google import KNOWN, hour

HERE = (3.03, 101.54)


@pytest.fixture(autouse=True)
def keyed(monkeypatch):
    main._hits.clear()
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(googlemaps, "DAILY_SHARE", False)   # the month's limit alone; the daily share has its own tests


def fake_weather(monkeypatch):
    calls = []
    monkeypatch.setattr(googlemaps, "_get", lambda url, params, headers: calls.append(url) or {"forecastHours": [hour("t", 1, 50)]})
    return calls


def fake_places(monkeypatch):
    calls = []
    monkeypatch.setattr(googlemaps, "_post", lambda url, body, headers: calls.append(url) or {"places": []})
    return calls


def test_calls_stop_at_the_monthly_limit_before_google_is_asked(monkeypatch):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "3")
    calls = fake_weather(monkeypatch)
    for _ in range(3):
        googlemaps.rain_outlook(*HERE, 12)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_outlook(*HERE, 12)
    assert len(calls) == 3


def test_weather_and_places_each_have_their_own_count(monkeypatch):
    monkeypatch.setenv("MAPS_PLACES_MONTHLY_LIMIT", "1")
    posts, gets = fake_places(monkeypatch), fake_weather(monkeypatch)
    googlemaps.place_status("KFC", *HERE)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.place_status("KFC", *HERE)
    googlemaps.rain_outlook(*HERE, 12)
    assert (len(posts), len(gets)) == (1, 1)


def test_a_limit_is_never_above_googles_free_allowance(monkeypatch):
    # Nov 2026: Weather 10,000 free calls a month, Places Text Search Pro 5,000 (then USD 32 per 1,000)
    assert googlemaps.FREE_LIMITS["weather"] < 10_000 and googlemaps.FREE_LIMITS["places"] < 5_000
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "50000")
    assert googlemaps._limit("weather") == googlemaps.FREE_LIMITS["weather"]
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "lots")
    assert googlemaps._limit("weather") == 0, "a bad setting stops calls rather than risk a bill"


def test_the_count_survives_a_restart(monkeypatch, maps_usage_file):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "2")
    calls = fake_weather(monkeypatch)
    googlemaps.rain_outlook(*HERE, 12)
    googlemaps.rain_outlook(*HERE, 12)
    monkeypatch.setattr(googlemaps, "_usage", None)   # as after a restart: the count is read from the file again
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_outlook(*HERE, 12)
    assert len(calls) == 2 and json.loads(maps_usage_file.read_text())["weather"] == 2


def test_a_new_month_starts_at_midnight_us_pacific_never_earlier(monkeypatch):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "1")
    last_minutes = datetime(2026, 12, 1, 7, 59, tzinfo=timezone.utc)   # 30 Nov 23:59 at UTC-8: still November for Google
    googlemaps._spend("weather", last_minutes)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps._spend("weather", last_minutes)
    googlemaps._spend("weather", datetime(2026, 12, 1, 8, 0, tzinfo=timezone.utc))   # 1 Dec 00:00 at UTC-8


def test_a_failed_google_call_still_counts(monkeypatch):
    # Google may still have billed it, so the count errs high
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "1")

    def boom(url, params, headers):
        raise googlemaps.UpstreamError("HTTP 503")

    monkeypatch.setattr(googlemaps, "_get", boom)
    with pytest.raises(googlemaps.UpstreamError):
        googlemaps.rain_outlook(*HERE, 12)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_outlook(*HERE, 12)


def test_no_key_and_unnamed_shops_are_not_counted(monkeypatch, maps_usage_file):
    posts = fake_places(monkeypatch)
    assert googlemaps.place_status(googlemaps.UNNAMED + " shop", *HERE) is None
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")
    with pytest.raises(googlemaps.NotConfigured):
        googlemaps.rain_outlook(*HERE, 12)
    assert not posts and not maps_usage_file.exists()


@pytest.mark.parametrize("content", ["{not json", "[]", '{"month": 7}', '{"month": "2026-11", "weather": -5}',
                                     '{"month": "2026-11", "weather": "9"}', '{"month": "2026-11", "weather": true}'])
def test_an_unreadable_count_stops_calls_rather_than_start_again_from_zero(monkeypatch, maps_usage_file, content, caplog):
    maps_usage_file.write_text(content)
    calls = fake_weather(monkeypatch)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_outlook(*HERE, 12)
    assert not calls and "usage file" in caplog.text


def test_a_count_that_cannot_be_saved_stops_the_call(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("MAPS_USAGE_FILE", str(tmp_path / "no-such-folder" / "maps-usage.json"))
    calls = fake_weather(monkeypatch)
    with pytest.raises(googlemaps.FreeLimitReached):
        googlemaps.rain_outlook(*HERE, 12)
    assert not calls and "usage file" in caplog.text


def test_the_page_and_the_chat_say_the_free_allowance_is_used_up(monkeypatch):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "0")
    monkeypatch.setenv("MAPS_PLACES_MONTHLY_LIMIT", "0")
    posts, gets = fake_places(monkeypatch), fake_weather(monkeypatch)
    client = TestClient(main.app)
    assert client.get("/api/rain").json()["data"] == {"configured": True, "rain": None, "capped": True, "until": "month", "at": None}
    assert client.get(f"/api/place/{KNOWN['id']}").json()["data"] == {"configured": True, "place": None, "capped": True,
                                                                       "until": "month"}
    assert floodtools.rain_forecast() == {"error": floodtools.MAPS_CAPPED}
    assert floodtools.business_status(KNOWN["id"]) == {"error": floodtools.MAPS_CAPPED}
    assert not posts and not gets


# ---------- the daily share: a bot can use up one day's calls, not the month's

MYT = timezone(timedelta(hours=8))


def at(day, hour=17):
    # after 4 pm in Malaysia the US Pacific date (Google's month) is the same date, so both calendars agree
    return datetime(2026, 11, day, hour, tzinfo=MYT)


def test_each_day_may_use_its_share_of_what_is_left_of_the_month(monkeypatch):
    monkeypatch.setattr(googlemaps, "DAILY_SHARE", True)
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "300")
    # 1 Nov: 30 days left in November, so a share of 10
    for _ in range(10):
        googlemaps._spend("weather", at(1))
    with pytest.raises(googlemaps.DailyShareReached) as refused:
        googlemaps._spend("weather", at(1, 20))
    assert isinstance(refused.value, googlemaps.FreeLimitReached), "callers that catch the monthly cap catch this too"
    googlemaps._spend("weather", at(2))      # a new Malaysian day: 290 left over 29 days, a share of 10 again
    # 30 Nov, nothing used since: the whole of what is left may be used on the last day
    for _ in range(289):
        googlemaps._spend("weather", at(30))
    with pytest.raises(googlemaps.FreeLimitReached) as month:
        googlemaps._spend("weather", at(30))
    assert not isinstance(month.value, googlemaps.DailyShareReached), "the month's limit, not the day's share"


def test_a_quiet_day_leaves_more_for_the_days_after(monkeypatch):
    monkeypatch.setattr(googlemaps, "DAILY_SHARE", True)
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "300")
    googlemaps._spend("weather", at(21))     # 21 Nov: 300 over 10 days = 30, one used
    for _ in range(30):
        googlemaps._spend("weather", at(22))   # 22 Nov: 299 over 9 days, a share of 34
    assert googlemaps._usage["weather"] == 31


def test_the_day_turns_at_midnight_in_malaysia(monkeypatch):
    monkeypatch.setattr(googlemaps, "DAILY_SHARE", True)
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "300")
    for _ in range(10):
        googlemaps._spend("weather", datetime(2026, 11, 1, 23, 59, tzinfo=MYT))
    with pytest.raises(googlemaps.DailyShareReached):
        googlemaps._spend("weather", datetime(2026, 11, 1, 23, 59, tzinfo=MYT))
    googlemaps._spend("weather", datetime(2026, 11, 2, 0, 0, tzinfo=MYT))


def test_a_count_file_from_before_the_daily_share_still_reads(monkeypatch, maps_usage_file):
    monkeypatch.setattr(googlemaps, "DAILY_SHARE", True)
    maps_usage_file.write_text('{"month": "2026-11", "weather": 7}')
    googlemaps._spend("weather", at(26))
    saved = json.loads(maps_usage_file.read_text())
    assert saved["weather"] == 8 and saved["day"] == "2026-11-26" and saved["day_start"]["weather"] == 7


def test_the_page_and_the_chat_say_todays_share_is_back_tomorrow(monkeypatch):
    def share_used(*args, **kwargs):
        raise googlemaps.DailyShareReached("weather: today's share")
    monkeypatch.setattr(googlemaps, "_spend", share_used)
    client = TestClient(main.app)
    assert client.get("/api/rain").json()["data"] == {"configured": True, "rain": None, "capped": True, "until": "tomorrow", "at": None}
    assert client.get(f"/api/place/{KNOWN['id']}").json()["data"]["until"] == "tomorrow"
    assert floodtools.rain_forecast() == {"error": floodtools.MAPS_CAPPED_DAY}
    from app import outlook
    assert outlook._rain(googlemaps.rain_days, *HERE)[1] == "capped_day"


def test_the_months_limit_says_back_on_the_first(monkeypatch):
    monkeypatch.setenv("MAPS_WEATHER_MONTHLY_LIMIT", "0")
    assert TestClient(main.app).get("/api/rain").json()["data"]["until"] == "month"


# ---------- one address a day, and crawlers

def test_one_address_gets_a_days_worth_of_google_answers(monkeypatch):
    monkeypatch.setattr(main, "MAPS_DAILY_PER_VISITOR", 3)
    monkeypatch.setattr(main, "MAPS_RATE_LIMIT", 1000)
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: {"total_mm": 1.0})
    client = TestClient(main.app)
    one = {"x-forwarded-for": "203.0.113.7"}
    assert [client.get("/api/rain", headers=one).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert "tomorrow" in client.get("/api/rain", headers=one).json()["error"]
    assert client.get("/api/rain", headers={"x-forwarded-for": "203.0.113.8"}).status_code == 200
    monkeypatch.setattr(main, "_maps_today", {"day": "2000-01-01", "counts": {"203.0.113.7": 99}})
    assert client.get("/api/rain", headers=one).status_code == 200, "a new day starts again"


def test_crawlers_are_asked_to_leave_the_api_alone():
    found = TestClient(main.app).get("/robots.txt")
    assert found.status_code == 200 and "Disallow: /api/" in found.text
