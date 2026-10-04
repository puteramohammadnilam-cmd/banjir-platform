"""Plan card A4 through HTTP: POST /api/point, /api/coverage, and `place` in the business endpoints.

Fixture rasters through BANJIR_RASTER_DIR; the parity test reads the real JRC files and skips only without them.
Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_points_api.py
"""
import base64
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tiff_fixture as fx
from app import ai, areas, costs, googlemaps, main, places, raster

ROOT = Path(__file__).resolve().parent.parent
GRID = "N10_E100"
WET, WET_ID = (6.4321, 101.1987), "pt:6.37500,101.12500"
INNER = (6.4321, 103.6)                  # fixture row 14, col 14: all four blocks around it are loaded
DRY = (4.9, 101.1)
POINT_WORDS = "Please check the location and try again."
TINY_JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * 64).decode()
SRI_MUDA_ID = areas.premises("sri-muda")[0]["id"]


@pytest.fixture
def rasters(tmp_path, monkeypatch):
    folder = fx.write_depth_set(tmp_path / "rasters")
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(folder))
    return folder


@pytest.fixture
def client(rasters, monkeypatch):
    main._hits.clear()
    monkeypatch.setattr(ai, "read_shop_photo", lambda image, mime: ai.PhotoEstimate(
        is_shop_front=True, floor_height_cm=30, steps_counted=2, stock_at_floor_level="yes",
        confidence="low", reasoning="Two steps."))
    return TestClient(main.app)


def post_point(client, lat, lon, source="pin"):
    return client.post("/api/point", json={"lat": lat, "lon": lon, "source": source})


# --- POST /api/point ---

def test_a_covered_point_gives_its_place_and_depths(client):
    res = post_point(client, *WET, source="gps")
    assert res.status_code == 200 and res.json()["success"] is True
    data = res.json()["data"]
    assert (data["coverage"], data["region"]) == ("covered", "peninsula")
    assert data["place"] == places.point(*WET) and data["place"]["id"] == WET_ID
    assert data["place"]["depth_m"] == {"10": 14.14, "20": 14.64, "50": 15.14}


