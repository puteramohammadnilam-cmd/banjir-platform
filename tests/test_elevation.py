"""app/elevation.py: heights from small fixture crops (every number known), the place and premise fields, the logs,
and the committed Shah Alam crops (their SOURCES.txt, and the values at spots checked by hand on 4 Oct 2026)."""
import hashlib
import logging
import math
import re
import sys
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import areas, elevation, places, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import geotiff_write as gw  # noqa: E402

DEM = ROOT / "app" / "data" / "dem"
ORIGIN, PIXEL, TILE = (100.0, 10.0), 0.25, 16   # the depth fixture's grid, so a point has both a depth and a height
ROWS, COLS = 20, 24
SPECIAL = {(0, 0): -9999.0, (0, 1): 0.0, (0, 2): -2.345, (0, 3): math.nan, (0, 4): -0.04, (0, 5): 12.36}
NO_RIVER = (1, 1)     # a surface but no river within reach


def surface(r: int, c: int) -> float:
    return SPECIAL.get((r, c), 5 + r + c / 10)


def above(r: int, c: int) -> float:
    return -9999.0 if (r, c) == NO_RIVER else surface(r, c) - 7


def write_crop(folder: Path, name: str = "test-area", origin=ORIGIN, layers=("surface", "above_river"), **options) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    values = {"surface": surface, "above_river": above}
    for layer in layers:
        rows = [[values[layer](r, c) for c in range(COLS)] for r in range(ROWS)]
        gw.write_tiff(folder / f"{name}_{layer}.tif", rows, tile=TILE, origin=origin, pixel=(PIXEL, PIXEL),
                      padding=-9999.0, **options)
    return folder


def centre(r: int, c: int) -> tuple[float, float]:
    """(lat, lon) of a fixture square's centre."""
    return ORIGIN[1] - (r + 0.5) * PIXEL, ORIGIN[0] + (c + 0.5) * PIXEL


@pytest.fixture
def dem(tmp_path, monkeypatch):
    folder = write_crop(tmp_path / "dem")
    monkeypatch.setenv("BANJIR_DEM_DIR", str(folder))
    return folder


def test_height_value_keeps_zero_and_negatives_and_drops_no_data():
    assert [elevation.height_value(v) for v in (12.36, 0.0, -2.345, -0.04, -9999.0, -9998.5, math.nan, math.inf)] == \
           [12.4, 0.0, -2.3, 0.0, None, None, None, None]
    assert math.copysign(1, elevation.height_value(-0.04)) == 1   # never "-0.0" in an answer


def test_a_spot_gives_ground_and_height_above_the_river(dem):
    assert elevation.at(*centre(5, 7)) == {"ground_m": 10.7, "above_river_m": 3.7}
    assert elevation.at(*centre(0, 1)) == {"ground_m": 0.0, "above_river_m": -7.0}
    assert elevation.at(*centre(0, 2)) == {"ground_m": -2.3, "above_river_m": -9.3}   # negatives are kept
    assert elevation.at(*centre(0, 5)) == {"ground_m": 12.4, "above_river_m": 5.4}


def test_no_river_within_reach_is_null_and_no_surface_is_no_answer(dem):
    assert elevation.at(*centre(*NO_RIVER)) == {"ground_m": 6.1, "above_river_m": None}
    assert elevation.at(*centre(0, 0)) is None    # no data
    assert elevation.at(*centre(0, 3)) is None    # NaN


def test_outside_every_crop_is_none(dem, monkeypatch):
    south = ORIGIN[1] - ROWS * PIXEL
    assert elevation.at(south - 0.01, ORIGIN[0] + 1) is None
    assert elevation.at(ORIGIN[1] - 1, ORIGIN[0] + COLS * PIXEL) is None    # the east edge is outside
    monkeypatch.setenv("BANJIR_DEM_DIR", str(dem / "missing"))
    assert elevation.at(*centre(5, 7)) is None


def test_a_second_crop_is_read_where_the_first_does_not_reach(dem):
    write_crop(dem, "east-area", origin=(ORIGIN[0] + COLS * PIXEL, ORIGIN[1]))
    elevation.crops.cache_clear()
    lat, lon = centre(5, 7)
    assert elevation.at(lat, lon + COLS * PIXEL) == elevation.at(lat, lon) == {"ground_m": 10.7, "above_river_m": 3.7}


