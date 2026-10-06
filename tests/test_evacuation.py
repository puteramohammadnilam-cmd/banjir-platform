"""Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_evacuation.py"""
import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app import evacuation, main

ROW = {"id": 1, "name": "SK TAMAN MELATI", "latti": 3.03, "longi": 101.54, "negeri": "Selangor", "daerah": "Petaling",
       "mukim": "Bukit Raja", "bencana": "Banjir", "mangsa": 120, "keluarga": 30, "kapasiti": 34.5}
BOX = (101.52, 3.01, 101.56, 3.05)   # west, south, east, north


@pytest.fixture(autouse=True)
def fresh_state():
    evacuation._state = dict(evacuation._EMPTY)
    yield
    evacuation._state = dict(evacuation._EMPTY)


def test_a_centre_keeps_counts_and_place_and_no_one_s_details():
    assert evacuation.clean(ROW) == {"name": "SK TAMAN MELATI", "lat": 3.03, "lon": 101.54, "district": "Petaling",
                                     "disaster": "Banjir", "evacuees": 120, "families": 30, "full_pct": 35}


@pytest.mark.parametrize("change", [
    {"latti": "x"}, {"longi": None}, {"name": "   "}, {"mangsa": -1}, {"keluarga": 10**9},
    {"latti": 35.0}, {"longi": 140.0},   # outside Malaysia
    {"mangsa": 10**400},                 # too big for a float: dropped, not a crash
])
def test_rows_that_are_not_usable_centres_are_dropped(change):
    assert evacuation.clean({**ROW, **change}) is None


def test_a_missing_fill_level_is_unknown_not_zero():
    assert evacuation.clean({**ROW, "kapasiti": None})["full_pct"] is None


def test_long_names_are_cut_and_spaces_tidied():
    assert evacuation.clean({**ROW, "name": "  A   " + "B" * 200})["name"] == ("A " + "B" * 200)[:evacuation.MAX_NAME_CHARS]


def test_only_centres_near_the_box_count_nearest_its_middle_first():
    middle = evacuation.clean(ROW)
    edge = evacuation.clean({**ROW, "name": "EDGE", "latti": 3.07})          # about 2 km past the north edge
    far = evacuation.clean({**ROW, "name": "FAR", "latti": 3.20})            # about 17 km past it
    assert [c["name"] for c in evacuation.near(BOX, [edge, far, middle])] == ["SK TAMAN MELATI", "EDGE"]


def fetching(rows):
    calls = []
    return calls, lambda: calls.append(1) or [evacuation.clean(r) for r in rows]


def test_the_feed_is_asked_at_most_once_in_five_minutes_for_everyone():
    calls, fetch = fetching([ROW])
    now = [0.0]
    first = evacuation.for_box(BOX, clock=lambda: now[0], fetch=fetch)
    now[0] = evacuation.CACHE_S - 1
    evacuation.for_box(BOX, clock=lambda: now[0], fetch=fetch)
    assert len(calls) == 1
    now[0] = evacuation.CACHE_S + 1
    evacuation.for_box(BOX, clock=lambda: now[0], fetch=fetch)
    assert len(calls) == 2
    assert (first["count"], first["evacuees"], first["open_nationwide"], first["margin_km"]) == (1, 120, 1, evacuation.MARGIN_KM)
    assert first["source"] == evacuation.PORTAL and first["checked"]
    assert "lat" not in first["centres"][0] and "lon" not in first["centres"][0], "the page does not use them"


def test_a_failure_keeps_the_last_list_a_while_and_is_tried_again_sooner(caplog):
    _, good = fetching([ROW])
    evacuation.for_box(BOX, clock=lambda: 0.0, fetch=good)
    calls = []

    def bad():
        calls.append(1)
        raise evacuation.FeedError("HTTP 503 from the JKM feed")

    t = evacuation.CACHE_S + 1
    assert evacuation.for_box(BOX, clock=lambda: t, fetch=bad)["count"] == 1, "the list from before the failure"
    assert evacuation.for_box(BOX, clock=lambda: t + evacuation.RETRY_S - 1, fetch=bad)["count"] == 1
    assert len(calls) == 1, "not asked again within RETRY_S"
    assert evacuation.for_box(BOX, clock=lambda: evacuation.STALE_S + 1, fetch=bad) is None, "too old to show"
    assert len(calls) == 2 and "HTTP 503" in caplog.text