def test_a_covered_point_comes_with_the_wet_squares_of_the_blocks_around_it(client):
    # a URL asking for a block would name the area in every log: the squares come in the one POST, whose body is never
    # logged
    data = post_point(client, *INNER).json()["data"]
    blocks = [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert data["blocks"] == [{"grid": GRID, "bi": bi, "bj": bj} for bi, bj in blocks]
    assert data["cells"] == [cell for bi, bj in blocks for cell in raster.depth_set().block(GRID, bi, bj, 24)]
    assert [6.25, 103.5, 14.24, 14.74, 15.24] in data["cells"], "the point's own square"
    assert all(len(cell) == 5 and any(cell[2:]) for cell in data["cells"]) and len(data["cells"]) <= 4 * 24 * 24


def test_the_blocks_are_cut_at_the_grid_edge(client):
    data = post_point(client, *WET).json()["data"]   # row 14, col 4: west of block 0 there is nothing
    assert [(b["bi"], b["bj"]) for b in data["blocks"]] == [(0, 0), (1, 0)]
    assert data["cells"] == [cell for b in data["blocks"] for cell in raster.depth_set().block(GRID, b["bi"], b["bj"], 24)]


@pytest.mark.parametrize("lat, lon", [(1.5535, 110.3593), (6.33, 99.84), (35.68, 139.69)], ids=["borneo", "langkawi", "tokyo"])
def test_a_point_that_cannot_be_checked_comes_with_no_squares(client, lat, lon):
    data = post_point(client, lat, lon).json()["data"]
    assert data["place"] is None and "cells" not in data and "blocks" not in data


def test_reopening_a_point_link_gets_the_squares_too(client):
    # a #place= link: the page snaps the id's numbers (a square's centre) and posts them, as for a pin
    first = post_point(client, *INNER, source="gps").json()["data"]
    lat, lon = places.parse_point_id(first["place"]["id"])
    again = post_point(client, lat, lon, source="pin").json()["data"]
    assert again == first and again["cells"] and again["blocks"]


def test_the_sea_is_covered_with_all_depths_null(client):
    data = post_point(client, *DRY).json()["data"]
    assert data["coverage"] == "covered" and data["place"]["depth_m"] == {"10": None, "20": None, "50": None}


@pytest.mark.parametrize("lat, lon, coverage, region", [
    (1.5535, 110.3593, "not_loaded", "borneo"),     # Kuching
    (6.33, 99.84, "not_loaded", "langkawi"),
    (35.68, 139.69, "outside", None),               # Tokyo
])
def test_uncovered_points_say_why(client, lat, lon, coverage, region):
    res = post_point(client, lat, lon)
    assert res.status_code == 200
    assert res.json()["data"] == {"coverage": coverage, "region": region, "place": None}


@pytest.mark.parametrize("raw", [
    '{"lat": NaN, "lon": 101.2, "source": "pin"}',
    '{"lat": 6.4, "lon": Infinity, "source": "pin"}',
    '{"lat": 1e400, "lon": 101.2, "source": "pin"}',
    '{"lat": "6.4", "lon": 101.2, "source": "pin"}',
    '{"lat": true, "lon": 101.2, "source": "pin"}',
    '{"lat": null, "lon": 101.2, "source": "pin"}',
    '{"lon": 101.2, "source": "pin"}',
    '{"lat": 6.4, "lon": 101.2}',
    '{"lat": 6.4, "lon": 101.2, "source": "ip"}',
    '{"lat": 90.5, "lon": 101.2, "source": "pin"}',
    '{"lat": 6.4, "lon": -180.5, "source": "gps"}',
    '[6.4, 101.2]',
    'lat=6.4&lon=101.2',
])
def test_a_bad_point_body_is_a_422_in_plain_words(client, raw):
    res = client.post("/api/point", content=raw, headers={"content-type": "application/json"})
    assert res.status_code == 422
    assert res.json() == {"success": False, "data": None, "error": POINT_WORDS}


PLAIN_WORDS = {   # what each endpoint says to a body that does not fit
    "/api/point": POINT_WORDS,
    "/api/ask": main.QUESTION_WORDS,
    "/api/estimate": "Please check the figures. Use plain numbers, such as 50000.",
    "/api/photo": "The photo could not be sent. Please choose it again.",
    "/api/news": "Please reload the page and ask for the news again.",
}


@pytest.mark.parametrize("raw", [
    b'{"lat": ' + b"1" * 5000 + b', "lon": 101.2, "source": "pin"}',   # more digits than Python turns into an int
    b'{"lat": 6.4, "lon": 101.2, "source": "pin\xff"}',                 # not UTF-8
    b"[" * 50_000,                                                       # nested too deep to read
], ids=["5000-digit-integer", "invalid-utf8", "deep-nesting"])
@pytest.mark.parametrize("path", PLAIN_WORDS)
def test_a_body_that_cannot_be_read_is_a_422_in_plain_words(client, monkeypatch, path, raw):
    calls = []
    for name in ("ask", "flood_news", "read_shop_photo"):
        monkeypatch.setattr(ai, name, lambda *args: calls.append(args))
    res = client.post(path, content=raw, headers={"content-type": "application/json"})
    assert (res.status_code, res.json()) == (422, {"success": False, "data": None, "error": PLAIN_WORDS[path]})
    assert calls == []


def test_points_are_posted_not_got(client):
    res = client.get("/api/point?lat=6.4&lon=101.2")
    assert res.status_code == 405 and res.headers["allow"] == "POST" and res.json()["success"] is False


@pytest.mark.parametrize("path", ["/api/ask", "/api/photo", "/api/estimate", "/api/news"])
def test_every_post_only_endpoint_says_405_to_a_get(client, path):
    assert client.get(path).status_code == 405


def test_without_raster_files_points_are_not_ready(client, tmp_path, monkeypatch):
    assert client.get("/api/status").json()["data"]["points_ready"] is True
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(tmp_path / "none"))
    assert client.get("/api/status").json()["data"]["points_ready"] is False
    assert post_point(client, *WET).json()["data"] == {"coverage": "not_loaded", "region": "peninsula", "place": None}


