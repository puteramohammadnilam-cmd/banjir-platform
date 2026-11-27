"""tools/outline_squares.py: squares counted and drawn per outline straight from the depth files, on the fixture rasters
against a square-by-square count with app/geo.py, through tools/area_sections.py for an area with no stored squares,
and, when the raw sections and the rasters are here, against the city's built sections.json.

Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_outline_squares.py
"""
import json
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

import tiff_fixture as fx
from app import geo, raster

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import area_sections as asec  # noqa: E402
import outline_squares as osq  # noqa: E402
import sections_io  # noqa: E402
from test_area_sections import SECTIONS, built  # noqa: E402,F401  (built: the city fixture)

RPS = ("10", "20", "50")


def outline(sid, *rings, multi=False):
    closed = [[*ring, ring[0]] for ring in rings]
    geometry = {"type": "MultiPolygon", "coordinates": [[ring] for ring in closed]} if multi else \
        {"type": "Polygon", "coordinates": closed}
    return {"id": sid, "name": sid.title(), "geometry": geometry, "bbox": geo.bbox(geometry)}


def box(west, south, east, north):
    return [(west, south), (east, south), (east, north), (west, north)]


# a triangle over the special values of row 0; a box with a hole over the empty tile and the partial tiles; two
# separate parts; and a box after the triangle that it overlaps, which only gets what the triangle leaves
OUTLINES = [
    outline("tri", [(100.1, 9.9), (104.9, 9.6), (101.3, 6.1)]),
    outline("holed", box(103.0, 3.0, 109.6, 7.4), box(104.2, 4.2, 106.8, 6.3)),
    outline("parts", box(100.2, 2.6, 102.2, 5.2), box(106.0, 8.0, 108.4, 9.8), multi=True),
    outline("late", box(100.6, 7.0, 103.4, 9.2)),
]


@pytest.fixture
def depths(tmp_path):
    return raster.DepthSet.load(fx.write_depth_set(tmp_path / "r"))


def by_hand(depth_set, outlines):
    """Each square of the grid to the first outline holding its centre (app/geo.py), with its wet flood sizes."""
    grid = depth_set.grids[0]
    found = {o["id"]: {"cells": 0, "wet_cells": dict.fromkeys(RPS, 0), "squares": {}} for o in outlines}
    for row in range(grid.rows):
        for col in range(grid.cols):
            home = geo.containing(*grid.centre(row, col), outlines)
            if home:
                counts = found[home["id"]]
                counts["cells"] += 1
                wet = depth_set.depths(*grid.centre(row, col))
                counts["squares"][(row, col)] = wet
                for rp in RPS:
                    counts["wet_cells"][rp] += 1 if wet[rp] else 0
    return found


def test_the_counts_match_a_square_by_square_count_with_the_first_outline_winning(depths):
    scanned = {item["id"]: item for item in osq.scan(depths, OUTLINES)}
    expected = by_hand(depths, OUTLINES)
    for sid, counts in expected.items():
        assert scanned[sid]["counts"] == {"cells": counts["cells"], "wet_cells": counts["wet_cells"]}, sid
        assert counts["cells"] > 0, f"{sid} holds squares in the fixture"
    assert expected["late"]["cells"] < len([1 for row in range(30) for col in range(40)
                                            if geo.point_in_geometry(*depths.grids[0].centre(row, col), OUTLINES[3]["geometry"])])


def test_each_picture_square_is_its_depth_step_inside_and_clear_elsewhere(depths):
    expected = by_hand(depths, OUTLINES)
    for item in osq.scan(depths, OUTLINES):
        top, left, bottom, right = item["extent"]
        width = right - left + 1
        mine = expected[item["id"]]["squares"]
        assert (top, left, bottom, right) == (min(r for r, _ in mine), min(c for _, c in mine), max(r for r, _ in mine),
                                             max(c for _, c in mine))
        for rp in RPS:
            for row in range(top, bottom + 1):
                for col in range(left, right + 1):
                    metres = mine.get((row, col), {}).get(rp)
                    want = osq.depth_class(metres) if metres else 0
                    assert item["classes"][rp][(row - top) * width + col - left] == want, (item["id"], rp, row, col)


def test_depth_steps_follow_the_maps_ramp():
    assert [osq.depth_class(m) for m in (0.01, 0.49, 0.5, 0.99, 1, 1.99, 2, 2.99, 3, 12)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]


def test_the_palettes_and_steps_are_the_maps_own():
    source = (ROOT / "app" / "static" / "js" / "map-gl-data.js").read_text(encoding="utf-8")
    body = source[source.index("export function depthRamp"):]
    dark, light = re.findall(r"\[(\"#[0-9a-f]{6}\"[^\]]*)\]", body[:body.index("return")])
    for theme, found in (("dark", dark), ("light", light)):
        parts = [part.strip() for part in found.split(",")]
        assert tuple(json.loads(p) for p in parts[0::2]) == osq.PALETTES[theme]
        assert tuple(float(p) for p in parts[1::2]) == tuple(float(s) for s in osq.STEPS_M)
    assert '"step", ["get", `d${rp}`], "rgba(0,0,0,0)", 0,' in body, "the first colour starts at any water"


def png(path):
    """(rows of indices, palette bytes, tRNS bytes) of an 8-bit indexed PNG with no filters, as png_write writes."""
    data, at, idat, chunks = path.read_bytes(), 8, b"", {}
    while at < len(data):
        (size,), kind = struct.unpack(">I", data[at:at + 4]), data[at + 4:at + 8]
        body, at = data[at + 8:at + 8 + size], at + 12 + size
        if kind == b"IDAT":
            idat += body
        else:
            chunks[kind] = body
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    raw = zlib.decompress(idat)
    return [raw[r * (width + 1) + 1:(r + 1) * (width + 1)] for r in range(height)], chunks[b"PLTE"], chunks[b"tRNS"]


