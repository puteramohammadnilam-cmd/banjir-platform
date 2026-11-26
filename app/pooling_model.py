"""Where heavy rain collects on the ground: a screening model of surface ponding (flash floods from rain the drains
cannot take), on a bare-earth height grid. Used by tools/build_pooling.py for the "Rain pools" layer and by the
engineer tools (app/engineer.py) for a bund or pond what-if and for an uploaded grid.

Method ("blue spot" screening: Balstrom and Crawford 2018; fill-spill after Barnes and others 2020, simplified):
  1. Priority-flood (Barnes and others 2014) from the grid's edge gives every square the level water would have to
     reach to flow off the grid (`filled`) and the square it would overflow towards (`down`), so every square has a
     path to the edge.
  2. Dips: connected squares where `filled` stands at least MIN_DIP_M above the ground. Each has a capacity (the
     water it holds when full) and an outlet (where it overflows).
  3. Catchment: every square sends its rain down the steepest slope of the ground itself, to a low point. Where that
     low point is not in a dip (a pit too shallow to count), the rain goes on along the overflow path (`down`) to the
     first dip on it, or off the grid.
  4. Rain: each dip receives RUNOFF x (storm - drains) over its catchment. It fills from its lowest square up; what
     it cannot hold spills from its outlet along the overflow path into the first dip on it, highest dips first.
  5. The depth of water standing at each square, where at least MIN_DEPTH_M.
It knows nothing of pipes, pumps, gates, kerbs or buildings, and the grid's heights are good to a metre or two in a
town at best, so it shows where water tends to collect, not how deep it will be. numpy only.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

MIN_DIP_M = 0.15     # shallower dips are noise in a 30 m bare-earth grid
MIN_DEPTH_M = 0.1    # less standing water than this is not shown
RUNOFF = 0.8         # share of the rain that runs off a built-up town (the rest soaks in or is held)
DRAINS_MM = 30.0     # rain in the hour that the drains are taken to carry away (an assumption, said on the page)
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
NO_DOWN = -1


@dataclass(frozen=True)
class Dips:
    """The dips of a grid: label per square (-1 outside any), and per dip its squares' flat indices sorted by height,
    its capacity in m3, its outlet's flat index and its full level."""
    label: np.ndarray
    cells: list[np.ndarray]
    capacity: np.ndarray
    outlet: np.ndarray
    level: np.ndarray


