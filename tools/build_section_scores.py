"""Build app/data/areas/shah-alam/indexes.json: per section, the flash flood potential (from shah-alam_ffpi.tif) and our
multi-criteria flood risk score, with how the score compares with past floods and the river model.

    .venv/bin/python tools/build_section_scores.py [--raw DIR] [--ffpi app/data/indexes/shah-alam_ffpi.tif] [--out PATH]

Run from 11_Platform_Draft after tools/build_ffpi.py. Reads only saved files. The shape is tests/fixtures/
index_contract.json (indexes_json).

Squares: the 1 arc second grid of the index (index_inputs.grid_window()). A square belongs to the first section, in
natural order, whose outline holds its centre (as tools/area_sections.py gives squares to sections); land squares are
those with a land cover rating (not mostly permanent water). Section figures are means over the section's land squares
weighted by each square's area (the cosine of its latitude).

flash: the mean FFPI (1 decimal) and the share of the land squares in each class (3 decimals).
score: each land square is rated 1 to 5 on seven criteria and the ratings are weighted with Leeonis et al. (2024)'s
AHP weights, less rainfall (23: one rain record covers the whole city) and economic loss (3: no source), divided by
the 74 left. The section's value is the area-weighted mean (2 decimals), classed at 1.5, 2.5, 3.5 and 4.5.
  river_distance      straight line to the nearest OpenStreetMap river or canal square (lines and river water areas,
                      the rivers app/data/dem was built with): under 100 m 5, 250 m 4, 500 m 3, 1 km 2, else 1
  drainage_density    km of OpenStreetMap river, canal, stream, drain and ditch within 1 km, per km2 of that disc
  elevation           the lowest GLO-30 surface height of the 3 x 3 squares (as for the slope), Leeonis et al.'s classes
  land_cover          WorldCover 2021 pixels rated LAND_SCORES, mixed by share
  slope               percent, from that lowest surface, Leeonis et al.'s classes
  road_distance       straight line to the nearest OpenStreetMap road (all vehicle roads but service ways)
  population_density  people per section, as the paper's council figures are: WorldPop 2020 constrained people summed
                      over the section's squares (all of them, water too), rated with Leeonis et al.'s classes (under
                      1,000 = 1, their four ranges 2 to 5); every square of the section takes the section's rating, so
                      the section's mean of it is that rating and the city's is the area-weighted mean of its sections'
Squares without a value for a criterion (a hole in the surface model) have no rating for it, not the highest; a
section's mean leaves them out.
validation: Spearman's rho (average ranks for ties) of the section score, and of the flash high + extreme share,
against the count of history.json events naming each section and against the share of its 90 m squares wet at 1 in 50
in the river model (sections.json); and the ranks of the five sections named as flood hotspots. These compare; they do
not validate either index.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import raster  # noqa: E402
import build_elevation as be  # noqa: E402
import build_ffpi as bf  # noqa: E402
import grid_ops as go  # noqa: E402
import index_inputs as ii  # noqa: E402
import score_text  # noqa: E402
import sections_io  # noqa: E402

AREA_DIR = ROOT / "app" / "data" / "areas" / ii.NAME
FFPI_TIF = bf.OUT_DIR / f"{ii.NAME}_ffpi.tif"
WEIGHTS_TOTAL = 74
SCORE_CLASSES = ("very_low", "low", "moderate", "high", "very_high")
SCORE_BREAKS = (1.5, 2.5, 3.5, 4.5)
DRAIN_RADIUS_M = 1000.0
CAP_M = 1000.0
DRAIN_KINDS = {"river", "canal", "stream", "drain", "ditch"}
ROAD_KINDS = {"living_street", "motorway", "motorway_link", "primary", "primary_link", "residential", "secondary",
              "secondary_link", "tertiary", "tertiary_link", "trunk", "trunk_link", "unclassified"}
LAND_SCORES = {10: 1, 20: 2, 30: 3, 40: 3, 50: 5, 60: 4, 70: 4, 80: 5, 90: 4, 95: 4, 100: 4}
HOTSPOTS = ("seksyen-16", "seksyen-17", "seksyen-18", "seksyen-36", "seksyen-25")


@dataclass(frozen=True)
class Criterion:
    id: str
    weight: int
    unit: str
    breaks: tuple[float, ...]
    ratings: tuple[int, ...]


CRITERIA = (
    Criterion("river_distance", 18, "m", (100, 250, 500, 1000), (5, 4, 3, 2, 1)),
    Criterion("drainage_density", 16, "km/km2", (0.25, 0.5, 1.0, 1.5), (1, 2, 3, 4, 5)),
    Criterion("elevation", 10, "m", (21, 42, 70, 113), (5, 4, 3, 2, 1)),
    Criterion("land_cover", 9, "class", (), ()),
    Criterion("slope", 8, "%", (3.53, 7.05, 11.8, 18.1), (5, 4, 3, 2, 1)),
    Criterion("road_distance", 7, "m", (50, 100, 200, 500), (5, 4, 3, 2, 1)),
    Criterion("population_density", 6, "people per section", (1000, 7441, 18188, 43792), (1, 2, 3, 4, 5)),
)


def weights_used() -> dict[str, float]:
    return {c.id: round(c.weight / WEIGHTS_TOTAL, 4) for c in CRITERIA}


def rate(value: float, breaks: Sequence[float], ratings: Sequence[int]) -> int:
    """ratings[k] for the k breaks at or below the value."""
    return ratings[sum(value >= b for b in breaks)]


def land_cover_rating(counts: dict[int, int]) -> float | None:
    total = sum(counts.values())
    return sum(LAND_SCORES[k] * n for k, n in counts.items()) / total if total else None


def score_class(value: float) -> str:
    return bf.class_of(value, SCORE_BREAKS, SCORE_CLASSES)


# --- the criteria on the grid ---

def river_mask(grid: go.Grid, raw_dem: Path) -> bytearray:
    lines, areas = be.river_shapes(json.loads((raw_dem / f"rivers_{ii.NAME}.json").read_text(encoding="utf-8")))
    mask = go.draw_lines(grid, lines)
    for rings in areas:
        filled = go.polygon_mask(grid, {"type": "Polygon", "coordinates": [r for r in rings if len(r) > 2]})
        mask = bytearray(a | b for a, b in zip(mask, filled))
    return mask


def drainage_density(grid: go.Grid, raw: Path, land: Sequence[float]) -> array:
    """km of drainage line within DRAIN_RADIUS_M of each land square, per km2 of the squares counted."""
    lines = ii.osm_lines(raw / "indexes" / "osm_drains" / f"drains_{ii.NAME}.json", DRAIN_KINDS, "waterway")
    dx, dy = grid.metres()
    spec = go.disc_rows(DRAIN_RADIUS_M, dx, dy)
    disc_km2 = sum(2 * half + 1 for _, half in spec) * dx * dy / 1e6
    metres = go.disc_sum(go.line_metres(grid, lines), grid, spec, lambda i: land[i] > go.NODATA_BELOW)
    return array("d", (m / 1000 / disc_km2 for m in metres))


def section_totals(values: Sequence[float], holder: Sequence[int], count: int) -> list[float]:
    """The sum of the values of each of `count` sections' squares."""
    totals = [0.0] * count
    for value, k in zip(values, holder):
        if k >= 0:
            totals[k] += value
    return totals


