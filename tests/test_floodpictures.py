"""An area that sends no squares (a state split into districts): its flood depth pictures (app/floodpictures.py and
GET /api/areas/{id}/flood/{section}/{rp}/{theme}.png), and a district's main town for the rain and the outlook
(app/sections.py centre), on the made-up sectioned city.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_floodpictures.py
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import areas, floodpictures, main, sections
from sectioned_fixture import CITY, PLAIN, city  # noqa: F401  (city is a fixture)

PNG = b"\x89PNG\r\n\x1a\n made-up"


def install_pictures(folder, outlines=None):
    """flood_pictures.json and the zon-1 pictures, as tools/outline_squares.py lays them out."""
    flood = folder / CITY / "flood"
    flood.mkdir()
    doc = {"credit": "Water: JRC.", "outlines": outlines if outlines is not None else [
        {"id": "zon-1", "bounds": [101.5, 3.0, 101.53, 3.03]}, {"id": "zon-2", "bounds": None}]}
    (flood / "flood_pictures.json").write_text(json.dumps(doc), encoding="utf-8")
    for rp in ("10", "20", "50"):
        for theme in ("light", "dark"):
            (flood / f"zon-1_rp{rp}_{theme}.png").write_bytes(PNG)
    floodpictures.clear_cache()
    return flood


@pytest.fixture
def client(city, monkeypatch):
    main._hits.clear()
    return TestClient(main.app)


def test_the_page_is_told_where_each_sections_picture_is_and_the_url_to_fill(city):
    install_pictures(city)
    assert floodpictures.layer(CITY) == {"url": f"/api/areas/{CITY}/flood/{{section}}/{{rp}}/{{theme}}.png",
                                         "credit": "Water: JRC.",
                                         "pictures": [{"section": "zon-1", "bounds": [101.5, 3.0, 101.53, 3.03]}]}
    assert floodpictures.layer(PLAIN) is None, "an area that sends its squares has no pictures"


def test_the_pictures_reach_the_page_in_the_area_layers(client, city):
    install_pictures(city)
    sent = client.get(f"/api/areas/{CITY}/data").json()["data"]["area"]["layers"]["flood_depth"]
    assert sent["pictures"] == [{"section": "zon-1", "bounds": [101.5, 3.0, 101.53, 3.03]}]


def test_a_picture_is_served_and_anything_else_is_a_404(client, city):
    install_pictures(city)
    found = client.get(f"/api/areas/{CITY}/flood/zon-1/50/dark.png")
    assert found.status_code == 200 and found.content == PNG and found.headers["content-type"] == "image/png"
    for path in ("zon-1/50/blue", "zon-1/100/dark", "zon-2/50/dark", "zon-9/50/dark", "..%2Fzon-1/50/dark"):
        assert client.get(f"/api/areas/{CITY}/flood/{path}.png").status_code == 404, path
    assert client.get(f"/api/areas/{PLAIN}/flood/zon-1/50/dark.png").status_code == 404
    assert client.get("/api/areas/nope/flood/zon-1/50/dark.png").status_code == 404


def test_a_damaged_pictures_file_costs_the_pictures_not_the_page(city, caplog):
    flood = install_pictures(city)
    (flood / "flood_pictures.json").write_text("{not json", encoding="utf-8")
    floodpictures.clear_cache()
    assert floodpictures.layer(CITY) is None and floodpictures.png_path(CITY, "zon-1", "50", "dark") is None
    assert "flood_pictures.json cannot be read" in caplog.text


def test_a_districts_main_town_is_where_rain_is_asked_else_the_middle_of_its_box(city):
    path = areas.AREAS_DIR / CITY / "sections.json"
    doc = json.loads(path.read_text())
    doc["sections"][0]["town"] = [101.51, 3.02]
    path.write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    sections.preload()
    area = areas.get(CITY)
    assert sections.centre(sections.get(area, "zon-1")) == (3.02, 101.51)
    assert sections.centre(sections.get(area, "zon-u3")) == pytest.approx((3.05, 101.515))


@pytest.mark.parametrize("town", [[101.6, 3.02], [101.51], "101.51,3.02", [101.51, None]])
def test_a_town_outside_its_box_or_not_a_point_stops_the_server(city, town):
    path = areas.AREAS_DIR / CITY / "sections.json"
    doc = json.loads(path.read_text())
    doc["sections"][0]["town"] = town
    path.write_text(json.dumps(doc), encoding="utf-8")
    sections.clear_caches()
    with pytest.raises(areas.AreaError, match="town"):
        sections.preload()