def test_a_broken_raster_file_is_a_503_in_plain_words(client, tmp_path, monkeypatch, caplog):
    broken = fx.write_depth_set(tmp_path / "broken")
    fx.write_depth_tiff(broken / f"ID211_{GRID}_RP10_depth.tif", fx.depth_values(), tags={339: (fx.SHORT, (1,))})
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(broken))
    for res in (post_point(client, *WET), client.get("/api/coverage")):
        assert res.status_code == 503 and res.json()["error"] == "Could not read the flood model just now. Try again."
    assert "SampleFormat" in caplog.text and "6.43" not in caplog.text


# --- /api/coverage ---

def test_coverage_describes_the_loaded_grids_and_regions(client):
    data = client.get("/api/coverage").json()["data"]
    assert set(data) == {"data_version", "return_periods", "block_cells", "grids", "regions"}
    assert data == places.coverage() and data["block_cells"] == 24
    assert [region["id"] for region in data["regions"]] == ["langkawi", "peninsula", "borneo"]


def test_there_is_no_endpoint_for_a_block_of_squares_by_its_address(client):
    # GET /api/cells/{grid}/{bi}/{bj} is gone: its URL named the area in every log, and the page never called it
    res = client.get(f"/api/cells/{GRID}/0/0")
    assert res.status_code == 404 and res.json()["success"] is False


# --- headers ---

def test_geolocation_is_allowed_for_this_page_only(client):
    for res in (client.get("/"), client.get("/api/status")):
        assert "geolocation=(self)" in res.headers["permissions-policy"]
        assert "camera=()" in res.headers["permissions-policy"]


def test_pages_send_only_their_origin_as_the_referrer(client):
    # strict-origin: a request from the page, to this site or to the map tiles, names the site and not the page's
    # address, so a link's place never reaches a request log through the Referer header
    for res in (client.get("/"), client.get("/api/status"), client.get("/api/nope"), post_point(client, *WET)):
        assert res.headers["referrer-policy"] == "strict-origin"


