"""The "low ground" map layer: land within 1, 2, 3 or 5 m of the level of the nearest mapped river, as pictures made by
tools/build_lowground.py from the elevation crops in app/data/dem (app/elevation.py reads the same folder).

What it is: a picture per level of the squares (about 31 m) whose lowest height above the nearest mapped OpenStreetMap
river, over the 3 x 3 squares around them, is at or below that level, shaded darker the lower they sit. It is never a
flood forecast or extent: banks, drains and pumps are left out, and land that is not shaded can still flood. Beyond 3 km
of a mapped river there is no height above a river, so no shading.

Each area that has it has, beside its crops:
  {name}_lowground.json          {"levels": [metres], "bounds": [west, south, east, north], "credit": text, ...}
  {name}_lowground_{level}m.png  one indexed PNG per level, transparent where not shaded

layer(area_id) gives {levels, url, bounds, credit} for the page, `url` holding "{level}" for the page to fill in, or
None where the area has no files; png_path(area_id, level) the picture for a level (text "1", "2", "3" or "5"), or
None. The files are loaded on first use and kept; a JSON that cannot be read is logged with its name and gives None,
so a damaged file costs the layer, not the page.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from . import elevation

log = logging.getLogger("banjir")

FILE_NAME = re.compile(r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)_lowground\.json$")
AREA_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LEVELS = (1, 2, 3, 5)         # metres: the only levels served
LAYER_URL = "/api/areas/{id}/layers/low-ground-{{level}}.png"
BOUNDS_DECIMALS = 6


class LayerError(ValueError):
    """A low ground JSON that cannot be read or does not fit; the message names the file."""


@dataclass(frozen=True)
class LowGround:
    """One area's pictures: {level: path} for the levels whose PNG is there."""

    name: str
    pngs: dict
    bounds: tuple
    credit: str

    def layer(self) -> dict:
        return {"levels": sorted(self.pngs), "url": LAYER_URL.format(id=self.name),
                "bounds": [round(edge, BOUNDS_DECIMALS) for edge in self.bounds], "credit": self.credit}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_set(path: Path, name: str) -> LowGround:
    """One area's JSON, checked, with the PNGs of its levels that are on disk. Raises LayerError naming the file."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:   # not found, bad UTF-8 or bad JSON
        raise LayerError(f"{path.name}: cannot be read ({error})") from error
    levels, bounds, credit = (meta.get(key) for key in ("levels", "bounds", "credit")) if isinstance(meta, dict) else (None,) * 3
    if not (isinstance(levels, list) and levels and all(level in LEVELS and not isinstance(level, bool) for level in levels)):
        raise LayerError(f"{path.name}: levels must be some of {list(LEVELS)}")
    if not (isinstance(bounds, list) and len(bounds) == 4 and all(_is_number(edge) for edge in bounds)
            and bounds[0] < bounds[2] and bounds[1] < bounds[3]):
        raise LayerError(f"{path.name}: bounds must be [west, south, east, north]")
    if not (isinstance(credit, str) and credit.strip()):
        raise LayerError(f"{path.name}: credit must be text")
    pngs = {level: png for level in levels if (png := path.parent / f"{name}_lowground_{level}m.png").is_file()}
    return LowGround(name, pngs, tuple(bounds), credit.strip())


def load(folder: str | Path) -> tuple[LowGround, ...]:
    """The folder's sets by name; a missing folder has none."""
    root = Path(folder).absolute()
    found = (FILE_NAME.match(path.name) for path in sorted(root.iterdir())) if root.is_dir() else ()
    return tuple(read_set(root / match.group(0), match["name"]) for match in found if match)


_loaded: dict[str, tuple[LowGround, ...]] = {}
_loading = threading.Lock()


def sets() -> tuple[LowGround, ...]:
    """The sets of elevation.dem_dir(), loaded on first use and kept; a failed load is not kept, so the next call
    retries."""
    folder = str(elevation.dem_dir())
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


sets.cache_clear = _forget


def _named(area_id) -> LowGround | None:
    """The set named for the area, None for another id, no set or files that cannot be read. The id is matched against
    the file names, never turned into a path."""
    if not (isinstance(area_id, str) and AREA_ID.fullmatch(area_id)):
        return None
    try:
        return next((found for found in sets() if found.name == area_id), None)
    except LayerError as error:
        log.error("The low ground files could not be read: %s", error)
        return None


def layer(area_id: str) -> dict | None:
    """{levels, url, bounds, credit} of the area's layer, bounds [west, south, east, north]; None without one."""
    found = _named(area_id)
    return found.layer() if found and found.pngs else None


def png_path(area_id, level) -> Path | None:
    """The picture of the area's layer at `level` (its text, as in a URL: "1", "2", "3" or "5"), None without one."""
    found = _named(area_id)
    number = next((n for n in LEVELS if str(n) == level), None)
    return found.pngs.get(number) if found and number is not None else None