def test_one_file_of_two_or_two_grids_are_refused(tmp_path):
    with pytest.raises(raster.RasterError, match="no above_river file"):
        elevation.load(write_crop(tmp_path / "one", layers=("surface",)))
    folder = write_crop(tmp_path / "two")
    gw.write_tiff(folder / "test-area_above_river.tif", [[1.0] * COLS for _ in range(ROWS)], tile=TILE,
                  origin=(ORIGIN[0] + 1, ORIGIN[1]), pixel=(PIXEL, PIXEL), padding=-9999.0)
    with pytest.raises(raster.RasterError, match="do not share one grid"):
        elevation.load(folder)
    assert elevation.load(tmp_path / "none") == ()


def test_a_damaged_file_logs_its_name_and_tile_but_never_the_point(tmp_path, monkeypatch, caplog):
    folder = write_crop(tmp_path / "broken", chunks={0: b"not deflate data"})
    monkeypatch.setenv("BANJIR_DEM_DIR", str(folder))
    lat, lon = centre(3, 4)
    with caplog.at_level(logging.DEBUG, logger="banjir"):
        assert elevation.at(lat, lon) is None
    assert "test-area_surface.tif: tile 0" in caplog.text
    assert (lat, lon) == (9.125, 101.125)
    assert not re.search(r"9\.12|101\.12", caplog.text)


def test_a_point_carries_the_height_at_its_squares_centre(dem, tmp_path, monkeypatch):
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(fx.write_depth_set(tmp_path / "rasters")))
    place = places.point(*centre(14, 4))   # inside the Peninsula box, wet in the depth fixture
    assert place["elevation"] == elevation.at(*places.parse_point_id(place["id"])) == {"ground_m": 19.4,
                                                                                      "above_river_m": 12.4}


# --- the committed crops ---

def shipped() -> dict[str, tuple[int, str]]:
    """{file: (bytes, SHA-256)} as app/data/dem/SOURCES.txt lists them."""
    text = (DEM / "SOURCES.txt").read_text(encoding="utf-8")
    return {name: (int(size), digest) for name, size, digest in
            re.findall(r"File:\s+(\S+\.tif)\nBytes:\s+(\d+)\nSHA-256:\s+([0-9a-f]{64})", text)}


def test_the_committed_crops_are_the_ones_sources_lists():
    listed = shipped()
    assert sorted(listed) == sorted(p.name for p in DEM.glob("*.tif")) == ["shah-alam_above_river.tif",
                                                                          "shah-alam_surface.tif"]
    for name, (size, digest) in listed.items():
        data = (DEM / name).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (size, digest), name
    assert sum(size for size, _ in listed.values()) < 4_000_000   # small enough to keep in git


@pytest.fixture
def real_dem(monkeypatch):
    """The committed crops, with the premises read afresh so no other test's folder lingers in them."""
    monkeypatch.delenv("BANJIR_DEM_DIR", raising=False)
    areas.premises.cache_clear()
    areas._businesses.cache_clear()


@pytest.mark.parametrize(("spot", "lat", "lon", "ground", "river"), [
    ("Taman Sri Muda", 3.0249, 101.5325, 6.5, 3.5),
    ("Bukit Sapu Tangan, 204 m on OpenStreetMap", 3.1145919, 101.4983917, 216.8, 178.7),
    ("Bukit Nibung Gila, 120 m on OpenStreetMap", 3.1451708, 101.5584969, 118.6, 105.2),
    ("Bukit Lipat Kajang, 64 m on OpenStreetMap", 3.0247514, 101.4458931, 65.2, 57.9),
])
def test_known_spots_in_shah_alam(real_dem, spot, lat, lon, ground, river):
    assert elevation.at(lat, lon) == {"ground_m": ground, "above_river_m": river}, spot


def test_the_shah_alam_crop_covers_its_box_and_stops_there(real_dem):
    for lat, lon in ((2.95, 101.43), (3.23, 101.59), (2.95, 101.59), (3.23, 101.43)):
        assert elevation.at(lat, lon) is not None
    assert elevation.at(3.8077, 103.326) is None    # Kuantan
    assert elevation.at(3.27, 101.51) is None       # past the 2 km margin


def test_premises_carry_elevation_where_it_is_loaded_and_null_elsewhere(real_dem):
    sri_muda = areas.premises("sri-muda")
    assert all(set(p["elevation"]) == {"ground_m", "above_river_m"} for p in sri_muda)
    assert sri_muda[0]["elevation"] == {"ground_m": 12.6, "above_river_m": 8.0}
    assert all(p["elevation"] is None for p in areas.premises("kuantan"))
    found = places.resolve(sri_muda[0]["id"])
    assert found["elevation"] == sri_muda[0]["elevation"]