def by_section(totals: Sequence[float], holder: Sequence[int]) -> array:
    """Each square's section's figure; NODATA for a square in no section."""
    return array("d", (totals[k] if k >= 0 else go.NODATA for k in holder))


def criterion_values(layers: bf.Layers, raw: Path, holder: Sequence[int], count: int) -> dict[str, array]:
    """The raw value of each criterion per square (land cover is already a 1-5 rating; population is the people of
    the square's section)."""
    grid = layers.grid
    roads = ii.osm_lines(raw / "city_osm" / "roads.json", ROAD_KINDS, "highway")
    land = array("d", (go.NODATA if layers.land[i] <= go.NODATA_BELOW else
                       land_cover_rating({k: layers.cover[k][i] for k in layers.cover if layers.cover[k][i]})
                       for i in range(grid.size)))
    return {
        "river_distance": go.distance_to(river_mask(grid, raw.parent / "copernicus_glo30"), grid, CAP_M),
        "drainage_density": drainage_density(grid, raw, layers.land),
        "elevation": layers.ground,
        "land_cover": land,
        "slope": layers.slope,
        "road_distance": go.distance_to(go.draw_lines(grid, roads), grid, CAP_M),
        "population_density": by_section(section_totals(ii.load_population(grid, raw), holder, count), holder),
    }


