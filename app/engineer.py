"""Engineer mode (the page's "Engineer mode" switch): the "Rain pools" layer and the tools built on it, from the app's
own data only (no Google call, so no cost).

Rain pools: where heavy rain collects when the drains cannot take it, for storms of 40, 70 and 100 mm in an hour
(app/pooling_model.py, built by tools/build_pooling.py on FABDEM bare-earth heights; CC BY-NC-SA 4.0, so app/data/
pooling has its own licence). tools/check_pooling.py checked it against the flood record; the result is in each
area's JSON as "check" and the page shows it. It is a screening layer, never a forecast.

Tools: inspect (every value at a spot), profile (heights, river depths and standing water along a line), basin (the
land that drains to a spot), what-if (a bund raised or a pond dug along a line, the pooling worked out again on a
window around it), upload (an ESRI ASCII grid of the visitor's own, never stored) and a CSV of the businesses.
The two that run the model share one slot (COMPUTE), so one visitor cannot take the server's CPU.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
import math
import struct
import threading
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import areas, elevation, indexes, pooling_model, raster

POOL_DIR = Path(__file__).parent / "data" / "pooling"
LAYER_URL = "/api/areas/{id}/layers/rain-pools-{{mm}}.png"
M_PER_DEG_LAT = 110_574
M_PER_DEG_LON = 111_320
MAX_PROFILE_M = 5000
PROFILE_STEP_M = 30
WHATIF_MARGIN_M = 800
WHATIF_MAX_SIDE_M = 4000
CHANGE_M = 0.8                # a bund's height, or a pond's depth
MAX_ASC_BYTES = 3_000_000
MAX_ASC_CELLS = 250_000       # 500 x 500
COMPUTE = threading.Semaphore(1)
COMPUTE_WAIT_S = 3
CHANGE_COLOURS = {1: (59, 130, 246), 2: (249, 115, 22)}   # more water, less water

log = logging.getLogger(__name__)


class ToolError(ValueError):
    """A request the tools cannot answer; the message is for the visitor."""


@dataclass(frozen=True, eq=False)
class Pools:
    name: str
    meta: dict
    ground: raster.DepthFile
    down: raster.DepthFile
    storms: dict[int, raster.DepthFile]
    pngs: dict[int, Path]


def height(value: float) -> float | None:
    return round(value, 2) + 0.0 if raster.NODATA_BELOW < value < math.inf else None


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def pools(area_id: str) -> Pools | None:
    """The area's rain pools files, or None without them (or when they cannot be read, logged)."""
    meta_path = POOL_DIR / f"{area_id}_pooling.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        storms = {int(mm): raster.DepthFile.open(POOL_DIR / f"{area_id}_pool_{mm}.tif") for mm in meta["storms_mm"]}
        return Pools(area_id, meta, raster.DepthFile.open(POOL_DIR / f"{area_id}_ground.tif"),
                     raster.DepthFile.open(POOL_DIR / f"{area_id}_down.tif"), storms,
                     {mm: POOL_DIR / f"{area_id}_pool_{mm}.png" for mm in storms})
    except (OSError, ValueError, KeyError, raster.RasterError) as error:
        log.error("%s: the rain pools files cannot be read: %s", area_id, error)
        return None


def layer(area_id: str) -> dict | None:
    """What the page needs to draw the layer and say what it is; None for an area without one."""
    found = pools(area_id)
    if not found:
        return None
    meta = found.meta
    return {"storms": sorted(found.storms), "url": LAYER_URL.format(id=area_id), "bounds": meta["bounds"],
            "classes": meta["classes"], "credit": meta["credit"], "check": meta.get("check"),
            "assumptions": {k: meta[k] for k in ("drains_mm", "runoff", "min_dip_m", "min_depth_m", "burn_m")}}


def png_path(area_id: str, mm: str) -> Path | None:
    found = pools(area_id)
    storm = next((s for s in (found.storms if found else ()) if str(s) == mm), None)
    return found.pngs.get(storm) if storm else None


def tif_path(area_id: str, mm: str) -> Path | None:
    found = pools(area_id)
    storm = next((s for s in (found.storms if found else ()) if str(s) == mm), None)
    return Path(found.storms[storm].path) if storm else None


def _cell(found: Pools, lat: float, lon: float) -> tuple[int, int]:
    cell = found.ground.grid.cell(lon, lat)
    if cell is None:
        raise ToolError("That spot is outside the area's rain pools grid.")
    return cell


def _at(found: Pools, row: int, col: int) -> dict:
    return {"ground_m": found.ground.value_at(row, col, height),
            "pool_m": {str(mm): found.storms[mm].value_at(row, col, height) for mm in sorted(found.storms)}}


