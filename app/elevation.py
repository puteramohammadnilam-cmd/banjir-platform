"""Height of the ground at a business or a picked square, from the elevation crops in app/data/dem.

Each area with elevation has two files, made by tools/build_elevation.py on the Copernicus GLO-30 grid (about 31 m):
  {name}_surface.tif       metres above sea level (the EGM2008 geoid) of the surface seen from space: roofs and trees
                           are in it, not only the ground
  {name}_above_river.tif   the surface minus the level of the nearest mapped OpenStreetMap river within 3 km, no data
                           beyond; negative where the surface is below that level
Both are read with app/raster.py (DepthFile.value_at), in the layout it reads, with no data -9999.

at(lat, lon) gives {"ground_m", "above_river_m"} in metres to 1 decimal, or None where no crop covers the spot: the page
says "not loaded for this spot yet". Each is the LOWEST value of its file in the 3 x 3 squares around the spot (the
square holding it and the 8 around that, about 90 m across: every square centre within about 45 m of the spot's
square's centre), because a satellite surface at a shop's own point is mostly its roof. The two minimums are taken
separately, so they may come from different squares. Squares past the crop's edge and no-data squares are left out;
above_river_m is null when no square of the window has a river within 3 km, and the whole answer None when none has a
surface. A business is looked up at its own point, a picked square at its centre (places.py), so the same spot always
gives the same answer.

The files are part of the repo (app/data/dem/SOURCES.txt), loaded on first use and kept. A file that cannot be read
is logged with its name and tile, never a point, and gives None, so a damaged crop costs the heights, not the page.
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from . import raster

log = logging.getLogger("banjir")

DEM_DIR = Path(__file__).resolve().parent / "data" / "dem"
FILE_NAME = re.compile(r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)_(?P<layer>surface|above_river)\.tif$")
LAYERS = ("surface", "above_river")
DECIMALS = 1
WINDOW = 1                    # squares each side of the spot's square: the 3 x 3 window
CACHE_TILES = 32              # decoded 256 px tiles kept: 32 x 256 KB, about 8 MB; one area's two files hold 30


def height_value(value: float) -> float | None:
    """Metres to 1 decimal, zero and negatives kept; None for no data (raster.NODATA_BELOW and under) or not finite."""
    if not (raster.NODATA_BELOW < value < math.inf):   # false for NaN too
        return None
    return round(value, DECIMALS) + 0.0   # + 0.0 turns -0.0 into 0.0


@dataclass(frozen=True, eq=False)
class Crop:
    """One area's two files, on one grid."""

    name: str
    surface: raster.DepthFile
    above_river: raster.DepthFile

    def at(self, lat: float, lon: float) -> dict | None:
        """The lowest ground and height above the river in the window around the spot (the module docstring)."""
        cell = self.surface.grid.cell(lon, lat)
        if cell is None:
            return None
        row, col = cell
        window = [(row + dr, col + dc) for dr in range(-WINDOW, WINDOW + 1) for dc in range(-WINDOW, WINDOW + 1)]
        ground = lowest(self.surface, window)
        if ground is None:
            return None
        return {"ground_m": ground, "above_river_m": lowest(self.above_river, window)}


def lowest(file: raster.DepthFile, cells: list[tuple[int, int]]) -> float | None:
    """The smallest height_value of the file at the cells, leaving out no data and cells outside its grid; None if
    none is left."""
    return min((v for row, col in cells if (v := file.value_at(row, col, height_value)) is not None), default=None)


def load(folder: str | Path) -> tuple[Crop, ...]:
    """The folder's crops by name. A missing folder has none. A name with one file of the two, two files that do not
    share a grid, or a file in another layout raises raster.RasterError."""
    root = Path(folder).absolute()
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(root.glob("*.tif")) if root.is_dir() else []:
        match = FILE_NAME.match(path.name)
        if match:
            found.setdefault(match["name"], {})[match["layer"]] = path
    cache = raster.TileCache(CACHE_TILES)
    crops = []
    for name, paths in sorted(found.items()):
        missing = [layer for layer in LAYERS if layer not in paths]
        if missing:
            raise raster.RasterError(f"elevation {name}: no {missing[0]} file")
        surface, above = (raster.DepthFile.open(paths[layer], name, cache) for layer in LAYERS)
        if surface.grid != above.grid:
            raise raster.RasterError(f"elevation {name}: the two files do not share one grid")
        crops.append(Crop(name, surface, above))
    return tuple(crops)


def dem_dir() -> Path:
    """BANJIR_DEM_DIR when set, else app/data/dem."""
    return Path(os.environ.get("BANJIR_DEM_DIR") or DEM_DIR)


_loaded: dict[str, tuple[Crop, ...]] = {}
_loading = threading.Lock()


def crops() -> tuple[Crop, ...]:
    """The crops of dem_dir(), loaded on first use and kept; a load that fails is not kept, so the next call tries again."""
    folder = str(dem_dir())
    found = _loaded.get(folder)
    if found is None:
        with _loading:
            found = _loaded.get(folder)
            if found is None:
                found = _loaded[folder] = load(folder)
    return found


def at(lat: float, lon: float) -> dict | None:
    """{"ground_m", "above_river_m"} at a spot from the first crop that covers it, or None (the module docstring)."""
    try:
        return next((found for crop in crops() if (found := crop.at(lat, lon)) is not None), None)
    except raster.RasterError as error:
        log.error("The elevation files could not be read: %s", error)   # a file and a tile, never a point
        return None


def _forget() -> None:
    """Drop the loaded crops, so the next call reads its folder afresh (for tests)."""
    with _loading:
        _loaded.clear()


crops.cache_clear = _forget
