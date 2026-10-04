"""Flash flood potential at a business or a picked square, from the index files in app/data/indexes.

What the figure is: the Flash Flood Potential Index (Smith 2003, in the form of Yassin and others 2023) of a square of
about 30 m, from its slope, land cover, soil texture and vegetation, each rated 1 to 10 and combined to one score from 1
to 10. It says how easily rain runs off and pools there: a susceptibility class, never a water depth or a chance of
flooding, and flash floods are not in the river flood model (app/raster.py).

Each area that has it has files named after its id, made by tools/build_ffpi.py:
  {name}_ffpi.tif   the score, float32 to 0.1, on the crop grid of app/data/dem (1 arc-second), no data -9999 outside
                    the city and over permanent water; read with app/raster.py (DepthFile.value_at), as elevation.py is
  {name}_ffpi.json  {"classes": [4 names, lowest first], "breaks": [3 scores, rising], "credit": text, "bounds": [west,
                    south, east, north], "method": {...plain text...}, ...}: the one place the class breaks are written;
                    the tool, this module and the page's legend all read it
  {name}_ffpi.png   the map layer, an indexed PNG with the cells outside the city transparent (optional)

A score on a break is in the class above it: the class of a score is the highest one whose break it reaches, so
breaks [3.5, 6.0, 8.0] give low under 3.5, medium from 3.5, high from 6.0, extreme from 8.0. tools/build_ffpi.py and
tools/build_section_scores.py use the same rule.

flash_at(lat, lon) gives {"score", "class"} for the square holding the spot: score to 1 decimal, class a name from the
json. A business is looked up at its own point, a picked square at its centre (places.py), so the same spot always gives
the same answer. None where no file covers the spot, over no data (water, outside the city) and where a file cannot be
read: the page says "not worked out for this spot yet".

The files are part of the repo, loaded on first use and kept (BANJIR_INDEX_DIR names another folder, for tests). A file
that cannot be read is logged with its name and tile, never a point, and gives None, so a damaged file costs the figure,
not the page. A folder without the files has no figures, and every field built on them is null or left out.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import raster

log = logging.getLogger("banjir")

INDEX_DIR = Path(__file__).resolve().parent / "data" / "indexes"
FILE_NAME = re.compile(r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)_ffpi\.(?P<kind>tif|png|json)$")
AREA_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LAYER_URL = "/api/areas/{id}/layers/flash-flood.png"
DECIMALS = 1
SCORE_RANGE = (1.0, 10.0)     # a stored value outside it is no data
BOUNDS_DECIMALS = 6
BOUNDS_TOLERANCE = 1e-6       # degrees: the json's bounds and the tif's grid are the same edges to this
METHOD_KEYS = ("name", "formula", "summary", "citations", "deviations", "not")   # what the page is told of the method
CACHE_TILES = 16              # decoded 256 px tiles kept: the city's file holds 15


@dataclass(frozen=True, eq=False)
class Ffpi:
    """One area's files, on one grid."""

    name: str
    file: raster.DepthFile
    classes: tuple[str, ...]
    breaks: tuple[float, ...]
    credit: str
    png: Path | None
    method: Mapping

    def grade(self, value: float) -> str:
        """The class a score is in: the highest whose break it reaches (the module docstring)."""
        return self.classes[sum(1 for edge in self.breaks if value >= edge)]

    def at(self, lat: float, lon: float) -> dict | None:
        """{"score", "class"} for the square holding the spot, None outside the grid and over no data."""
        cell = self.file.grid.cell(lon, lat)
        value = None if cell is None else self.file.value_at(*cell, score_value)
        return None if value is None else {"score": value, "class": self.grade(value)}

    def layer(self) -> dict | None:
        """The map layer as the page is told of it, None without a PNG."""
        if self.png is None:
            return None
        bounds = [round(edge, BOUNDS_DECIMALS) for edge in self.file.grid.as_json()["bounds"]]
        return {"url": LAYER_URL.format(id=self.name), "bounds": bounds, "breaks": list(self.breaks),
                "credit": self.credit}


def score_value(value: float) -> float | None:
    """A stored score to 1 decimal; None for no data (raster.NODATA_BELOW and under), NaN and a value out of range."""
    if not (SCORE_RANGE[0] <= value <= SCORE_RANGE[1]):   # false for NaN too
        return None
    return round(value, DECIMALS) + 0.0


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_meta(path: Path) -> Mapping:
    """The json's classes, breaks and credit, checked. Raises raster.RasterError naming the file."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:   # not found, bad UTF-8 or bad JSON
        raise raster.RasterError(f"{path.name}: cannot be read ({error})") from error
    classes, breaks = (meta.get(key) for key in ("classes", "breaks")) if isinstance(meta, dict) else (None, None)
    problems = {
        "classes must be two or more different names":
            isinstance(classes, list) and len(classes) >= 2 and all(_is_text(c) for c in classes)
            and len(set(classes)) == len(classes),
        "breaks must be numbers, one fewer than the classes":
            isinstance(breaks, list) and isinstance(classes, list) and len(breaks) == len(classes) - 1
            and all(_is_number(b) for b in breaks),
        "breaks must rise": isinstance(breaks, list) and all(_is_number(b) for b in breaks)
            and all(a < b for a, b in zip(breaks, breaks[1:])),
        "credit must be text": isinstance(meta, dict) and _is_text(meta.get("credit")),
    }
    failed = [words for words, passed in problems.items() if not passed]
    if failed:
        raise raster.RasterError(f"{path.name}: {failed[0]}")
    return meta


def method_for_page(meta: Mapping) -> dict:
    """The plain-text parts of the json's method (METHOD_KEYS) that it has, as new objects."""
    method = meta.get("method")
    return {key: copy.deepcopy(method[key]) for key in METHOD_KEYS if isinstance(method, dict) and key in method}