def inspect(area_id: str, lat: float, lon: float) -> dict:
    """Every value the app holds at a spot."""
    found = pools(area_id)
    pool = _at(found, *_cell(found, lat, lon)) if found else {"ground_m": None, "pool_m": None}
    return {"lat": round(lat, 5), "lon": round(lon, 5), "river_depth_m": raster.depth_set().depths(lon, lat),
            "bare_ground_m": pool["ground_m"], "pool_m": pool["pool_m"], "surface": elevation.at(lat, lon),
            "flash": indexes.flash_at(lat, lon)}


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy = (b[0] - a[0]) * M_PER_DEG_LAT
    dx = (b[1] - a[1]) * M_PER_DEG_LON * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def profile(area_id: str, a: tuple[float, float], b: tuple[float, float]) -> dict:
    """Heights, river depths and standing water every PROFILE_STEP_M from a to b ((lat, lon) each)."""
    found = pools(area_id)
    if not found:
        raise ToolError("This area has no rain pools grid.")
    length = _metres(a, b)
    if length > MAX_PROFILE_M:
        raise ToolError(f"Draw a line of {MAX_PROFILE_M // 1000} km or less.")
    steps = max(1, round(length / PROFILE_STEP_M))
    points = []
    for k in range(steps + 1):
        lat, lon = a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps
        cell = found.ground.grid.cell(lon, lat)
        values = _at(found, *cell) if cell else {"ground_m": None, "pool_m": None}
        points.append({"d": round(length * k / steps), "ground_m": values["ground_m"], "pool_m": values["pool_m"],
                       "river_depth_m": raster.depth_set().depths(lon, lat)})
    return {"length_m": round(length), "points": points}


