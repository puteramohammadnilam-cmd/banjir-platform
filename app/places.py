"""A place is a mapped business or a point someone picked, addressed by one id string.

    business  "node-11075038761"       (node|way|relation)-digits: an OpenStreetMap business in a listed area
    point     "pt:3.02998,101.53667"   the centre of the 90 m flood model square that holds the point

Both resolve to the same keys (the Place), so the page and the AI tools handle either. A point's Place has is_point
true; name, sector, kind, is_chain, map_last_edited and road null; area_id the listed area whose view holds the
square's centre, or null; section {id, name} of that area's section holding the centre, or null; shelter the nearest
relief centre of that area, or null; elevation (app/elevation.py) at the square's centre as the id gives it, or null;
flash_flood ({score, class}, app/indexes.py) at that centre, or null; cell {grid, row, col, bounds}. A business's Place is its premises.json entry (with the elevation and flash_flood areas.premises adds at
its own point) plus is_point false, its area_id, its section as {id, name} (null in an area not split into sections)
and cell null.

A point in an area split into sections is in that area only when it is in one of its sections (app/sections.py
section_at: in an outline, or within NEAREST_SECTION_M of one); else it is in no listed area there. The section is
worked out here and sent only in POST /api/point's answer, never put in a URL or a log.

Snapping rule. Task A5 repeats it in JavaScript (place.js snapToGrid): change the two together.
  1. Grids: GET /api/coverage `grids`, in the order listed (by name). Each has x0 (west edge) and y0 (north edge)
     in degrees, px (square width, degrees of longitude), py (square height, degrees of latitude), rows and cols.
  2. Square: for (lat, lon) take the first grid where, in double precision and in this order of operations,
         y = (y0 - lat) / py        x = (lon - x0) / px
         0 <= y < rows  and  0 <= x < cols          (false for NaN)
     Then row = floor(y), col = floor(x). With no such grid the point is not covered. A point on a square's edge
     goes to the square east and south of it.
  3. Centre: lon_c = x0 + (col + 0.5) * px  and  lat_c = y0 - (row + 0.5) * py.
  4. Id: "pt:" + lat_c with 5 decimals + "," + lon_c with 5 decimals, no spaces: Python f"{v:.5f}", JavaScript
     v.toFixed(5). Both round the exact double to the nearest; they differ only on an exact tie, and no square
     centre of the JRC N10_E100 grid is one (tests/test_places.py checks every row and column). Malaysia's points
     are never negative, so the id holds no minus sign or "-0.00000".
  5. A Place's lat and lon are the id's two numbers. They lie within 0.000005 degrees (about 0.6 m) of the centre,
     well inside the square, so they snap back to the same square and id: snapping is idempotent. The server accepts
     a point id only in exactly this form, and snaps every point it is sent again.

Coverage: the first region box (REGIONS, checked in order) that holds a spot names its region. For a point a loaded
grid covers, the spot is its square's centre as the id gives it, so a point and its id always agree: a square whose
centre is in no box is "outside" even when the point itself lies just inside one, else "covered". For a point no
loaded grid covers, the spot is the point: "not_loaded" in its region, or "outside". The boxes are coarse: they also
take in Singapore, south Thailand, Brunei and part of Kalimantan.

The squares around a point. check() sends the wet squares of the 2 x 2 blocks of BLOCK_CELLS squares nearest the point's
square with the point (blocks, cells), so the page never asks for a block by its address: a URL naming a block, such as
N10_E100/348/77, names the area (about 2 km) in every server and proxy log, a POST body is not logged.
  1. Blocks: the grid is cut into blocks of BLOCK_CELLS x BLOCK_CELLS squares counted from its north-west corner;
     block (bi, bj) holds rows bi * BLOCK_CELLS up to the next block's, and likewise columns.
  2. Quadrant rule, on each axis: a square in the first half of its block (index mod BLOCK_CELLS under half a block)
     takes its own block and the one before it, else its own and the one after. So the square is always at least half
     a block from the edge of what is sent.
  3. Order: north to south, then west to east. A block before the grid's north or west edge, or past its south or east
     edge (DepthSet.block gives None), is left out; one with no water is kept, with no squares.
  4. cells: the blocks' wet squares in town.json `cells` format, [south, west, depth at 1 in 10, 20, 50], block by
     block. At most 4 x BLOCK_CELLS x BLOCK_CELLS squares.
A covered point always has both keys; a spot that is not_loaded or outside has neither. They are read with the point.
A damaged file tile in the point's own square is a RasterError, a 503, for the check. One in any of the four blocks
costs only the squares: blocks and cells are both null, never a part of them, since squares missing from the map would
look like dry land, and the page says they could not load.

Privacy and terms: this module keeps no point and never imports googlemaps. It logs only a damaged tile's file and
tile number, never a point. Depths are read only for a point a person gave (a pin or GPS) or an OpenStreetMap business,
never for coordinates from Google.
"""

from __future__ import annotations

import copy
import itertools
import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass

from . import areas, elevation, indexes, raster, sections