def check_bounds(meta: Mapping, file: raster.DepthFile, name: str) -> None:
    """Raise raster.RasterError unless the json's bounds, if it gives them, are the tif's grid."""
    bounds = meta.get("bounds")
    if bounds is not None and not (isinstance(bounds, list) and len(bounds) == 4 and all(
            _is_number(edge) and abs(edge - own) <= BOUNDS_TOLERANCE
            for edge, own in zip(bounds, file.grid.as_json()["bounds"]))):
        raise raster.RasterError(f"{name}_ffpi.json: bounds are not the grid of {name}_ffpi.tif")


def load(folder: str | Path) -> tuple[Ffpi, ...]:
    """The folder's sets by name. A missing folder has none. A name with a tif and no json (or the reverse), a json
    that does not fit its classes, or a tif in another layout raises raster.RasterError."""
    root = Path(folder).absolute()
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        match = FILE_NAME.match(path.name)
        if match:
            found.setdefault(match["name"], {})[match["kind"]] = path
    cache = raster.TileCache(CACHE_TILES)
    sets = []
    for name, paths in sorted(found.items()):
        missing = [kind for kind in ("tif", "json") if kind not in paths]
        if missing:
            raise raster.RasterError(f"flash flood potential {name}: no {missing[0]} file")
        meta = read_meta(paths["json"])
        file = raster.DepthFile.open(paths["tif"], name, cache)
        check_bounds(meta, file, name)
        sets.append(Ffpi(name, file, tuple(meta["classes"]), tuple(meta["breaks"]), meta["credit"].strip(),
                         paths.get("png"), method_for_page(meta)))
    return tuple(sets)


def index_dir() -> Path:
    """BANJIR_INDEX_DIR when set, else app/data/indexes."""
    return Path(os.environ.get("BANJIR_INDEX_DIR") or INDEX_DIR)


_loaded: dict[str, tuple[Ffpi, ...]] = {}
_loading = threading.Lock()


def crops() -> tuple[Ffpi, ...]:
    """The sets of index_dir(), loaded on first use and kept; a failed load is not kept, so the next call retries."""
    folder = str(index_dir())
    found = _loaded.get(folder)
    if found is None:
        with _loading:
            found = _loaded.get(folder)
            if found is None:
                found = _loaded[folder] = load(folder)
    return found


def _forget() -> None:
    """Drop the loaded sets, so the next call reads its folder afresh (for tests)."""
    with _loading:
        _loaded.clear()


crops.cache_clear = _forget


def _readable() -> tuple[Ffpi, ...]:
    """crops(), or () with the reason logged when the files cannot be read: a file and a tile, never a point."""
    try:
        return crops()
    except raster.RasterError as error:
        log.error("The flash flood potential files could not be read: %s", error)
        return ()


def flash_at(lat: float, lon: float) -> dict | None:
    """{"score", "class"} at a spot from the first set that covers it, or None (the module docstring)."""
    try:
        return next((found for index in crops() if (found := index.at(lat, lon)) is not None), None)
    except raster.RasterError as error:
        log.error("The flash flood potential files could not be read: %s", error)   # a file and a tile, never a point
        return None


def _named(area_id) -> Ffpi | None:
    """The set named for the area, None for another id or no set. The id is matched against the file names, never
    turned into a path."""
    if not (isinstance(area_id, str) and AREA_ID.fullmatch(area_id)):
        return None
    return next((index for index in _readable() if index.name == area_id), None)


def classes(area_id: str) -> tuple[str, ...] | None:
    """The class names of the area's files, lowest first; None where it has none."""
    found = _named(area_id)
    return found.classes if found else None


def layer(area_id: str) -> dict | None:
    """{url, bounds, breaks, credit} of the area's map layer, bounds [west, south, east, north]; None without one."""
    found = _named(area_id)
    return found.layer() if found else None


def png_path(area_id) -> Path | None:
    """The file of the area's map layer, None without one."""
    found = _named(area_id)
    return found.png if found else None


def flash_method(area_id: str) -> dict | None:
    """The plain-text method of the area's files (name, formula, summary, citations, deviations, not: those the json
    has), as a new object; None where it has no files."""
    found = _named(area_id)
    return copy.deepcopy(dict(found.method)) if found else None


def breaks(area_id: str) -> tuple[float, ...] | None:
    """The breaks between the classes of the area's files; None where it has none."""
    found = _named(area_id)
    return found.breaks if found else None
