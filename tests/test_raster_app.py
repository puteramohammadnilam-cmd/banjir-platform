"""Plan card A1, the reader as the app uses it: error classes and HTTP statuses, threads, cold start and the log.

Fixture rasters through BANJIR_RASTER_DIR, so every number is known. The core of the reader is in tests/test_raster.py.
Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_raster_app.py
"""
import logging
import re
import sys
import threading
import time
from array import array
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tiff_fixture as fx
from app import main, raster

GRID = "N10_E100"
TILE_0 = (6.4321, 101.1987)       # fixture row 14, column 4: tile 0, inside the Peninsula box
TILE_1 = (6.4321, 104.1)          # row 14, column 16: tile 1
TILE_2 = (6.4321, 109.6)          # row 14, column 38: tile 2, inside the Borneo box
POINT_ID = "pt:6.37500,101.12500"
MODEL_DOWN = "Could not read the flood model just now. Try again."
POINT_WORDS = "Please check the location and try again."
RP100 = f"ID211_{GRID}_RP100_depth.tif"
THREADS = 16


@pytest.fixture(autouse=True)
def fresh_set():
    """No set loaded when a test starts and none left behind: the public reset, not a private helper."""
    raster.depth_set.cache_clear()
    yield
    raster.depth_set.cache_clear()


@pytest.fixture
def rasters(tmp_path, monkeypatch):
    folder = fx.write_depth_set(tmp_path / "rasters")
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(folder))
    return folder


@pytest.fixture
def client(rasters):
    main._hits.clear()
    return TestClient(main.app)


@pytest.fixture
def damaged(rasters):
    """Files that load, one of whose tiles (the 100 year file's tile 0) is not deflate data: found only when read."""
    fx.write_depth_tiff(rasters / RP100, fx.depth_values(100), chunks={0: b"not deflate data"})
    main._hits.clear()
    return TestClient(main.app)


def post_point(client, lat, lon):
    return client.post("/api/point", json={"lat": lat, "lon": lon, "source": "pin"})


# --- damaged or unreadable data is a RasterError and a 503; a bad argument is a ValueError and a 422 ---

@pytest.fixture
def loaded(rasters):
    return raster.DepthSet.load(rasters)


def test_damaged_data_is_not_a_value_error_and_a_bad_argument_is_not_damaged_data(loaded):
    assert issubclass(raster.RasterError, Exception) and not issubclass(raster.RasterError, ValueError)
    for bad_call in (lambda: loaded.block(GRID, 0, 0, 0), lambda: loaded.view_cells((1.0, 1.0, 0.0, 0.0))):
        with pytest.raises(ValueError) as caught:
            bad_call()
        assert not isinstance(caught.value, raster.RasterError)


@pytest.mark.parametrize("name, words", [
    ("missing.tif", r"cannot be read \(No such file or directory\)$"),
    ("folder.tif", ""),     # a folder: the read fails, or the folder is too short to hold a header
])
def test_a_file_that_cannot_be_read_is_a_raster_error_naming_it_not_an_os_error(tmp_path, name, words):
    (tmp_path / "folder.tif").mkdir()
    with pytest.raises(raster.RasterError, match=rf"^{re.escape(name)}: {words}") as caught:
        raster.DepthFile.open(tmp_path / name)
    assert not isinstance(caught.value, (OSError, ValueError))


def test_a_folder_that_cannot_be_listed_or_a_file_that_cannot_be_hashed_is_a_raster_error(rasters, monkeypatch):
    def refuse_the_folder(self):
        raise PermissionError(13, "Permission denied")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_dir", refuse_the_folder)
        with pytest.raises(raster.RasterError, match=r"^rasters: cannot be listed \(Permission denied\)$"):
            raster.DepthSet.load(rasters)

    def fail_to_read(stream, algorithm):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(raster.hashlib, "file_digest", fail_to_read)
    unreadable = r"^ID211_N10_E100_RP\d+_depth\.tif: cannot be read \(Input/output error\)$"
    with pytest.raises(raster.RasterError, match=unreadable):
        raster.DepthSet.load(rasters)


WHILE_SERVING = [
    pytest.param("post", "/api/point", {"lat": TILE_0[0], "lon": TILE_0[1], "source": "pin"}, id="point"),
    pytest.param("post", "/api/estimate", {"place": POINT_ID}, id="estimate"),
    pytest.param("post", "/api/ask", {"question": "Is it safe?", "place": POINT_ID}, id="ask"),
]


@pytest.mark.parametrize("method, path, body", WHILE_SERVING)
def test_a_damaged_tile_met_while_serving_is_a_503_in_the_envelope(damaged, caplog, method, path, body):
    res = damaged.request(method, path, json=body)
    assert res.status_code == 503
    assert res.json() == {"success": False, "data": None, "error": MODEL_DOWN}
    assert f"{RP100}: tile 0" in caplog.text and "6.43" not in caplog.text and "101.19" not in caplog.text


