"""The new map preview (map.html): served with the site's headers, its Content-Security-Policy lets OpenFreeMap's tiles
in, it loads only its own script and the vendored MapLibre, and the base map styles and Arus's licence are kept beside
it. No network."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main

STATIC = Path(main.__file__).parent / "static"
OPENFREEMAP = "https://tiles.openfreemap.org"


@pytest.fixture
def client():
    main._hits.clear()
    return TestClient(main.app)


def csp_directive(header: str, name: str) -> list[str]:
    found = [part.split() for part in header.split(";") if part.split()[:1] == [name]]
    assert len(found) == 1, f"{name} appears {len(found)} times"
    return found[0][1:]


def test_the_preview_page_is_served_with_the_site_headers(client):
    response = client.get("/map.html")
    assert response.status_code == 200
    assert 'id="mg-map"' in response.text
    assert response.headers["x-frame-options"] == "DENY"


def test_the_csp_lets_openfreemap_tiles_fonts_and_sprites_in(client):
    header = client.get("/map.html").headers["content-security-policy"]
    for directive in ("connect-src", "img-src"):   # MapLibre fetches vector tiles, glyphs and sprites
        assert OPENFREEMAP in csp_directive(header, directive)
    assert csp_directive(header, "script-src") == ["'self'"]


def test_the_page_runs_only_its_own_script_and_the_vendored_maplibre():
    page = (STATIC / "map.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', page)
    assert scripts == ["vendor/maplibre-gl-csp.js", "js/map-gl.js"]
    assert "<script>" not in page   # nothing inline: script-src is 'self' only


@pytest.mark.parametrize("name", ["positron", "dark"])
def test_the_base_map_styles_are_kept_here_and_draw_from_openfreemap(name):
    style = json.loads((STATIC / "vendor" / "openfreemap" / f"{name}.json").read_text(encoding="utf-8"))
    hosts = [style["glyphs"], *(s.get("url", "") for s in style["sources"].values())]
    assert all(h.startswith(OPENFREEMAP) for h in hosts if h)
    assert any(layer["id"].startswith(("building", "road", "highway")) for layer in style["layers"])


def test_arus_is_credited_with_its_licence():
    licence = (STATIC / "vendor" / "LICENSE-arus.txt").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Farhan Syah" in licence
    assert "LICENSE-arus.txt" in (STATIC / "js" / "map-gl.js").read_text(encoding="utf-8")