def square_ratings(values: dict[str, array], land: Sequence[float]) -> dict[str, array]:
    """Each criterion's 1-5 rating per land square with a value for it; NODATA elsewhere."""
    out = {}
    for c in CRITERIA:
        source = values[c.id]
        out[c.id] = array("d", (go.NODATA if land[i] <= go.NODATA_BELOW or source[i] <= go.NODATA_BELOW else
                                source[i] if c.id == "land_cover" else rate(source[i], c.breaks, c.ratings)
                                for i in range(len(land))))
    return out


# --- section figures ---

def section_means(values: Sequence[float], holder: Sequence[int], grid: go.Grid, count: int) -> list[float | None]:
    """The area-weighted mean of the values with data in each of `count` sections; None for a section with none."""
    total, weight = [0.0] * count, [0.0] * count
    for r in range(grid.rows):
        w = grid.row_weight(r)
        for i in range(r * grid.cols, (r + 1) * grid.cols):
            k = holder[i]
            if k >= 0 and values[i] > go.NODATA_BELOW:
                total[k] += w * values[i]
                weight[k] += w
    return [t / w if w else None for t, w in zip(total, weight)]


def flash_summary(scores: Sequence[float], holder: Sequence[int], grid: go.Grid, count: int) -> list[dict | None]:
    """Per section {"mean", "share" {class: fraction}} of the FFPI over its squares with a score, by area."""
    weights = [dict.fromkeys(bf.CLASSES, 0.0) for _ in range(count)]
    means = section_means(scores, holder, grid, count)
    for r in range(grid.rows):
        w = grid.row_weight(r)
        for i in range(r * grid.cols, (r + 1) * grid.cols):
            if holder[i] >= 0 and scores[i] > go.NODATA_BELOW:
                weights[holder[i]][bf.class_of(scores[i])] += w
    found = []
    for mean, by_class in zip(means, weights):
        total = sum(by_class.values())
        found.append(None if mean is None else {"mean": round(mean, 1),
                                                "share": {k: round(v / total, 3) for k, v in by_class.items()}})
    return found


def read_ffpi(path: Path, grid: go.Grid) -> array:
    """The scores as stored (float32 widened), NODATA as -9999, read through app/raster.py."""
    crop = raster.DepthFile.open(path, path.stem)
    if (crop.grid.rows, crop.grid.cols) != (grid.rows, grid.cols):
        raise ValueError(f"{path.name} is not on the index grid")
    return array("d", (crop.value_at(r, c, float) for r in range(grid.rows) for c in range(grid.cols)))


# --- comparisons ---

def average_ranks(values: Sequence[float]) -> list[float]:
    """Ranks from 1 at the smallest; tied values share the mean of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks, start = [0.0] * len(values), 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for k in range(start, end + 1):
            ranks[order[k]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman's rho: Pearson's r of the average ranks; None when either side has no spread."""
    rx, ry = average_ranks(x), average_ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if not sxx or not syy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def top_ranks(values: Sequence[float]) -> list[int]:
    """1 for the highest; tied values share the best rank (1, 1, 3)."""
    return [1 + sum(other > v for other in values) for v in values]


def history_counts(events: Sequence[dict], ids: Sequence[str]) -> list[int]:
    return [sum(i in e.get("sections", []) for e in events) for i in ids]