def test_a_damaged_tile_beside_a_point_costs_only_the_squares_around_it(rasters, caplog):
    # A point is checked with the squares around it, so the tiles of its blocks are read too. Tile 2 (rows 0 to 15,
    # columns 32 to 47) is in the blocks of a point from column 12 on, and not in those of one in columns 0 to 11. The
    # point's own square is sound, so its depths still come back; the squares around it are null, not a partial set
    # that would look like dry land, and the page says they could not load.
    fx.write_depth_tiff(rasters / RP100, fx.depth_values(100), chunks={2: b"not deflate data"})
    main._hits.clear()
    client = TestClient(main.app)
    near = post_point(client, *TILE_0)    # column 4: blocks over columns 0 to 23
    assert near.status_code == 200 and near.json()["data"]["cells"]
    assert near.json()["data"]["place"]["depth_m"] == {"10": 14.14, "100": 14.64, "500": 15.14}
    far = post_point(client, *TILE_1)     # column 16: blocks over columns 0 to 39
    assert far.status_code == 200
    data = far.json()["data"]
    assert data["coverage"] == "covered" and data["place"]["id"] and data["place"]["depth_m"]["100"] is not None
    assert data["blocks"] is None and data["cells"] is None
    assert f"{RP100}: tile 2" in caplog.text and "6.43" not in caplog.text and "104.1" not in caplog.text


def test_a_damaged_tile_under_the_point_itself_is_still_a_503(damaged):
    res = post_point(damaged, *TILE_0)    # tile 0 holds the point's own square
    assert res.status_code == 503 and res.json() == {"success": False, "data": None, "error": MODEL_DOWN}


def test_a_file_that_goes_missing_while_serving_is_a_503_in_the_envelope(client, rasters, caplog):
    assert post_point(client, *TILE_0).status_code == 200      # loads the set, and reads tiles 0 and 1 of each file
    (rasters / RP100).unlink()
    res = post_point(client, *TILE_2)                          # its own square is in tile 2, not cached: opened now
    assert res.status_code == 503 and res.json() == {"success": False, "data": None, "error": MODEL_DOWN}
    assert f"{RP100}: tile 2 cannot be read" in caplog.text


def test_damaged_flood_data_met_inside_an_ai_call_is_a_503_not_a_502(client, monkeypatch):
    def breaks(*args):
        raise raster.RasterError(f"{RP100}: tile 0 is not deflate data")

    monkeypatch.setattr(main.ai, "ask", breaks)
    res = client.post("/api/ask", json={"question": "Is it safe?"})
    assert res.status_code == 503 and res.json() == {"success": False, "data": None, "error": MODEL_DOWN}


BAD_INPUT = [
    pytest.param("post", "/api/point", {"lat": "north", "lon": 101.0, "source": "pin"}, POINT_WORDS, id="point body"),
    pytest.param("post", "/api/estimate", {"place": "pt:abc"}, POINT_WORDS, id="point id"),
]


@pytest.mark.parametrize("model", ["sound", "damaged"])
@pytest.mark.parametrize("method, path, body, words", BAD_INPUT)
def test_bad_input_is_a_422_in_the_envelope_with_the_model_sound_or_damaged(request, model, method, path, body, words):
    client = request.getfixturevalue("client" if model == "sound" else "damaged")
    res = client.request(method, path, json=body)
    assert res.status_code == 422 and res.json() == {"success": False, "data": None, "error": words}


def test_a_point_id_that_is_not_the_one_the_server_gives_out_is_a_422(client):
    res = client.post("/api/estimate", json={"place": "pt:6.37501,101.12500"})
    assert res.status_code == 422 and res.json()["error"] == POINT_WORDS


# --- threads ---

@pytest.fixture
def switching_every_microsecond():
    """Threads give way to each other about every microsecond, so a missing lock shows within a few rounds."""
    before = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(before)


