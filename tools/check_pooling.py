"""Check the "Rain pools" layer against what is on record, and against the low ground layer as the baseline to beat;
the result goes into app/data/pooling/{name}_pooling.json as "check" and onto the page.

    .venv/bin/python tools/check_pooling.py --name shah-alam \\
        --hotspots ../05_Raw_Data_Sources/shah_alam/jps_selangor_hotspots/hotspots_2026-10-08.json

1. Sections: each section's share of land with standing water (the 70 mm storm), and its share of low ground (within
   2 m of the nearest river's level, app/data/dem). Sections with a recorded flood not described as from a river
   (history.json "what") against sections with no recorded flood: the AUC (the chance a flooded section scores above
   a dry one; 0.5 is no better than chance) and a one-sided permutation p-value.
2. JPS hotspots inside the area's box: the distance to the nearest square with standing water, as a percentile of the
   same distance for random points in the sections (lower is better; 50 is no better than chance).
JPS's list is used here only, never shown or stored with the app. numpy and tifffile.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "app" / "data" / "pooling"
DEM = ROOT / "app" / "data" / "dem"
AREAS = ROOT / "app" / "data" / "areas"
STORM = 70
LOW_M = 2.0
SHUFFLES = 5000
RANDOM_POINTS = 4000
RIVER_WORDS = re.compile(r"\briver|\bsungai\b|\bsg\.|overflow|melimpah|banks? burst|tebing", re.IGNORECASE)
rng = np.random.default_rng(26)


def read(path: Path):
    """(values with NaN for no data, west, north, px, py), pixel-is-area or pixel-is-point."""
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        values = page.asarray().astype(float)
        scale, tie = page.tags["ModelPixelScaleTag"].value, page.tags["ModelTiepointTag"].value
        keys = page.tags["GeoKeyDirectoryTag"].value
    point = any(keys[i] == 1025 and keys[i + 3] == 2 for i in range(4, len(keys), 4))
    values[values <= -9998] = np.nan
    return values, tie[3] - (scale[0] / 2 if point else 0), tie[4] + (scale[1] / 2 if point else 0), scale[0], scale[1]


def sample(grid, lon, lat):
    values, west, north, px, py = grid
    r, c = ((north - lat) / py).astype(int), ((lon - west) / px).astype(int)
    ok = (r >= 0) & (r < values.shape[0]) & (c >= 0) & (c < values.shape[1])
    out = np.full(lon.shape, np.nan)
    out[ok] = values[r[ok], c[ok]]
    return out


def inside(lon, lat, outline) -> np.ndarray:
    """Even-odd point in (multi)polygon test, vectorised over the points."""
    polygons = outline["coordinates"] if outline["type"] == "MultiPolygon" else [outline["coordinates"]]
    hit = np.zeros(lon.shape, dtype=bool)
    for polygon in polygons:
        for ring in polygon:
            xs, ys = np.array([p[0] for p in ring]), np.array([p[1] for p in ring])
            for x0, y0, x1, y1 in zip(xs, ys, np.roll(xs, -1), np.roll(ys, -1)):
                crosses = ((y0 > lat) != (y1 > lat)) & (lon < (x1 - x0) * (lat - y0) / ((y1 - y0) or 1e-12) + x0)
                hit ^= crosses
    return hit


def auc(positive, negative) -> float:
    p, n = np.asarray(positive)[:, None], np.asarray(negative)[None, :]
    return float(((p > n) + 0.5 * (p == n)).mean())


def permutation_p(scores, labels) -> float:
    observed = auc(scores[labels], scores[~labels])
    more = sum(auc(scores[s], scores[~s]) >= observed for s in (rng.permutation(labels) for _ in range(SHUFFLES)))
    return (more + 1) / (SHUFFLES + 1)


def section_scores(pool, above, sections, events):
    """Per section kept: (pool share, low ground share, has a rain flood, its squares as lon/lat)."""
    rain_sections = {s for e in events if not RIVER_WORDS.search(e.get("what", "")) for s in e.get("sections", [])}
    any_sections = {s for e in events for s in e.get("sections", [])}
    values, west, north, px, py = pool
    rows, cols = values.shape
    lon_g, lat_g = np.meshgrid(west + (np.arange(cols) + 0.5) * px, north - (np.arange(rows) + 0.5) * py)
    wet_all = np.isfinite(values)
    kept = []
    for section in sections:
        w, s, e, n = section["bbox"]
        near = (lon_g >= w) & (lon_g <= e) & (lat_g >= s) & (lat_g <= n)
        lon, lat = lon_g[near], lat_g[near]
        mask = inside(lon, lat, section["outline"])
        if mask.sum() < 20 or (section["id"] in any_sections and section["id"] not in rain_sections):
            continue   # too small, or only river floods on record: neither a rain-flood case nor a no-flood one
        low = sample(above, lon[mask], lat[mask])
        kept.append((float(wet_all[near][mask].mean()), float(np.nanmean(low <= LOW_M)) if np.isfinite(low).any() else 0.0,
                     section["id"] in rain_sections, np.column_stack([lon[mask], lat[mask]])))
    return kept, np.column_stack([lon_g[wet_all], lat_g[wet_all]])


def nearest_m(points, targets):
    d = np.full(len(points), np.inf)
    for i in range(0, len(targets), 5000):
        t = targets[i:i + 5000]
        dx = (points[:, None, 0] - t[None, :, 0]) * 111_320 * np.cos(np.radians(3.1))
        dy = (points[:, None, 1] - t[None, :, 1]) * 110_574
        d = np.minimum(d, np.hypot(dx, dy).min(axis=1))
    return d


def hotspot_check(path: Path, pool, above, cells, wet_pts) -> dict:
    values, west, north, px, py = pool
    rows, cols = values.shape
    spots = json.loads(path.read_text())
    pts = np.array([(float(h["longitude"]), float(h["latitude"])) for h in spots if h.get("longitude")])
    pts = pts[(pts[:, 0] >= west) & (pts[:, 0] <= west + cols * px) & (pts[:, 1] >= north - rows * py) & (pts[:, 1] <= north)]
    everywhere = np.vstack(cells)
    rand = everywhere[rng.choice(len(everywhere), RANDOM_POINTS, replace=False)]
    low_pts = np.vstack([c[sample(above, c[:, 0], c[:, 1]) <= LOW_M] for c in cells])
    rank = lambda targets: round(float(np.mean([np.mean(nearest_m(rand, targets) <= d) * 100
                                                for d in nearest_m(pts, targets)])), 1)
    return {"hotspots": int(len(pts)), "hotspot_percentile": rank(wet_pts),
            "baseline_low_ground_hotspot_percentile": rank(low_pts)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--hotspots", type=Path)
    args = parser.parse_args()
    pool = read(POOL / f"{args.name}_pool_{STORM}.tif")
    above = read(DEM / f"{args.name}_above_river.tif")
    sections = json.loads((AREAS / args.name / "sections.json").read_text())["sections"]
    events = json.loads((AREAS / args.name / "history.json").read_text())["events"]
    kept, wet_pts = section_scores(pool, above, sections, events)
    shares, low_shares, labels = (np.array([k[i] for k in kept]) for i in range(3))
    check = {"storm_mm": STORM, "sections_with_rain_floods": int(labels.sum()), "sections_without": int((~labels).sum()),
             "auc": round(auc(shares[labels], shares[~labels]), 2), "p": round(permutation_p(shares, labels), 3),
             "baseline_low_ground_auc": round(auc(low_shares[labels], low_shares[~labels]), 2),
             "baseline_low_ground_p": round(permutation_p(low_shares, labels), 3)}
    if args.hotspots:
        check.update(hotspot_check(args.hotspots, pool, above, [k[3] for k in kept], wet_pts))
    meta_path = POOL / f"{args.name}_pooling.json"
    meta = json.loads(meta_path.read_text())
    meta["check"] = check
    meta_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(check, indent=1))


if __name__ == "__main__":
    main()