def validation(ids: Sequence[str], values: Sequence[float | None], flash: Sequence[dict | None]) -> dict:
    history = json.loads((AREA_DIR / "history.json").read_text(encoding="utf-8"))
    counts = history_counts(history["events"], ids)
    rows = {s["id"]: s["counts"] for s in json.loads((AREA_DIR / "sections.json").read_text("utf-8"))["sections"]}
    wet = [rows[i]["wet_cells"]["50"] / rows[i]["cells"] if rows[i]["cells"] else 0.0 for i in ids]
    held = [k for k in range(len(ids)) if values[k] is not None and flash[k] is not None]
    score = [values[k] for k in held]
    high = [flash[k]["share"]["high"] + flash[k]["share"]["extreme"] for k in held]
    pick = lambda seq: [seq[k] for k in held]   # noqa: E731
    rho = lambda a, b: None if (r := spearman(a, b)) is None else round(r, 3)   # noqa: E731
    score_rank, flash_rank = top_ranks(score), top_ranks(high)
    return score_text.validation_doc(
        n=len(held),
        spearman={"score_vs_history": rho(score, pick(counts)), "score_vs_wet_share_50": rho(score, pick(wet)),
                  "flash_vs_history": rho(high, pick(counts)), "flash_vs_wet_share_50": rho(high, pick(wet))},
        hotspots=[{"id": h, "history_events": counts[ids.index(h)], "score_rank": score_rank[held.index(ids.index(h))],
                   "flash_rank": flash_rank[held.index(ids.index(h))]} for h in HOTSPOTS])


# --- the document ---

def score_of(ratings: dict[str, float | None]) -> dict | None:
    if any(v is None for v in ratings.values()):
        return None
    value = sum(c.weight * ratings[c.id] for c in CRITERIA) / WEIGHTS_TOTAL
    return {"value": round(value, 2), "class": score_class(round(value, 2)),
            "ratings": {c.id: round(ratings[c.id], 2) for c in CRITERIA}}


def method_doc() -> dict:
    score = score_text.score_method()
    score["criteria"] = [{"id": c.id, "weight": c.weight, "unit": c.unit, "breaks": list(c.breaks),
                          "ratings": list(c.ratings), **score_text.criterion_extra(c.id, LAND_SCORES)}
                         for c in CRITERIA]
    score.update({"weights_total": WEIGHTS_TOTAL, "weights_used": weights_used(), "classes": list(SCORE_CLASSES),
                  "breaks": list(SCORE_BREAKS),
                  "break_rule": "A value at or above a break belongs to the class above it."})
    return {"flash": {"source": f"{ii.NAME}_ffpi.json", "classes": list(bf.CLASSES), "breaks": list(bf.BREAKS),
                      "per_section": "Mean score and share of the section's land squares in each class; permanent "
                                     "water left out."},
            "score": score}


def indexes_doc(ids: Sequence[str], flash: Sequence[dict | None], ratings: dict[str, Sequence[float | None]],
                city: dict, checks: dict) -> dict:
    sections = {}
    for k, sid in enumerate(ids):
        score = score_of({c.id: ratings[c.id][k] for c in CRITERIA})
        sections[sid] = {"flash": flash[k], "score": score if flash[k] is not None else None}
    return {"version": 1, "area": ii.NAME, "method": method_doc(), "sections": sections, "city": city,
            "validation": checks}


def build(raw: Path, ffpi_path: Path, out: Path) -> dict:
    layers = bf.load_layers(raw)
    grid = layers.grid
    sections = sections_io.load_sections()
    ids = [s["id"] for s in sections]
    holder = go.first_holder(grid, [s["geometry"] for s in sections])
    city_holder = array("i", (0 if h >= 0 else -1 for h in holder))
    ratings = square_ratings(criterion_values(layers, raw, holder, len(ids)), layers.land)
    means = {c.id: section_means(ratings[c.id], holder, grid, len(ids)) for c in CRITERIA}
    city_means = {c.id: section_means(ratings[c.id], city_holder, grid, 1)[0] for c in CRITERIA}
    scores = read_ffpi(ffpi_path, grid)
    flash = flash_summary(scores, holder, grid, len(ids))
    city = {"flash": flash_summary(scores, city_holder, grid, 1)[0], "score": score_of(city_means)}
    values = [None if (s := score_of({c.id: means[c.id][k] for c in CRITERIA})) is None else s["value"]
              for k in range(len(ids))]
    doc = indexes_doc(ids, flash, means, city, validation(ids, values, flash))
    out.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return doc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw", type=Path, default=ii.raw_root(), help="the raw shah_alam folder")
    parser.add_argument("--ffpi", type=Path, default=FFPI_TIF)
    parser.add_argument("--out", type=Path, default=AREA_DIR / "indexes.json")
    args = parser.parse_args(argv)
    doc = build(args.raw, args.ffpi, args.out)
    print(score_text.report(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