log = logging.getLogger("banjir")

POINT_ID = re.compile(r"pt:(-?[0-9]{1,2}\.[0-9]{5}),(-?[0-9]{1,3}\.[0-9]{5})")
BUSINESS_ID = re.compile(r"(?:node|way|relation)-[0-9]{1,19}")
POINT_PREFIX = "pt:"
ID_DECIMALS = 5
BOUNDS_DECIMALS = 6          # as the south and west of a square in town.json `cells`
REGIONS = (                  # (id, (west, south, east, north)), checked in this order
    ("langkawi", (99.55, 6.1, 99.97, 6.55)),
    ("peninsula", (99.5, 1.15, 104.7, 6.8)),
    ("borneo", (109.5, 0.8, 119.4, 7.5)),
)
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON_AT_EQUATOR = 111_320.0
MAX_NAME_CHARS = 80
SPACE_CATEGORIES = {"Cc", "Zl", "Zp", "Cs", "Co", "Cn"}   # controls, line breaks and stray code points: a space
DROPPED_CATEGORIES = {"Cf"}                              # format characters (bidi overrides, zero width): removed


class PlaceError(ValueError):
    """No usable place. `reason` is "unknown" (no such business), "malformed" (a point id not in the form snap()
    gives), "outside" (in no region box) or "not_loaded" (in `region`, but no loaded grid covers it). The message is
    only the reason, never the id or a coordinate, so it is safe to log."""

    def __init__(self, reason: str, region: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.region = region


@dataclass(frozen=True)
class Snap:
    """The square holding a point: its id, its exact centre and where it sits in its grid."""

    id: str
    lat: float
    lon: float
    grid: raster.Grid
    row: int
    col: int


def region_at(lat: float, lon: float) -> str | None:
    """The first region box holding the point (edges included), or None."""
    return next((name for name, (west, south, east, north) in REGIONS
                 if west <= lon <= east and south <= lat <= north), None)


def snap(lat: float, lon: float) -> Snap | None:
    """The loaded square holding the point, or None where no loaded grid covers it (the rule in the docstring)."""
    found = raster.depth_set().locate(lon, lat)
    if found is None:
        return None
    grid, row, col = found
    centre_lon, centre_lat = grid.centre(row, col)
    point_id = f"{POINT_PREFIX}{centre_lat:.{ID_DECIMALS}f},{centre_lon:.{ID_DECIMALS}f}"
    return Snap(point_id, centre_lat, centre_lon, grid, row, col)


def point(lat: float, lon: float) -> dict:
    """The Place for the 90 m square holding (lat, lon). PlaceError "outside" when no region box holds the square's
    centre (or, with no loaded square, the point), "not_loaded" (with the region) when no loaded grid covers it."""
    return _located(lat, lon)[0]


def _located(lat: float, lon: float) -> tuple[dict, str]:
    """(Place, region) for the square holding the point; the PlaceErrors of point(). The region is taken from the
    square's centre as its id gives it, the numbers resolve() snaps again, so a point and its id never disagree."""
    found = snap(lat, lon)
    if found is None:
        region = region_at(lat, lon)
        if region is None:
            raise PlaceError("outside")
        raise PlaceError("not_loaded", region)
    region = region_at(*parse_point_id(found.id))
    if region is None:
        raise PlaceError("outside")
    return _point_place(found, raster.depth_set().depths(lon, lat)), region


def _point_place(found: Snap, depth_m: dict) -> dict:
    lat, lon = parse_point_id(found.id)
    area, section = sections.listed_area_at(lat, lon)
    bounds = [round(edge, BOUNDS_DECIMALS) for edge in found.grid.bounds(found.row, found.col)]
    return {"id": found.id, "is_point": True, "name": None, "sector": None, "kind": None, "is_chain": None,
            "lat": lat, "lon": lon, "map_last_edited": None, "area_id": area.id if area else None,
            "section": {"id": section["id"], "name": section["name"]} if section else None,
            "depth_m": depth_m, "road": None, "shelter": nearest_shelter(area, lat, lon) if area else None,
            "elevation": elevation.at(lat, lon), "flash_flood": indexes.flash_at(lat, lon),
            "cell": {"grid": found.grid.name, "row": found.row, "col": found.col, "bounds": bounds}}


def check(lat: float, lon: float) -> dict:
    """POST /api/point's answer: {coverage: covered | not_loaded | outside, region, place}. A covered point's region
    is its square's, the one resolve() gives its id, and the answer also holds the squares around it: `blocks` and
    `cells` (see neighbourhood). The other two answers have neither key."""
    try:
        place, region = _located(lat, lon)
    except PlaceError as error:
        return {"coverage": error.reason, "region": error.region, "place": None}
    return {"coverage": "covered", "region": region, "place": place, **_squares_around(place["cell"])}


def _squares_around(cell: dict) -> dict:
    """neighbourhood(cell), or blocks and cells both null when a tile of the blocks cannot be read (the docstring)."""
    try:
        return neighbourhood(cell)
    except raster.RasterError as error:
        log.error("The flood squares around a point could not be read: %s", error)   # a file and a tile, never a point
        return {"blocks": None, "cells": None}


def is_point_id(ref) -> bool:
    """Whether a reference claims to be a point (it may still be malformed)."""
    return isinstance(ref, str) and ref.startswith(POINT_PREFIX)


def parse_point_id(ref: str) -> tuple[float, float]:
    """(lat, lon) from a point id's two numbers; PlaceError "malformed" unless it has the form and a valid range."""
    match = POINT_ID.fullmatch(ref) if isinstance(ref, str) else None
    if match is None:
        raise PlaceError("malformed")
    lat, lon = float(match[1]), float(match[2])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise PlaceError("malformed")
    return lat, lon


def resolve(ref) -> dict:
    """The Place for an id: a mapped business from any listed area, or a covered point. A point id must be exactly
    the id snap() gives its square, else PlaceError "malformed"; see PlaceError for the other reasons."""
    if is_point_id(ref):
        place = point(*parse_point_id(ref))
        if place["id"] != ref:
            raise PlaceError("malformed")
        return place
    found = areas.business(ref) if isinstance(ref, str) and BUSINESS_ID.fullmatch(ref) else None
    if found is None:
        raise PlaceError("unknown")
    premise, area = found
    return {**copy.deepcopy(premise), "is_point": False, "area_id": area.id, "cell": None,
            "section": sections.ref(area, premise.get("section"))}


def area_of(place: dict) -> areas.Area | None:
    """The listed area a Place lies in, or None for a point outside them."""
    return areas.get(place["area_id"]) if place.get("area_id") else None


# --- the flood model files, for the map ---

def coverage() -> dict:
    """GET /api/coverage: the loaded grids (to snap in the page), the block size and the region boxes in order."""
    return {**raster.depth_set().coverage(), "regions": [{"id": name, "box": list(box)} for name, box in REGIONS]}


def _pair(index: int, size: int) -> tuple[int, int]:
    """The two blocks along one axis nearest a square: its own and the one on the side of it that the square is nearer."""
    block = index // size
    return (block - 1, block) if index % size < size / 2 else (block, block + 1)


def blocks_around(row: int, col: int, size: int = raster.BLOCK_CELLS) -> list[tuple[int, int]]:
    """The (bi, bj) of the 2 x 2 blocks nearest a square, north to south then west to east (the quadrant rule in the
    module docstring). Blocks before the north or west edge are left out; whether one lies past the south or east edge
    is for DepthSet.block to say."""
    return [(bi, bj) for bi, bj in itertools.product(_pair(row, size), _pair(col, size)) if bi >= 0 and bj >= 0]


def neighbourhood(cell: dict) -> dict:
    """{blocks, cells} for a Place's `cell` (grid, row, col): the blocks around its square that the grid holds, as
    [{grid, bi, bj}], and their wet squares in town.json `cells` format. Block ids and squares come from one pass, so
    they always describe the same blocks. Empty for a grid that is not loaded."""
    loaded, blocks, squares = raster.depth_set(), [], []
    for bi, bj in blocks_around(cell["row"], cell["col"]):
        found = loaded.block(cell["grid"], bi, bj, raster.BLOCK_CELLS)
        if found is not None:
            blocks.append({"grid": cell["grid"], "bi": bi, "bj": bj})
            squares.extend(found)
    return {"blocks": blocks, "cells": squares}


def points_ready() -> bool:
    """Whether points can be checked: the flood model files load and hold at least one grid."""
    try:
        return bool(raster.depth_set().grids)
    except (raster.RasterError, OSError):
        return False


# --- distances, relief centres and names ---

def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two nearby points on a flat local map, using the cosine of their mean latitude."""
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    dx = (lon2 - lon1) * M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def nearest_shelter(area: areas.Area, lat: float, lon: float) -> dict | None:
    """{name, distance_m} of the area's nearest relief centre, as premises.json gives it; None with no list."""
    found = min(((distance_m(lat, lon, s["lat"], s["lon"]), s["name"]) for s in areas.town(area.id)["shelters"]),
                default=None)
    return None if found is None else {"name": found[1], "distance_m": round(found[0])}


def clean_name(text) -> str:
    """A name from the map made safe to put before the AI model: control, line-break and stray characters become
    spaces, format characters (such as right-to-left overrides) are removed, runs of spaces close up, and it is cut to
    MAX_NAME_CHARS. Anything but text gives ""."""
    if not isinstance(text, str):
        return ""
    kept = "".join(" " if unicodedata.category(ch) in SPACE_CATEGORIES else ch for ch in text
                   if unicodedata.category(ch) not in DROPPED_CATEGORIES)
    return " ".join(kept.split())[:MAX_NAME_CHARS].strip()


def quoted_name(text) -> str:
    """clean_name in double quotes, with any quote or backslash inside escaped, so it cannot end its own quotes."""
    return json.dumps(clean_name(text), ensure_ascii=False)
