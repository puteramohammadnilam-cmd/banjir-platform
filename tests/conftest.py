"""Shared by every test: Google Maps calls are counted in a file of the test's own (app/googlemaps.py monthly cap), so
no test writes the real count or starts from another test's."""
import pytest

from app import googlemaps


@pytest.fixture(autouse=True)
def maps_usage_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPS_USAGE_FILE", str(tmp_path / "maps-usage.json"))
    monkeypatch.setattr(googlemaps, "_usage", None)
    return tmp_path / "maps-usage.json"