def test_with_no_list_yet_a_failing_feed_gives_none():
    def bad():
        raise evacuation.FeedError("timeout")

    assert evacuation.for_box(BOX, clock=lambda: 0.0, fetch=bad) is None


def test_a_request_that_finds_another_fetching_does_not_wait_for_it():
    assert evacuation._lock.acquire(blocking=False)
    try:
        assert evacuation.for_box(BOX, clock=lambda: 0.0, fetch=lambda: pytest.fail("asked JKM twice")) is None
    finally:
        evacuation._lock.release()


def test_at_most_five_centres_are_sent_but_all_are_counted():
    _, fetch = fetching([{**ROW, "name": f"PPS {i}"} for i in range(8)])
    found = evacuation.for_box(BOX, clock=lambda: 0.0, fetch=fetch)
    assert found["count"] == 8 and len(found["centres"]) == evacuation.MAX_SHOWN and found["evacuees"] == 960


# ---------- _fetch: what JKM may answer

class Answer(io.BytesIO):
    def __init__(self, body: bytes, url: str = evacuation.FEED):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answering(monkeypatch, answer):
    def urlopen(request, timeout):
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(evacuation.urllib.request, "urlopen", urlopen)


def body(*rows):
    return json.dumps({"points": list(rows)}).encode()


def test_only_flood_centres_are_kept(monkeypatch):
    answering(monkeypatch, Answer(body(ROW, {**ROW, "name": "FIRE", "bencana": "Kebakaran"},
                                       {**ROW, "name": "FLASH", "bencana": "Banjir Kilat"})))
    assert [c["name"] for c in evacuation._fetch()] == ["SK TAMAN MELATI", "FLASH"]


def test_an_empty_list_is_a_real_answer(monkeypatch):
    answering(monkeypatch, Answer(body()))
    assert evacuation._fetch() == []


@pytest.mark.parametrize("answer, words", [
    (urllib.error.HTTPError(evacuation.FEED, 503, "down", {}, None), "HTTP 503"),
    (TimeoutError("timed out"), "TimeoutError"),
    (Answer(b"<html>maintenance</html>"), "JSONDecodeError"),
    (Answer(b"[1, 2]"), "AttributeError"),
    (Answer(json.dumps({"points": "none"}).encode()), "no list of points"),
    (Answer(b"[" * 100_000 + b"]" * 100_000), "Error"),                       # too deep to parse
    (Answer(body({"nama": "renamed fields", "lat": 3.0})), "none of the JKM feed's 1 rows"),
    (Answer(b" " * (evacuation.MAX_BYTES + 1)), "too much"),
    (Answer(body(ROW), url="https://elsewhere.example/x"), "another host"),
])
def test_any_answer_that_is_not_a_list_of_centres_is_a_feed_error(monkeypatch, answer, words):
    answering(monkeypatch, answer)
    with pytest.raises(evacuation.FeedError, match=words):
        evacuation._fetch()


# ---------- the endpoint

def test_the_endpoint_answers_for_an_area_and_a_section(monkeypatch):
    main._hits.clear()
    asked = []
    monkeypatch.setattr(evacuation, "for_box", lambda box: asked.append(tuple(box)) or {"count": 0, "centres": []})
    client = TestClient(main.app)
    assert client.get("/api/evacuation").json()["data"]["centres"] == {"count": 0, "centres": []}
    assert client.get("/api/evacuation?area=shah-alam&section=seksyen-25").status_code == 200
    assert asked[0] != asked[1], "the section's own box, not the city's"
    assert client.get("/api/evacuation?area=nope").status_code == 404


def test_the_endpoint_says_null_while_there_is_no_list(monkeypatch):
    main._hits.clear()
    monkeypatch.setattr(evacuation, "for_box", lambda box: None)
    assert TestClient(main.app).get("/api/evacuation").json() == {"success": True, "data": {"centres": None}, "error": None}