def test_the_pictures_and_their_json_hold_the_bounds_sizes_hashes_and_colours(depths, tmp_path):
    scanned = osq.scan(depths, OUTLINES)
    doc = osq.write_pictures(tmp_path / "out", scanned, depths.grids[0])
    assert json.loads((tmp_path / "out" / "flood_pictures.json").read_text()) == doc
    grid = depths.grids[0]
    for item, entry in zip(scanned, doc["outlines"]):
        top, left, bottom, right = item["extent"]
        assert entry["bounds"] == [grid.x0 + left * fx.PIXEL, grid.y0 - (bottom + 1) * fx.PIXEL,
                                   grid.x0 + (right + 1) * fx.PIXEL, grid.y0 - top * fx.PIXEL]
        assert (entry["width"], entry["height"]) == (right - left + 1, bottom - top + 1)
        assert entry["counts"] == item["counts"]
        for rp in RPS:
            for theme, colours in osq.PALETTES.items():
                file = entry["files"][rp][theme]
                rows, palette, alpha = png(tmp_path / "out" / file["file"])
                assert b"".join(rows) == bytes(item["classes"][rp])
                assert palette == bytes(3) + b"".join(bytes.fromhex(c[1:]) for c in colours)
                assert alpha == b"\x00", "index 0, dry or outside, is clear; the steps are solid"
                assert file["file"] == f"{item['id']}_rp{rp}_{theme}.png"
    again = osq.write_pictures(tmp_path / "again", osq.scan(depths, OUTLINES), grid)
    assert again["outlines"] == doc["outlines"], "the same input gives the same bytes"


def test_outlines_outside_one_loaded_grid_are_refused(depths):
    with pytest.raises(ValueError, match="one loaded depth grid"):
        osq.scan(depths, [outline("past", box(109.0, 3.0, 111.0, 4.0))])


def test_an_outline_that_holds_no_square_centre_has_no_extent_and_no_picture(depths, tmp_path):
    thin = outline("thin", box(100.26, 9.0, 100.36, 9.5))   # between two columns' centres (100.125 and 100.375)
    item = osq.scan(depths, [thin])[0]
    assert item["counts"] == {"cells": 0, "wet_cells": dict.fromkeys(RPS, 0)} and item["extent"] is None
    entry = osq.write_pictures(tmp_path, [item], depths.grids[0])["outlines"][0]
    assert entry["bounds"] is None and entry["files"] == {}


@pytest.mark.parametrize("spans, taken, left", [
    ([(0, 10)], [], [(0, 10)]),
    ([(0, 10)], [(2, 4), (6, 7)], [(0, 2), (4, 6), (7, 10)]),
    ([(0, 10), (12, 15)], [(5, 13)], [(0, 5), (13, 15)]),
    ([(3, 5)], [(0, 9)], []),
    ([(3, 5)], [(5, 9)], [(3, 5)]),
])
def test_subtract_keeps_what_is_not_taken(spans, taken, left):
    assert osq.subtract(spans, taken) == left


def test_an_area_with_no_stored_squares_gets_the_same_section_counts_from_the_depth_files(built):
    premises, town, depth_set = built
    stored = asec.build(premises, town, SECTIONS, depth_set)
    scanned = asec.build(premises, {**town, "cells": []}, SECTIONS, depth_set, scan=True)
    assert scanned["sections"] == stored["sections"] and scanned["city"] == stored["city"]
    assert scanned["outside_sections"] is None and stored["outside_sections"]["cells"] > 0
    dry = asec.build(premises, town, SECTIONS, depth_set)
    assert dry["outside_sections"] == stored["outside_sections"], "without --scan, the stored squares, as before"


def test_an_open_ring_is_named_by_its_outline(depths):
    geometry = {"type": "Polygon", "coordinates": [[(100.1, 9.9), (104.9, 9.6), (101.3, 6.1)]]}   # not closed
    with pytest.raises(ValueError, match="^open: .*odd number"):
        osq.scan(depths, [{"id": "open", "name": "Open", "geometry": geometry, "bbox": geo.bbox(geometry)}])


def test_pictures_from_an_earlier_run_that_are_no_longer_listed_are_removed(depths, tmp_path):
    osq.write_pictures(tmp_path, osq.scan(depths, OUTLINES), depths.grids[0])
    doc = osq.write_pictures(tmp_path, osq.scan(depths, OUTLINES[:1]), depths.grids[0])
    listed = {f["file"] for o in doc["outlines"] for rp in o["files"].values() for f in rp.values()}
    assert {p.name for p in tmp_path.glob("*.png")} == listed and len(listed) == 6


RAW_SECTIONS = sections_io.default_path()
CITY_SECTIONS = ROOT / "app" / "data" / "areas" / "shah-alam" / "sections.json"


@pytest.mark.skipif(not (RAW_SECTIONS.is_file() and CITY_SECTIONS.is_file() and raster.depth_set().layers),
                    reason="the raw sections, the built city or the depth files are not here")
def test_the_city_sections_get_the_counts_its_built_sections_json_holds():
    scanned = {item["id"]: item["counts"] for item in osq.scan(raster.depth_set(), sections_io.load_sections(), pictures=False)}
    built = json.loads(CITY_SECTIONS.read_text(encoding="utf-8"))["sections"]
    assert {s["id"]: {"cells": s["counts"]["cells"], "wet_cells": s["counts"]["wet_cells"]} for s in built} == scanned
