"""The 3D page's satellite photo: Esri World Imagery through an ArcGIS Location Platform key (app/satellite.py), handed to
the page by GET /api/satellite, and the Content-Security-Policy that lets only the keyed Esri host in. No network."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main, satellite

STATIC = Path(main.__file__).parent / "static"
KEYED_HOST = "https://ibasemaps-api.arcgis.com"
KEYLESS_HOST = "server.arcgisonline.com"


@pytest.fixture
def client():
    main._hits.clear()
    return TestClient(main.app)


def csp_directive(header: str, name: str) -> list[str]:
    """The sources of one directive of a Content-Security-Policy header."""
    found = [part.split() for part in header.split(";") if part.split()[:1] == [name]]
    assert len(found) == 1, f"{name} appears {len(found)} times"
    return found[0][1:]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_without_a_key_the_page_gets_no_satellite(client, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(satellite.KEY_NAME, raising=False)
    else:
        monkeypatch.setenv(satellite.KEY_NAME, value)
    res = client.get("/api/satellite")
    assert res.status_code == 200
    assert res.json() == {"success": True, "data": {"satellite": None}, "error": None}
    assert satellite.is_configured() is False


def test_with_a_key_the_page_gets_the_keyed_tile_url_and_esris_credit(client, monkeypatch):
    monkeypatch.setenv(satellite.KEY_NAME, "  AAPTxy-123_abc  ")
    found = client.get("/api/satellite").json()["data"]["satellite"]
    assert found["tiles"] == (f"{KEYED_HOST}/arcgis/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}"
                              "?token=AAPTxy-123_abc")
    assert found["attribution"].startswith('Powered by <a href="https://www.esri.com">Esri</a> | Source: Esri, ')
    assert found["attribution"].endswith("and the GIS User Community")
    assert satellite.is_configured() is True


def test_a_key_with_url_characters_cannot_break_out_of_the_token(monkeypatch):
    monkeypatch.setenv(satellite.KEY_NAME, "a&b=c/d?e#f g")
    tiles = satellite.imagery()["tiles"]
    assert tiles.endswith("?token=a%26b%3Dc%2Fd%3Fe%23f%20g")
    assert tiles.count("?") == 1 and "&" not in tiles and "#" not in tiles


def test_the_key_is_never_cached_and_head_works(client, monkeypatch):
    monkeypatch.setenv(satellite.KEY_NAME, "key-1")
    assert client.get("/api/satellite").headers["cache-control"] == "no-store"   # a rotated key must not linger
    assert client.head("/api/satellite").status_code == 200
    assert client.post("/api/satellite").status_code == 405


def test_the_satellite_answer_is_rate_limited_with_the_map_layers(client, monkeypatch):
    monkeypatch.setattr(main, "MAP_RATE_LIMIT", 2)
    codes = [client.get("/api/satellite").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_the_csp_lets_in_the_keyed_esri_host_and_not_the_keyless_one(client):
    header = client.get("/api/satellite").headers["content-security-policy"]
    images, fetches = csp_directive(header, "img-src"), csp_directive(header, "connect-src")
    for sources in (images, fetches):   # MapLibre fetches its tiles, so the tile hosts are in both
        assert KEYED_HOST in sources and "https://tile.openstreetmap.org" in sources
    assert "blob:" in images and "data:" in images
    assert KEYLESS_HOST not in header


def test_no_page_file_asks_the_keyless_esri_server():
    pages = [p for p in STATIC.rglob("*") if p.suffix in {".html", ".js", ".css"} and "vendor" not in p.parts]
    assert pages and not [p.name for p in pages if KEYLESS_HOST in p.read_text(encoding="utf-8")]


def test_the_satellite_switch_starts_hidden_on_the_3d_page():
    """The page shows it only once /api/satellite has a photo; without a key the street map is all there is."""
    page = (STATIC / "3d.html").read_text(encoding="utf-8")
    switch = re.search(r'<label[^>]*id="f3d-satellite-switch"[^>]*>', page)
    assert switch and " hidden" in switch.group(0)
    assert ".f3d-toggle[hidden] { display: none; }" in (STATIC / "flood3d" / "flood3d.css").read_text(encoding="utf-8")
