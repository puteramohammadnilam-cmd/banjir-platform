"""Small flash flood potential files for the tests of app/indexes.py, every number known. Standard library only.

Two grids, so a test can ask about a place in either the flood model fixture (tests/tiff_fixture.py) or the made-up city
(tests/sectioned_fixture.py):

    DEPTH_GRID  20 x 24 squares of 0.25 degrees from (100.0, 10.0): the flood model fixture's origin and pixel size
    CITY_GRID   6 x 6 squares of 0.01 degrees from (101.5, 3.06): the made-up city's box

A square's score is `score(row, col)`, 1.0 to 9.9 in steps of 0.1, except the squares of SPECIAL on the first row:
no data, scores exactly on each break (3.5, 6.0, 8.0), one step under the first, NaN and 10.0. A score on a break is in
the class above it (app/indexes.py), so the two sides of every edge are checked.

    write_set(folder, name="test-area", grid=DEPTH_GRID)    # test-area_ffpi.{tif,png,json}
    write_indexes(folder, section_ids)                      # indexes.json for a made-up city's sections
"""
from __future__ import annotations

import json
import math
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import geotiff_write as gw  # noqa: E402

DEPTH_GRID = {"origin": (100.0, 10.0), "pixel": 0.25, "rows": 20, "cols": 24}
CITY_GRID = {"origin": (101.5, 3.06), "pixel": 0.01, "rows": 6, "cols": 6}
TILE = 16
CLASSES = ["low", "medium", "high", "extreme"]
BREAKS = [3.5, 6.0, 8.0]
CREDIT = "Fixture credit for the map layer."
NODATA = -9999.0
SPECIAL = {(0, 0): NODATA, (0, 1): 3.5, (0, 2): 6.0, (0, 3): 8.0, (0, 4): 3.4, (0, 5): math.nan, (0, 6): 10.0}


def score(row: int, col: int) -> float:
    """The square's score: its own, 1.0 to 9.9, so a hand check needs no table."""
    return SPECIAL.get((row, col), round(1 + ((row * 7 + col * 3) % 90) * 0.1, 1))


FLASH_METHOD = {"name": "Flash Flood Potential Index (FFPI)", "formula": "(1.5 M + L + S + 0.5 V) / 4",
                "summary": "Each square rated 1 to 10 for slope, land cover, soil and vegetation, then weighted.",
                "factors": {"M": "slope"}, "classes": "Four equal steps of the 1-10 scale.",
                "citations": ["Smith, G. (2003)", "Yassin, N. A. M. et al. (2023)"],
                "deviations": ["Slope 27 to 30 percent is not rated in the paper: put in 9."],
                "not": "A susceptibility to flash floods, not a water depth and not a chance of flooding."}


def ffpi_json(grid: dict = DEPTH_GRID, **changes) -> dict:
    """The fixture's name.json: the classes, the breaks between them (one fewer than the classes), the credit, the
    grid's bounds and the method."""
    west, north = grid["origin"]
    edge = grid["pixel"]
    return {"classes": CLASSES, "breaks": BREAKS, "credit": CREDIT, "method": FLASH_METHOD,
            "bounds": [west, north - grid["rows"] * edge, west + grid["cols"] * edge, north], **changes}


def centre(row: int, col: int, grid: dict = DEPTH_GRID) -> tuple[float, float]:
    """(lat, lon) of a square's centre."""
    west, north = grid["origin"]
    return north - (row + 0.5) * grid["pixel"], west + (col + 0.5) * grid["pixel"]


def png_bytes() -> bytes:
    """A real 1 x 1 indexed PNG with one transparent entry, as the build writes the layer."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", 1, 1, 8, 3, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"PLTE", b"\x00\x00\x00") + chunk(b"tRNS", b"\x00")
            + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b""))


def write_set(folder: Path, name: str = "test-area", grid: dict = DEPTH_GRID, files=("tif", "png", "json"),
              meta: dict | None = None, **tiff_options) -> Path:
    """The named files of one area into folder (made if need be); `meta` replaces the JSON's fields, a JSON string
    is written as it is, and `tiff_options` go to geotiff_write.write_tiff (a damaged tile, say)."""
    folder.mkdir(parents=True, exist_ok=True)
    if "tif" in files:
        rows = [[score(r, c) for c in range(grid["cols"])] for r in range(grid["rows"])]
        gw.write_tiff(folder / f"{name}_ffpi.tif", rows, tile=TILE, origin=grid["origin"],
                      pixel=(grid["pixel"], grid["pixel"]), padding=NODATA, **tiff_options)
    if "png" in files:
        (folder / f"{name}_ffpi.png").write_bytes(png_bytes())
    if "json" in files:
        text = meta if isinstance(meta, str) else json.dumps(ffpi_json(grid, **(meta or {})))
        (folder / f"{name}_ffpi.json").write_text(text, encoding="utf-8")
    return folder


SHARE = {"low": 0.4, "medium": 0.3, "high": 0.2, "extreme": 0.1}
SCORE_CLASSES = ["very_low", "low", "moderate", "high", "very_high"]
RATINGS = {"slope": 3.0, "elevation": 2.0}


def section_figures(value: float) -> dict:
    """One section's entry in indexes.json."""
    return {"flash": {"mean": round(4.0 + value, 1), "share": dict(SHARE)},
            "score": {"value": value, "class": "moderate", "ratings": dict(RATINGS)}}


def indexes_doc(section_ids, **changes) -> dict:
    """indexes.json for the sections, as the data contract gives it: figures for each section and the city, the
    method (flash, whose breaks are the files', and score) and the validation."""
    found = {sid: section_figures(2.0 + index / 10) for index, sid in enumerate(section_ids)}
    return {"version": 1, "area": "test-city",
            "method": {"flash": {"source": "test-city_ffpi.json", "classes": CLASSES, "breaks": BREAKS,
                                 "per_section": "Mean score and share of the section's land squares."},
                       "score": {"name": "Flood risk score (multi-criteria)", "summary": "Seven criteria, rated 1 to 5.",
                                 "criteria": [{"id": "slope", "weight": 8, "unit": "%", "breaks": [3, 7],
                                               "ratings": [5, 3, 1], "source": "fixture"}],
                                 "weights_total": 74, "weights_used": {"slope": 0.6, "elevation": 0.4},
                                 "classes": SCORE_CLASSES, "breaks": [1.5, 2.5, 3.5, 4.5],
                                 "break_rule": "A value at or above a break belongs to the class above it.",
                                 "citations": ["Leeonis, A. N. et al. (2024) (criteria weights)"],
                                 "deviations": ["Rainfall was left out: no source varies inside the city."],
                                 "credit": "Fixture score credit: people and drains."}},
            "sections": found,
            "city": section_figures(2.5),
            "validation": {"wording": "Compared with past flood records; this does not validate either index.",
                           "n": len(found), "spearman": {"score_vs_history": 0.12, "flash_vs_history": None},
                           "hotspots": [{"id": "zon-1", "history_events": 9, "score_rank": 20, "flash_rank": 5}]},
            **changes}


def write_indexes(folder: Path, section_ids, **changes) -> Path:
    path = Path(folder) / "indexes.json"
    path.write_text(json.dumps(indexes_doc(section_ids, **changes)), encoding="utf-8")
    return path