def run_together(work, threads: int = THREADS) -> list[BaseException]:
    """Run work(n) for each n below `threads`, on that many threads let go together; the exceptions they raised."""
    errors: list[BaseException] = []
    start = threading.Barrier(threads)

    def runner(n: int) -> None:
        start.wait()
        try:
            work(n)
        except BaseException as error:   # whatever it is, the test reports it
            errors.append(error)

    pool = [threading.Thread(target=runner, args=(n,)) for n in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()
    return errors


class YieldingKey(int):
    """A cache key whose hash gives up the GIL, as a real key's never does. The pause between the two steps of a
    cache call (look the key up, then move it to the end) is long enough for another thread to evict the key in it."""

    def __hash__(self) -> int:
        time.sleep(0)
        return super().__hash__()


@pytest.mark.parametrize("limit", [1, 4])
def test_sixteen_threads_hammering_the_tile_cache_get_no_key_error_and_right_tiles(switching_every_microsecond, limit):
    cache = raster.TileCache(limit=limit)
    keys = [YieldingKey(n) for n in range(limit + 2)]   # always more keys than room, so rounds keep evicting
    tiles = [array("f", [n]) for n in range(len(keys))]

    def hammer(n: int) -> None:
        for step in range(250):
            i = (n * 3 + step) % len(keys)
            found = cache.get(keys[i])
            assert found is None or found is tiles[i]   # a hit is this key's tile, never another's
            if found is None:
                cache.put(keys[i], tiles[i])

    assert run_together(hammer) == []
    assert len(cache) <= limit


def test_sixteen_threads_reading_squares_through_a_one_tile_cache_get_right_depths(
        rasters, switching_every_microsecond):
    small = raster.DepthSet.load(rasters, cache_tiles=1)       # nearly every read is a miss: decoded, put, evicted
    cells = [(2, 3), (2, 20), (2, 35), (20, 20), (19, 33), (14, 4)]
    want = {cell: {str(rp): round(cell[0] + cell[1] / 100 + 0.1 + fx.RP_EXTRA[rp], 2) for rp in fx.RETURN_PERIODS}
            for cell in cells}
    centres = {cell: small.grids[0].centre(*cell) for cell in cells}

    def hammer(n: int) -> None:
        for step in range(8):
            cell = cells[(n + step) % len(cells)]
            assert small.depths(*centres[cell]) == want[cell]

    assert run_together(hammer) == []
    assert len(small.cache) <= 1


# --- the app's cached set: one load at a cold start, a public reset, the log ---

def test_threads_arriving_together_at_a_cold_start_load_the_set_once(rasters, monkeypatch):
    loads, found = [], []
    real_load = raster.DepthSet.load.__func__

    def slow_load(cls, *args, **kwargs):
        loads.append(args)
        time.sleep(0.05)     # long enough for every thread to be waiting when the first one is done
        return real_load(cls, *args, **kwargs)

    monkeypatch.setattr(raster.DepthSet, "load", classmethod(slow_load))
    assert run_together(lambda n: found.append(raster.depth_set()), threads=8) == []
    assert len(loads) == 1 and len(found) == 8 and len({id(one) for one in found}) == 1


def test_cache_clear_makes_the_next_call_read_the_folder_again(rasters):
    first = raster.depth_set()
    assert raster.depth_set() is first
    raster.depth_set.cache_clear()
    again = raster.depth_set()
    assert again is not first and [g.name for g in again.grids] == [GRID]


def test_a_failed_load_is_not_kept_so_repaired_files_load_without_a_restart(rasters):
    good = (rasters / RP100).read_bytes()
    fx.write_depth_tiff(rasters / RP100, fx.depth_values(100), tags={339: (fx.SHORT, (1,))})
    for _ in range(2):
        with pytest.raises(raster.RasterError, match="SampleFormat"):
            raster.depth_set()
    (rasters / RP100).write_bytes(good)
    assert [g.name for g in raster.depth_set().grids] == [GRID]


def test_only_a_few_folders_stay_loaded(tmp_path, monkeypatch):
    def load(name: str):
        monkeypatch.setenv("BANJIR_RASTER_DIR", str(tmp_path / name))
        return raster.depth_set()

    first = load("0")
    for name in "12345":
        load(name)
    assert load("0") is not first    # the oldest of six was dropped to keep the set small


def test_a_missing_raster_folder_is_logged_once_and_never_with_a_coordinate(tmp_path, monkeypatch, caplog):
    gone = tmp_path / "gone"
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(gone))
    main._hits.clear()
    with caplog.at_level(logging.WARNING, logger="banjir"):
        sets = [raster.depth_set() for _ in range(3)]
        reply = post_point(TestClient(main.app), *TILE_0).json()["data"]
    assert sets[0].grids == () and sets[0] is sets[1] is sets[2]       # the empty set is kept, as before
    assert reply == {"coverage": "not_loaded", "region": "peninsula", "place": None}
    warned = [record for record in caplog.records if record.name == "banjir"]
    assert [record.levelno for record in warned] == [logging.WARNING]
    assert f"{gone} does not exist" in warned[0].getMessage()
    assert "6.43" not in caplog.text and "101.19" not in caplog.text


def test_a_folder_without_depth_files_is_logged_too_and_a_good_one_is_not(tmp_path, monkeypatch, caplog):
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(tmp_path / "empty"))
    with caplog.at_level(logging.WARNING, logger="banjir"):
        raster.depth_set()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert f"{tmp_path / 'empty'} holds no depth files" in caplog.records[0].getMessage()
    caplog.clear()
    monkeypatch.setenv("BANJIR_RASTER_DIR", str(fx.write_depth_set(tmp_path / "good")))
    with caplog.at_level(logging.WARNING, logger="banjir"):
        raster.depth_set()
    assert caplog.records == []