def _array(file: raster.DepthFile, rows: range | None = None, cols: range | None = None) -> np.ndarray:
    """The file's values (NaN for no data) over the rows and columns given (all by default)."""
    grid = file.grid
    rows, cols = rows or range(grid.rows), cols or range(grid.cols)
    out = np.full((len(rows), len(cols)), np.nan)
    tile = file.tile
    for ti in range(rows.start // tile, (rows.stop - 1) // tile + 1):
        for tj in range(cols.start // tile, (cols.stop - 1) // tile + 1):
            index = ti * file.across + tj
            if not file.counts[index]:
                continue
            block = np.frombuffer(file._decode(index), dtype="<f4").reshape(tile, tile).astype(float)
            r0, c0 = ti * tile, tj * tile
            rs, re_ = max(r0, rows.start), min(r0 + tile, rows.stop)
            cs, ce = max(c0, cols.start), min(c0 + tile, cols.stop)
            out[rs - rows.start:re_ - rows.start, cs - cols.start:ce - cols.start] = block[rs - r0:re_ - r0, cs - c0:ce - c0]
    out[out <= raster.NODATA_BELOW] = np.nan
    return out


def _png(index: np.ndarray, palette: dict[int, tuple[int, int, int]]) -> str:
    """An indexed PNG (index 0 transparent) as a data: URL."""
    rows, cols = index.shape
    colours = [(0, 0, 0)] + [palette.get(i, (0, 0, 0)) for i in range(1, max(palette) + 1)]
    raw = b"".join(b"\x00" + bytes(row) for row in index.astype(np.uint8).tolist())
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", cols, rows, 8, 3, 0, 0, 0))
           + chunk(b"PLTE", b"".join(bytes(c) for c in colours)) + chunk(b"tRNS", b"\x00")
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _bounds(file: raster.DepthFile, rows: range, cols: range) -> list[float]:
    g = file.grid
    return [round(g.x0 + cols.start * g.px, 6), round(g.y0 - rows.stop * g.py, 6),
            round(g.x0 + cols.stop * g.px, 6), round(g.y0 - rows.start * g.py, 6)]


def basin(area_id: str, lat: float, lon: float) -> dict:
    """The land whose water flows through the spot (overflow paths over the filled ground), as a picture."""
    found = pools(area_id)
    if not found:
        raise ToolError("This area has no rain pools grid.")
    row, col = _cell(found, lat, lon)
    code = _array(found.down)
    n_rows, n_cols = code.shape
    flat = np.where(np.isnan(code), -1, code).astype(int).ravel()
    idx = np.arange(flat.size)
    r, c = np.divmod(idx, n_cols)
    moves = np.array(pooling_model.NEIGHBOURS)
    safe = np.clip(flat, 0, 7)
    to = (r + moves[safe, 0]) * n_cols + c + moves[safe, 1]
    down = np.where(flat >= 0, to, pooling_model.NO_DOWN)
    inside = pooling_model.upstream(down, (n_rows, n_cols), row * n_cols + col)
    rs, cs = np.flatnonzero(inside.any(axis=1)), np.flatnonzero(inside.any(axis=0))
    rows, cols = range(rs[0], rs[-1] + 1), range(cs[0], cs[-1] + 1)
    lat_mid = found.ground.grid.y0 - n_rows * found.ground.grid.py / 2
    cell_m2 = (found.ground.grid.py * M_PER_DEG_LAT) * (found.ground.grid.px * M_PER_DEG_LON * math.cos(math.radians(lat_mid)))
    return {"area_km2": round(float(inside.sum()) * cell_m2 / 1e6, 3), "squares": int(inside.sum()),
            "bounds": _bounds(found.down, rows, cols),
            "png": _png(inside[rows.start:rows.stop, cols.start:cols.stop].astype(int), {1: (14, 165, 233)})}


def _spacing(grid: raster.Grid, lat: float) -> tuple[float, float]:
    return grid.py * M_PER_DEG_LAT, grid.px * M_PER_DEG_LON * math.cos(math.radians(lat))


def _line_cells(points: list[tuple[int, int]], shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    for (r0, c0), (r1, c1) in zip(points, points[1:]):
        steps = max(abs(r1 - r0), abs(c1 - c0), 1) * 2
        for k in range(steps + 1):
            r, c = round(r0 + (r1 - r0) * k / steps), round(c0 + (c1 - c0) * k / steps)
            if 0 <= r < shape[0] and 0 <= c < shape[1]:
                mask[r, c] = True
    return mask


def _polygon_cells(points: list[tuple[int, int]], shape: tuple[int, int]) -> np.ndarray:
    rr, cc = np.mgrid[0:shape[0], 0:shape[1]]
    inside = np.zeros(shape, dtype=bool)
    for (r0, c0), (r1, c1) in zip(points, points[1:] + points[:1]):
        crosses = ((r0 > rr) != (r1 > rr)) & (cc < (c1 - c0) * (rr - r0) / ((r1 - r0) or 1e-12) + c0)
        inside ^= crosses
    return inside | _line_cells(points + points[:1], shape)


def _summary(depth: np.ndarray, cell_m2: float) -> dict:
    wet = np.isfinite(depth)
    return {"wet_squares": int(wet.sum()), "deepest_m": round(float(np.nanmax(depth)), 2) if wet.any() else 0.0,
            "water_m3": round(float(np.nansum(depth) * cell_m2))}


def _run(task):
    if not COMPUTE.acquire(timeout=COMPUTE_WAIT_S):
        raise ToolError("The model is busy with another run. Please try again in a moment.")
    try:
        return task()
    finally:
        COMPUTE.release()


def whatif(area_id: str, storm_mm: int, kind: str, points: list[tuple[float, float]]) -> dict:
    """The standing water with and without a bund (CHANGE_M higher along the line) or a pond (CHANGE_M lower inside the
    shape, or along the line for two points), worked out again on a window around it."""
    found = pools(area_id)
    if not found:
        raise ToolError("This area has no rain pools grid.")
    if kind not in ("bund", "pond") or not 2 <= len(points) <= 50:
        raise ToolError("Draw a bund or a pond of 2 to 50 points.")
    grid = found.ground.grid
    cells = [_cell(found, lat, lon) for lat, lon in points]
    margin_r = math.ceil(WHATIF_MARGIN_M / (grid.py * M_PER_DEG_LAT))
    margin_c = math.ceil(WHATIF_MARGIN_M / (grid.px * M_PER_DEG_LON))
    r0, r1 = max(0, min(r for r, _ in cells) - margin_r), min(grid.rows, max(r for r, _ in cells) + margin_r + 1)
    c0, c1 = max(0, min(c for _, c in cells) - margin_c), min(grid.cols, max(c for _, c in cells) + margin_c + 1)
    spacing = _spacing(grid, points[0][0])
    if (r1 - r0) * spacing[0] > WHATIF_MAX_SIDE_M or (c1 - c0) * spacing[1] > WHATIF_MAX_SIDE_M:
        raise ToolError(f"Keep the bund or pond within about {(WHATIF_MAX_SIDE_M - 2 * WHATIF_MARGIN_M) // 1000} km.")
    rows, cols = range(r0, r1), range(c0, c1)
    ground = _array(found.ground, rows, cols)
    local = [(r - r0, c - c0) for r, c in cells]
    shape = ground.shape
    edit = _line_cells(local, shape) if kind == "bund" or len(local) == 2 else _polygon_cells(local, shape)
    changed = ground + np.where(edit, CHANGE_M if kind == "bund" else -CHANGE_M, 0.0)

    def task():
        before = pooling_model.ponding(ground, storm_mm, spacing)
        after = pooling_model.ponding(changed, storm_mm, spacing)
        return before, after

    before, after = _run(task)
    diff = np.nan_to_num(after) - np.nan_to_num(before)
    index = np.where(diff >= pooling_model.MIN_DEPTH_M, 1, np.where(diff <= -pooling_model.MIN_DEPTH_M, 2, 0))
    cell_m2 = spacing[0] * spacing[1]
    return {"kind": kind, "storm_mm": storm_mm, "change_m": CHANGE_M, "squares_changed": int(edit.sum()),
            "before": _summary(before, cell_m2), "after": _summary(after, cell_m2),
            "bounds": _bounds(found.ground, rows, cols), "png": _png(index, CHANGE_COLOURS)}


def parse_asc(text: str) -> tuple[np.ndarray, float]:
    """(heights with NaN for no data, cell size) of an ESRI ASCII grid; ToolError for anything else."""
    if len(text) > MAX_ASC_BYTES:
        raise ToolError(f"The file is over {MAX_ASC_BYTES // 1_000_000} MB.")
    lines = text.strip().splitlines()
    head: dict[str, float] = {}
    while lines and lines[0].split() and lines[0].split()[0].lower() in (
            "ncols", "nrows", "xllcorner", "yllcorner", "xllcenter", "yllcenter", "cellsize", "nodata_value"):
        key, value = lines.pop(0).split()[:2]
        try:
            head[key.lower()] = float(value)
        except ValueError:
            raise ToolError(f"The header value for {key} is not a number.") from None
    try:
        n_cols, n_rows, size = int(head["ncols"]), int(head["nrows"]), head["cellsize"]
    except KeyError as missing:
        raise ToolError(f"The file has no {missing.args[0]} line: is it an ESRI ASCII grid (.asc)?") from None
    if not (0 < n_cols * n_rows <= MAX_ASC_CELLS and n_rows >= 3 and n_cols >= 3 and size > 0):
        raise ToolError(f"Use a grid of 3 x 3 to {MAX_ASC_CELLS:,} squares.")
    try:
        values = np.array(" ".join(lines).split(), dtype=float)
    except ValueError:
        raise ToolError("The heights must all be numbers.") from None
    if values.size != n_cols * n_rows:
        raise ToolError(f"The file says {n_rows} x {n_cols} but holds {values.size} heights.")
    grid = values.reshape(n_rows, n_cols)
    if "nodata_value" in head:
        grid[grid == head["nodata_value"]] = np.nan
    if not np.isfinite(grid).any() or np.nanmax(np.abs(grid)) > 10_000:
        raise ToolError("The heights do not look like metres.")
    return grid, size


def upload(text: str, storm_mm: int) -> dict:
    """The standing water on a visitor's own grid. Cell sizes under 1 are taken as degrees, else as metres. Never
    stored."""
    grid, size = parse_asc(text)
    metres = size * M_PER_DEG_LAT if size < 1 else size
    depth = _run(lambda: pooling_model.ponding(grid, storm_mm, (metres, metres)))
    index = np.zeros(depth.shape, dtype=int)
    for k, upto in ((3, None), (2, 1.0), (1, 0.3)):
        index = np.where(np.isfinite(depth) & (True if upto is None else depth < upto), k, index)
    palette = {1: (169, 180, 255), 2: (108, 111, 240), 3: (58, 42, 168)}
    return {"rows": grid.shape[0], "cols": grid.shape[1], "cell_m": round(metres, 2), "storm_mm": storm_mm,
            **_summary(depth, metres * metres), "png": _png(index, palette)}


def export_csv(area_id: str, section_id: str | None = None) -> str:
    """The area's (or a section's) businesses with every value the app holds at each, as CSV. Columns from FABDEM
    (bare ground, standing water) are CC BY-NC-SA 4.0; the rest as the README says."""
    out = io.StringIO()
    found = pools(area_id)
    storms = sorted(found.storms) if found else []
    writer = csv.writer(out)
    writer.writerow(["id", "name", "lat", "lon", "section", "river_depth_10_m", "river_depth_20_m", "river_depth_50_m",
                     "surface_m", "above_river_m", "bare_ground_m (CC BY-NC-SA)",
                     *[f"standing_water_{mm}mm_m (CC BY-NC-SA)" for mm in storms]])
    for p in areas.premises(area_id):
        if section_id and p.get("section") != section_id:
            continue
        surface = elevation.at(p["lat"], p["lon"]) or {}
        cell = found.ground.grid.cell(p["lon"], p["lat"]) if found else None
        pool = _at(found, *cell) if cell else {"ground_m": None, "pool_m": {}}
        depth = p.get("depth_m", {})
        writer.writerow([p["id"], p.get("name", ""), p["lat"], p["lon"], p.get("section", ""),
                         depth.get("10"), depth.get("20"), depth.get("50"), surface.get("ground_m"),
                         surface.get("above_river_m"), pool["ground_m"], *[pool["pool_m"].get(str(mm)) for mm in storms]])
    return out.getvalue()
