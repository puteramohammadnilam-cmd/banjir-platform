"""Build one area's "where to move the car" spots: points on its streets that the flood model keeps dry.

    .venv/bin/python tools/build_dry_spots.py --area shah-alam \\
        --roads ../05_Raw_Data_Sources/shah_alam/city_osm/roads.json

Run from 11_Platform_Draft. It writes app/data/areas/{area}/dry_spots.json, which app/dryspots.py reads.

Inputs, read only: the area's area.json (its view), the JRC flood depth GeoTIFFs (app/raster.py, CC BY 4.0) and the
OpenStreetMap roads of the Overpass fetch build_area.py also reads (ODbL).

Each public street a car can be left on is walked every SPACING_M metres: PARK_ROADS (not motorways, trunk or primary
roads, nor slip roads), and not a bridge (the model's river squares read as dry), a tunnel or underpass (a flood trap),
a private or permit-only way (NO_ACCESS) or a driveway, car park aisle or back lane (NO_SERVICE). Named streets are
walked first, so where a square holds more than one street the named one is kept. A point is kept when the model puts no water on it in a 1 in 10 years flood, with `dry` the number
of flood sizes it stays dry in: 1 (1 in 10 only), 2 (also 1 in 20) or 3 (also 1 in 50). One point per 90 m flood square
is enough (the model has one depth for the whole square), so the file stays small. Inside the view only.

The model's squares are 90 m and it models rivers, not drains: a dry spot is the model's, not a promise.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import raster  # noqa: E402
from build_area import Projection  # noqa: E402

PARK_ROADS = {"secondary", "tertiary", "unclassified", "residential", "service", "living_street"}
NO_ACCESS = {"private", "no", "customers", "permit", "delivery", "destination"}
NO_SERVICE = {"driveway", "parking_aisle", "alley", "drive-through"}
SPACING_M = 40
COORD_DECIMALS = 5   # about 1 m
CREDIT = ("Streets: (c) OpenStreetMap contributors, ODbL. Water: European Commission JRC global river flood hazard "
          "maps v2.1, CC BY 4.0.")


def walk(pts: Sequence[tuple[float, float]], step: float) -> Iterator[tuple[float, float]]:
    """Points along a line in local metres: its first point, then one every `step` metres, and its last point."""
    yield pts[0]
    carry = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        length = math.hypot(bx - ax, by - ay)
        at = step - carry
        while at <= length:
            yield ax + (bx - ax) * at / length, ay + (by - ay) * at / length
            at += step
        carry = (carry + length) % step
    yield pts[-1]


def is_parkable(tags: dict) -> bool:
    """A public street a car can be driven to and left on, by its OpenStreetMap tags."""
    return (tags.get("highway") in PARK_ROADS and tags.get("bridge", "no") == "no" and tags.get("tunnel", "no") == "no"
            and tags.get("covered", "no") == "no" and tags.get("access") not in NO_ACCESS
            and tags.get("service") not in NO_SERVICE)


def load_streets(path: Path, proj: Projection) -> list[dict]:
    """The parkable streets of an Overpass answer as {name, pts} in local metres, named ones first."""
    ways = json.loads(Path(path).read_text(encoding="utf-8"))["elements"]
    streets = [{"name": way["tags"].get("name"), "pts": [proj.to_m(pt["lon"], pt["lat"]) for pt in way["geometry"]]}
               for way in ways if is_parkable(way.get("tags", {})) and len(way.get("geometry", [])) >= 2]
    return sorted(streets, key=lambda street: street["name"] is None)   # stable: Overpass order within each


def dry_count(depths: dict | None) -> int:
    """How many flood sizes, smallest first, leave the point dry: 0 to 3. Outside the model counts as 0."""
    if depths is None:
        return 0
    count = 0
    for rp in raster.RETURN_PERIODS:
        if depths[str(rp)] is not None:
            break
        count += 1
    return count


def build(roads: list[dict], proj: Projection, view: Sequence[float], depth_set: raster.DepthSet) -> dict:
    west, south, east, north = view
    names: dict[str, int] = {}
    seen: set[tuple] = set()
    spots = []
    for road in roads:
        for x, y in walk(road["pts"], SPACING_M):
            lon, lat = proj.to_lonlat(x, y)
            square = depth_set.locate(lon, lat)
            key = square and (square[0].name, square[1], square[2])
            if not (west <= lon <= east and south <= lat <= north) or square is None or key in seen:
                continue
            seen.add(key)
            dry = dry_count(depth_set.depths(lon, lat))
            if dry:
                name = -1 if road["name"] is None else names.setdefault(road["name"], len(names))
                spots.append([round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS), dry, name])
    return {"credit": CREDIT, "spacing_m": SPACING_M, "names": list(names), "spots": spots}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--area", required=True)
    parser.add_argument("--roads", required=True, type=Path)
    args = parser.parse_args(argv)
    folder = ROOT / "app" / "data" / "areas" / args.area
    view = json.loads((folder / "area.json").read_text(encoding="utf-8"))["view"]
    proj = Projection.for_view(view)
    found = build(load_streets(args.roads, proj), proj, view, raster.depth_set())
    (folder / "dry_spots.json").write_text(json.dumps(found, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    by_dry = {n: sum(1 for spot in found["spots"] if spot[2] == n) for n in (1, 2, 3)}
    print(f"{args.area}: {len(found['spots'])} dry spots on {len(found['names'])} named streets; dry in 1/2/3 sizes: {by_dry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