def test_rain_place_and_point_answers_are_never_stored(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(googlemaps, "rain_outlook", lambda lat, lon, hours: {"total_mm": 0})
    monkeypatch.setattr(googlemaps, "place_status", lambda name, lat, lon: None)
    for res in (client.get("/api/rain"), client.get(f"/api/place/{SRI_MUDA_ID}"), client.get(f"/api/place/{WET_ID}"),
                post_point(client, *WET)):
        assert res.headers["cache-control"] == "no-store"
    assert "no-store" not in client.get("/api/coverage").headers.get("cache-control", "")


# --- compression ---

GZIP = {"Accept-Encoding": "gzip"}


def test_a_point_answer_is_gzipped_with_its_headers_and_format_unchanged(client):
    plain = client.post("/api/point", json={"lat": WET[0], "lon": WET[1], "source": "pin"},
                        headers={"Accept-Encoding": "identity"})
    zipped = client.post("/api/point", json={"lat": WET[0], "lon": WET[1], "source": "pin"}, headers=GZIP)
    assert "content-encoding" not in plain.headers and zipped.headers["content-encoding"] == "gzip"
    assert zipped.json() == plain.json()   # the client unzips it: the same envelope, the same keys
    assert int(zipped.headers["content-length"]) < len(plain.content) / 3
    for header in ("cache-control", "referrer-policy", "permissions-policy", "content-security-policy"):
        assert zipped.headers[header] == plain.headers[header], header
    assert zipped.headers["cache-control"] == "no-store" and "accept-encoding" in zipped.headers["vary"].lower()


def test_an_upload_refused_for_its_size_is_answered_plainly_not_gzipped(client):
    res = client.post("/api/photo", content=b"{}", headers={**GZIP, "content-length": str(main.MAX_BODY_BYTES + 1),
                                                            "content-type": "application/json"})
    assert res.status_code == 413 and "content-encoding" not in res.headers
    assert res.json() == {"success": False, "data": None, "error": "That upload is too large."}
    assert res.headers["content-security-policy"]


def test_a_short_answer_is_not_gzipped(client):
    res = client.get("/api/status", headers=GZIP)
    assert len(res.content) < 1024 and "content-encoding" not in res.headers


# --- rate limits ---

def test_point_checks_have_their_own_bucket(client, monkeypatch):
    assert (main.GEO_RATE_LIMIT, main.MAP_RATE_LIMIT) == (120, 1200)
    monkeypatch.setattr(main, "GEO_RATE_LIMIT", 3)
    codes = [post_point(client, *WET).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert client.get("/api/coverage").status_code == 200   # the map bucket is separate


def test_coverage_has_the_map_bucket(client, monkeypatch):
    monkeypatch.setattr(main, "MAP_RATE_LIMIT", 2)
    assert [client.get("/api/coverage").status_code for _ in range(3)] == [200, 200, 429]
    assert post_point(client, *WET).status_code == 200


# --- `place` in /api/ask, /api/photo and /api/estimate ---

def test_ask_takes_a_point_and_its_area(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "ask", lambda question, place, history, area: seen.append((place, area)) or "ok")
    assert client.post("/api/ask", json={"question": "Banjir tak?", "place": WET_ID}).status_code == 200
    assert client.post("/api/ask", json={"question": "hi", "place": WET_ID, "area_id": "kota-tinggi"}).status_code == 200
    assert client.post("/api/ask", json={"question": "hi", "business_id": SRI_MUDA_ID}).status_code == 200
    assert seen == [(WET_ID, None), (WET_ID, None), (SRI_MUDA_ID, areas.get("sri-muda"))]


@pytest.mark.parametrize("body, status, error", [
    ({"place": "pt:6.375,101.125"}, 422, POINT_WORDS),
    ({"place": "pt:6.37501,101.12500"}, 422, POINT_WORDS),
    ({"place": "pt:35.68000,139.69000"}, 404, "That point is not covered by the flood model in this build."),
    ({"place": "node-1"}, 404, "Unknown business."),
    ({"place": WET_ID, "area_id": "nope"}, 404, "Unknown area."),
    ({"place": "x" * 41}, 422, None),
])
def test_ask_refuses_a_place_it_cannot_find(client, monkeypatch, body, status, error):
    calls = []
    monkeypatch.setattr(ai, "ask", lambda *args: calls.append(args) or "x")
    res = client.post("/api/ask", json={"question": "hi", **body})
    assert res.status_code == status and calls == [] and res.json()["success"] is False
    assert error is None or res.json()["error"] == error


def test_place_wins_over_business_id_even_when_it_is_null(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "ask", lambda question, place, history, area: seen.append(place) or "ok")
    for place in (None, WET_ID):
        body = {"question": "hi", "place": place, "business_id": SRI_MUDA_ID}
        assert client.post("/api/ask", json=body).status_code == 200
    assert seen == [None, WET_ID]   # null selects nothing: business_id is not used
    for path, rest in (("/api/estimate", {"value_at_risk_rm": 1000}), ("/api/photo", {"image": TINY_JPEG})):
        assert client.post(path, json={"place": None, "business_id": SRI_MUDA_ID, **rest}).status_code == 422


def test_photo_for_a_point_uses_the_point_depths(client):
    res = client.post("/api/photo", json={"place": WET_ID, "image": TINY_JPEG})
    depth = places.point(*WET)["depth_m"]
    assert res.status_code == 200
    assert res.json()["data"]["water_above_floor_m"] == {rp: round(max(0.0, d - 0.30), 2) for rp, d in depth.items()}
    old_name = client.post("/api/photo", json={"business_id": SRI_MUDA_ID, "image": TINY_JPEG})
    assert old_name.status_code == 200


def test_estimate_for_a_point_is_the_cost_engine_on_its_depths(client):
    figures = {"value_at_risk_rm": 80_000, "floor_height_cm": 20, "daily_takings_rm": 500, "closed_days": 7}
    res = client.post("/api/estimate", json={"place": WET_ID, **figures})
    assert res.status_code == 200
    data = res.json()["data"]
    assert (data["place"], data["business"]) == (WET_ID, None)
    expected = costs.estimate(places.point(*WET)["depth_m"], shop_size="", raise_cm=0, measure_cost_rm=0, **figures)
    assert {key: data[key] for key in expected} == expected


def test_estimate_still_takes_business_id(client):
    res = client.post("/api/estimate", json={"business_id": SRI_MUDA_ID, "value_at_risk_rm": 10_000})
    assert res.status_code == 200 and res.json()["data"]["business"] == areas.premises("sri-muda")[0]["name"]
    missing = client.post("/api/estimate", json={"value_at_risk_rm": 10_000})
    assert missing.status_code == 422 and "figures" in missing.json()["error"]


def test_the_google_listing_is_never_looked_up_for_a_point(client, monkeypatch):
    calls = []
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setattr(googlemaps, "place_status", lambda *args: calls.append(args) or {"status": "open"})
    res = client.get(f"/api/place/{WET_ID}")
    assert res.status_code == 404 and res.json()["success"] is False and calls == []
    assert client.get("/api/place/pt:anything").status_code == 404 and calls == []


# --- the open item from A3: a malformed news body ---

@pytest.mark.parametrize("raw", ['{"area_id": 5}', '{"area_id": "' + "x" * 41 + '"}', "[1]", "{"])
def test_a_malformed_news_body_is_a_422_in_plain_words(client, monkeypatch, raw):
    calls = []
    monkeypatch.setattr(ai, "flood_news", lambda *args: calls.append(args) or {})
    res = client.post("/api/news", content=raw, headers={"content-type": "application/json"})
    assert res.status_code == 422 and calls == []
    assert res.json() == {"success": False, "data": None, "error": "Please reload the page and ask for the news again."}


# --- parity through the API, on the real JRC files ---

def real_raster_dir() -> Path | None:
    candidates = (os.environ.get("BANJIR_RASTER_DIR"), ROOT / "app" / "data" / "rasters",
                  ROOT.parent / "05_Raw_Data_Sources" / "jrc_glofas_v2_1")
    return next((Path(c) for c in candidates if c and any(Path(c).glob("*_RP*_depth.tif"))), None)


REAL_DIR = real_raster_dir()


@pytest.mark.skipif(REAL_DIR is None, reason="no JRC depth files on this machine")
def test_parity_each_premise_point_returns_its_depth(monkeypatch):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(REAL_DIR))
    monkeypatch.setattr(main, "GEO_RATE_LIMIT", 10_000)
    main._hits.clear()
    client = TestClient(main.app)
    checked = 0
    for area in areas.load_all():
        for premise in areas.premises(area.id):
            data = post_point(client, premise["lat"], premise["lon"]).json()["data"]
            assert (data["coverage"], data["place"]["depth_m"]) == ("covered", premise["depth_m"]), premise["id"]
            # a business near the view's edge can sit in a square whose centre is outside it: that point is in no area
            west, south, east, north = area.view
            lat, lon = data["place"]["lat"], data["place"]["lon"]
            inside = west <= lon <= east and south <= lat <= north
            assert data["place"]["area_id"] == (area.id if inside else None), premise["id"]
            checked += 1
    assert checked == sum(len(areas.premises(area.id)) for area in areas.load_all()) == 204 + 27 + 300 + 491 + 158
    example = post_point(client, 3.0297599, 101.5364982).json()["data"]["place"]   # the plan's checklist point
    assert example["id"] == "pt:3.02998,101.53667" and example["depth_m"]["50"] == 1.76


@pytest.mark.skipif(REAL_DIR is None, reason="no JRC depth files on this machine")
def test_a_point_on_the_peninsula_edge_never_gets_an_id_that_404s(monkeypatch):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(REAL_DIR))
    main._hits.clear()
    client = TestClient(main.app)
    # The review's case: (1.15, 103.0) is on the box's south edge, but its square's centre is just south of it, so the
    # id it used to get (this one) was refused by every endpoint that takes a place
    assert places.snap(1.15, 103.0).id == "pt:1.14998,103.00000"
    assert post_point(client, 1.15, 103.0).json()["data"] == {"coverage": "outside", "region": None, "place": None}
    inside = post_point(client, 1.1505, 103.0).json()["data"]   # the next square north, whose centre is in the box
    point_id = inside["place"]["id"]
    assert (inside["coverage"], inside["region"], point_id) == ("covered", "peninsula", "pt:1.15082,103.00000")
    assert client.post("/api/estimate", json={"place": point_id, "value_at_risk_rm": 1000}).status_code == 200