def priority_flood(ground: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(filled, down): the spill level of every square and the flat index of the square it overflows towards (its
    neighbour that reached it first; NO_DOWN on the edge). NaN squares count as the edge (water leaves there)."""
    rows, cols = ground.shape
    filled = np.where(np.isnan(ground), -np.inf, ground).astype(float)
    down = np.full(rows * cols, NO_DOWN, dtype=np.int64)
    seen = np.zeros((rows, cols), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    order = 0
    for r in range(rows):
        for c in range(cols):
            if r in (0, rows - 1) or c in (0, cols - 1) or np.isnan(ground[r, c]):
                seen[r, c] = True
                heapq.heappush(heap, (filled[r, c], order, r * cols + c))
                order += 1
    flat = filled.ravel()
    while heap:
        level, _, at = heapq.heappop(heap)
        r, c = divmod(at, cols)
        for dr, dc in NEIGHBOURS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not seen[nr, nc]:
                seen[nr, nc] = True
                there = nr * cols + nc
                flat[there] = max(flat[there], level)
                down[there] = at
                heapq.heappush(heap, (flat[there], order, there))
                order += 1
    return flat.reshape(rows, cols), down


def steepest(ground: np.ndarray, spacing: tuple[float, float]) -> np.ndarray:
    """The flat index each square drains to down the steepest drop of the ground (itself where none is lower)."""
    rows, cols = ground.shape
    dy, dx = spacing
    padded = np.pad(np.where(np.isnan(ground), np.inf, ground), 1, constant_values=np.inf)
    best = np.zeros((rows, cols))
    to = np.arange(rows * cols).reshape(rows, cols)
    index = np.pad(to, 1, constant_values=-1)
    for dr, dc in NEIGHBOURS:
        neighbour = padded[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols]
        slope = (ground - neighbour) / np.hypot(dr * dy, dc * dx)
        better = np.nan_to_num(slope, nan=-np.inf) > best
        best = np.where(better, slope, best)
        to = np.where(better, index[1 + dr:1 + dr + rows, 1 + dc:1 + dc + cols], to)
    return to.ravel()


def sinks(to: np.ndarray) -> np.ndarray:
    """Where each square's water ends, following `to` (pointer doubling until every path has reached its end)."""
    end = to.copy()
    while True:
        nxt = end[end]
        if np.array_equal(nxt, end):
            return end
        end = nxt


def find_dips(ground: np.ndarray, filled: np.ndarray, down: np.ndarray, cell_m2: float) -> Dips:
    rows, cols = ground.shape
    wet = (filled - np.nan_to_num(ground, nan=np.inf)) >= MIN_DIP_M
    wet_any = (filled - np.nan_to_num(ground, nan=np.inf)) > 1e-9
    label = np.full(rows * cols, -1, dtype=np.int64)
    flat_wet, flat_any = wet.ravel(), wet_any.ravel()
    cells, capacity, outlet, level = [], [], [], []
    for start in np.flatnonzero(flat_wet):
        if label[start] >= 0:
            continue
        k = len(cells)
        stack, members = [start], []
        label[start] = k
        while stack:   # the connected squares under the same spill level, the shallow rim of the dip included
            at = stack.pop()
            members.append(at)
            r, c = divmod(at, cols)
            for dr, dc in NEIGHBOURS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    there = nr * cols + nc
                    if label[there] < 0 and flat_any[there] and filled.flat[there] == filled.flat[at]:
                        label[there] = k
                        stack.append(there)
        members = np.array(members)
        heights = ground.flat[members]
        members = members[np.argsort(heights, kind="stable")]
        top = filled.flat[members[0]]
        exit_at = next((d for d in down[members] if d >= 0 and label[d] != k), NO_DOWN)
        cells.append(members)
        capacity.append(float(np.sum(top - ground.flat[members]) * cell_m2))
        outlet.append(exit_at)
        level.append(float(top))
    return Dips(label.reshape(rows, cols), cells, np.array(capacity), np.array(outlet, dtype=np.int64), np.array(level))


def first_dip(label: np.ndarray, down: np.ndarray) -> np.ndarray:
    """For every square, the first dip on its overflow path, itself included (-1: the path leaves the grid first).
    Pointer doubling: each square looks at the square its pointer reaches; a settled one gives its answer, an unsettled
    one is jumped over (none of the squares in between is in a dip)."""
    index = np.arange(down.size)
    found = label.copy()
    pointer = np.where(down >= 0, down, index)
    done = (found >= 0) | (pointer == index)
    while not done.all():
        ahead, ahead_done = found[pointer], done[pointer]
        settle = ~done & ahead_done
        found = np.where(settle, ahead, found)
        pointer = np.where(~done & ~ahead_done, pointer[pointer], pointer)
        done = done | settle
    return found


def fill_level(heights: np.ndarray, volume: float, cell_m2: float, top: float) -> float:
    """The water level in a dip whose squares (heights sorted low to high) hold `volume` m3, at most `top`."""
    if volume <= 0:
        return float(heights[0])
    held = 0.0
    for i in range(1, len(heights)):
        step = (heights[i] - heights[i - 1]) * i * cell_m2
        if held + step >= volume:
            return float(heights[i - 1] + (volume - held) / (i * cell_m2))
        held += step
    return float(min(top, heights[-1] + (volume - held) / (len(heights) * cell_m2)))


def ponding(ground: np.ndarray, storm_mm: float, spacing: tuple[float, float], drains_mm: float = DRAINS_MM,
            runoff: float = RUNOFF, prepared: tuple | None = None) -> np.ndarray:
    """Depth of standing water (m) at each square after `storm_mm` of rain in an hour; NaN where none is shown.
    `prepared` is (filled, down, dips, ends, reach) from prepare(), to share between storms."""
    filled, down, dips, ends, reach = prepared or prepare(ground, spacing)
    cell_m2 = spacing[0] * spacing[1]
    rain_m = runoff * max(0.0, storm_mm - drains_mm) / 1000
    inflow = np.zeros(len(dips.cells))
    which = reach[ends]   # the dip each square's rain reaches (-1: none, it leaves the grid)
    np.add.at(inflow, which[which >= 0], rain_m * cell_m2)
    depth = np.full(ground.size, np.nan)
    for k in np.argsort(-dips.level, kind="stable"):   # highest first, so what spills reaches the lower dips in time
        members, volume = dips.cells[k], inflow[k]
        if volume > dips.capacity[k] and dips.outlet[k] >= 0:
            target = reach[dips.outlet[k]]
            if target >= 0 and target != k:
                inflow[target] += volume - dips.capacity[k]
        level = fill_level(ground.flat[members], min(volume, dips.capacity[k]), cell_m2, dips.level[k])
        water = level - ground.flat[members]
        depth[members] = np.where(water >= MIN_DEPTH_M, water, np.nan)
    return depth.reshape(ground.shape)


def prepare(ground: np.ndarray, spacing: tuple[float, float]) -> tuple:
    """What every storm on the same grid shares: (filled, down, dips, ends, reach)."""
    filled, down = priority_flood(ground)
    dips = find_dips(ground, filled, down, spacing[0] * spacing[1])
    ends = sinks(steepest(ground, spacing))
    return filled, down, dips, ends, first_dip(dips.label.ravel(), down)


def upstream(down: np.ndarray, shape: tuple[int, int], at: int) -> np.ndarray:
    """Boolean grid of the squares whose overflow path (`down`, from priority_flood; NO_DOWN at its end) passes through
    `at`: the area that drains to it. Pointer doubling, so a path of n steps takes about log2(n) passes."""
    count = down.size
    pointer = np.where(down >= 0, down, np.arange(count))
    hit = np.arange(count) == at
    while True:
        hit = hit | hit[pointer]
        jumped = pointer[pointer]
        if np.array_equal(jumped, pointer):
            return hit.reshape(shape)
        pointer = jumped
