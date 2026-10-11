"""Bake the 3D flood mock-up's data for one shop: the buildings around it from OpenStreetMap and the flood model's
squares, into app/static/flood3d/<place id>.json for app/static/3d.html.

    .venv/bin/python tools/build_flood3d.py [--area shah-alam] [--place node-5565878632] [--radius-m 450]

        [--heights URL | file.tif | folder with pieces.json | none] [--heights-dir DIR] [--osm-answer FILE]

Run from 11_Platform_Draft. One Overpass question (fetch_area_osm's polite overpass_post): the building ways in a box
--radius-m around the shop, `out geom`. Each building keeps its outline and a height, taken from the first of: OSM's
`height`; OSM's `building:levels` floors; Google Open Buildings 2.5D Temporal (the --heights raster, below); a guess
from its kind. `hsrc` says which ("osm", "google" or "guess") and `guessed` is true for a guess only, so the page can
draw those lighter. The building the shop stands in (or the nearest within NEAR_M) is marked as the shop's. The squares
are town.json's cells inside the box that hold water, each with its depth per flood size (0 = dry); each building takes
the depths of the square under its middle, so the page can draw its walls wet up to the water line. With
--osm-answer the buildings come from an Overpass answer saved before (the same query, `out geom`) instead of asking
Overpass again, when it is busy.

Google's heights: one 2023 GeoTIFF of the open-buildings-temporal-data bucket (12.5 km square, UTM, 0.5 m squares,
float32 bands building_fractional_count, building_height and building_presence; about 4 m effective resolution). From
a URL only the header and the 512 px blocks over the box are fetched (HTTP Range, tools/tiff_read.PieceSource), into
--heights-dir with each range's SHA-256, so a later bake reads the same bytes offline. A building's Google height is
the median of building_height over the squares whose centres fall inside its OSM outline and where building_presence
is at least PRESENCE_MIN; none when fewer than MIN_SQUARES qualify or the median is under MIN_HEIGHT_M (ground, or a
roof the model barely saw). Heights are metres above the ground, model output, not surveyed.

ponytail: one shop baked by hand for the mock-up; buildings drawn as OSM ways only (multipolygon relations left out);
one Google tile, so a box across a tile edge gets no Google height past the edge (those buildings fall to a guess).
Upgrade path: an /api/flood3d/<place> answer built the same way, cached per place.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tiff_read as tr  # noqa: E402
from fetch_area_osm import QUERY_TIMEOUT_S, overpass_post  # noqa: E402
from fetch_indexes import HEAD_BYTES, get_range, remote_size  # noqa: E402
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AREAS = ROOT / "app" / "data" / "areas"
OUT_DIR = ROOT / "app" / "static" / "flood3d"
DEFAULT_PLACE = "node-5565878632"   # a 7-Eleven in a busy shop row, wet in all three flood sizes
DEFAULT_RADIUS_M = 450
NEAR_M = 30                         # a shop mapped as a dot just outside its building's outline still finds it
FLOOR_M = 3.2                       # one storey, floor to floor
GUESS_FLOORS = {"house": 2, "terrace": 2, "detached": 2, "semidetached_house": 2, "residential": 2, "bungalow": 1,
                "commercial": 3, "retail": 3, "office": 4, "apartments": 8, "industrial": 2, "warehouse": 2,
                "mosque": 2, "school": 3, "roof": 1, "shed": 1, "garage": 1}
DEFAULT_FLOORS = 2
METRES_PER_DEG = 111_320.0
CREDIT = "Buildings © OpenStreetMap contributors (ODbL) · flood depth: JRC v2.1 (CC BY 4.0)"
HEIGHTS_URL = ("https://storage.googleapis.com/open-buildings-temporal-data/v1/geotiffs/31cc4_2023_06_30/"
               "tile_PO8L06phMAw.tif")   # the 2023 tile (UTM 47N) holding the default shop's box
HEIGHTS_DIR = SHAH_ALAM_RAW / "open_buildings_temporal"
HEIGHTS_CREDIT = "building heights: Google Open Buildings 2.5D Temporal, {year} (CC BY 4.0)"
HEIGHT_BAND, PRESENCE_BAND = "building_height", "building_presence"
PRESENCE_MIN = 0.5            # uncalibrated model confidence: Google says use it to rank or cut, not as a chance
MIN_SQUARES = 8               # 2 m² of 0.5 m squares: fewer is too little roof to take a median of
MIN_HEIGHT_M = 2.5            # under one storey: ground or a roof the model barely saw
WGS84_A, WGS84_F = 6_378_137.0, 1 / 298.257223563
UTM_K0, UTM_EAST0, UTM_NORTH = 0.9996, 500_000.0, range(32601, 32661)
JOIN_GAP = 1 << 16            # fetch neighbouring blocks less than 64 KB apart in one request


def box_around(lat: float, lon: float, metres: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) of a square box `metres` out from the point on each side."""
    dlat = metres / METRES_PER_DEG
    dlon = metres / (METRES_PER_DEG * math.cos(math.radians(lat)))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def osm_height(tags: dict) -> float | None:
    """A building's height in metres from OSM: its `height`, else its `building:levels` floors; None without either."""
    for key, scale in (("height", 1.0), ("building:levels", FLOOR_M)):
        try:
            value = float(str(tags.get(key, "")).replace("m", "").strip())
        except ValueError:
            continue
        if value > 0:
            return round(value * scale, 1)
    return None


def height_of(tags: dict, google: float | None = None) -> tuple[float, str]:
    """A building's height in metres and where it came from: "osm" (its `height` or `building:levels`), else "google"
    (the Open Buildings height given), else "guess" (from its kind)."""
    known = osm_height(tags)
    if known is not None:
        return known, "osm"
    if google is not None:
        return round(google, 1), "google"
    return round(GUESS_FLOORS.get(tags.get("building"), DEFAULT_FLOORS) * FLOOR_M, 1), "guess"


def no_heights(ring: list[list[float]]) -> None:
    """Stands in for google_height when there is no Google raster: no height for any outline."""
    return None


# --- Google Open Buildings 2.5D Temporal heights ---

def utm_north(lat: float, lon: float, zone: int) -> tuple[float, float]:
    """(easting, northing) in metres on WGS 84 / UTM zone `zone` north (EPSG 32600 + zone): Krüger's series to the
    third power of n, well under a millimetre off within a zone."""
    n = WGS84_F / (2 - WGS84_F)
    radius = WGS84_A / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alpha = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16, 13 * n ** 2 / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240)
    e = math.sqrt(WGS84_F * (2 - WGS84_F))
    phi, lam = math.radians(lat), math.radians(lon - (6 * zone - 183))
    t = math.sinh(math.atanh(math.sin(phi)) - e * math.atanh(e * math.sin(phi)))
    xi, eta = math.atan2(t, math.cos(lam)), math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, a in enumerate(alpha, 1))
    y = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, a in enumerate(alpha, 1))
    return UTM_EAST0 + UTM_K0 * radius * x, UTM_K0 * radius * y


@dataclass(frozen=True)
class Heights:
    """Google's building height and presence over a window of its grid, rows north first: square (r, c) is item
    r * cols + c of each band, its centre (west + (c + 0.5) * pixel, north - (r + 0.5) * pixel) metres on UTM zone
    `zone` north."""

    zone: int
    west: float
    north: float
    pixel: float
    cols: int
    height: Sequence[float]
    presence: Sequence[float]

    @property
    def rows(self) -> int:
        return len(self.height) // self.cols


def band_of(metadata: str, name: str) -> int:
    """The sample number that GDAL's metadata (TIFF tag 42112) gives the band described as `name`."""
    found = re.search(rf'sample="(\d+)" role="description">{re.escape(name)}</Item>', metadata)
    if found is None:
        raise tr.TiffError(f"no band described as {name!r} in the file's GDAL metadata")
    return int(found.group(1))


def layer_year(text: str) -> str:
    """The year of an Open Buildings Temporal layer named in a path or URL (its folders end _YYYY_06_30), else ""."""
    found = re.search(r"_(20\d\d)_06_30", text)
    return found.group(1) if found else ""


def heights_source(spec: str, parent: Path):
    """Where the Google raster's bytes come from: an https URL (its header and blocks fetched as needed into a folder
    under `parent` named after the URL's last two parts), a folder of byte ranges saved before, or a GeoTIFF on disk."""
    if not spec.startswith("https://"):
        path = Path(spec)
        return tr.PieceSource(path) if (path / "pieces.json").exists() else tr.FileSource(path)
    folder = parent / "_".join(spec.rsplit("/", 2)[-2:]).removesuffix(".tif")
    held = tr.PieceSource(folder)
    if held.url not in (None, spec):
        raise SystemExit(f"{folder} holds byte ranges of {held.url}, not {spec}")
    source = tr.PieceSource(folder, url=spec, getter=get_range, size=held.size or remote_size(spec))
    source.fetch([(0, HEAD_BYTES)])
    return source


def read_heights(source, box: tuple[float, float, float, float]) -> Heights:
    """Google's height and presence over the (south, west, north, east) box, first fetching the blocks a remote source
    does not hold yet."""
    image = tr.open_image(source, utm=True)
    if image.crs not in UTM_NORTH or image.px != image.py:
        raise tr.TiffError(f"{source.name}: EPSG {image.crs}, squares {image.px} x {image.py}; need square pixels on "
                           "a WGS 84 / UTM north zone (32601 to 32660)")
    metadata = tr.read_tags(source).get(tr.GDAL_METADATA, ("",))[0]
    bands = [band_of(metadata, name) for name in (HEIGHT_BAND, PRESENCE_BAND)]
    zone, (south, west, north, east) = image.crs - 32600, box
    corners = [utm_north(lat, lon, zone) for lat in (south, north) for lon in (west, east)]
    xs, ys = [x for x, _ in corners], [y for _, y in corners]
    top, left, rows, cols = tr.pixel_window(image, (min(xs), min(ys), max(xs), max(ys)))
    if rows <= 0 or cols <= 0:
        raise tr.TiffError(f"{source.name}: the box lies outside this tile")
    if getattr(source, "getter", None):
        blocks = [i for band in bands for i in tr.blocks_for(image, top, left, rows, cols, band)]
        source.fetch([(image.offsets[i], image.counts[i]) for i in blocks if image.counts[i]], join_gap=JOIN_GAP)
    height, presence = (tr.read_window(source, image, top, left, rows, cols, band) for band in bands)
    return Heights(zone, image.west + left * image.px, image.north - top * image.py, image.px, cols, height, presence)


def squares_in(heights: Heights, ring: list[list[float]]) -> list[int]:
    """Indices into the bands of `heights` of the squares whose centres fall inside the (lon, lat) outline."""
    points = [list(utm_north(lat, lon, heights.zone)) for lon, lat in ring]
    xs, ys, size = [x for x, _ in points], [y for _, y in points], heights.pixel
    c_lo = max(0, math.ceil((min(xs) - heights.west) / size - 0.5))
    c_hi = min(heights.cols - 1, math.floor((max(xs) - heights.west) / size - 0.5))
    r_lo = max(0, math.ceil((heights.north - max(ys)) / size - 0.5))
    r_hi = min(heights.rows - 1, math.floor((heights.north - min(ys)) / size - 0.5))
    return [r * heights.cols + c for r in range(r_lo, r_hi + 1) for c in range(c_lo, c_hi + 1)
            if contains(points, heights.west + (c + 0.5) * size, heights.north - (r + 0.5) * size)]


def google_height(heights: Heights, ring: list[list[float]]) -> float | None:
    """The median of Google's building_height over the outline's squares where building_presence is at least
    PRESENCE_MIN; None when fewer than MIN_SQUARES qualify or the median is under MIN_HEIGHT_M."""
    values = [heights.height[i] for i in squares_in(heights, ring)
              if heights.presence[i] >= PRESENCE_MIN and heights.height[i] >= 0]
    if len(values) < MIN_SQUARES:
        return None
    middle = statistics.median(values)
    return round(middle, 1) if middle >= MIN_HEIGHT_M else None


# --- outlines, the shop and the water ---


def contains(ring: list[list[float]], lon: float, lat: float) -> bool:
    """Ray casting: whether (lon, lat) falls inside the closed ring of [lon, lat] points."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def metres_to_ring(ring: list[list[float]], lon: float, lat: float) -> float:
    """Metres from (lon, lat) to the nearest wall of the ring, on a flat local grid (fine over tens of metres)."""
    x_scale = METRES_PER_DEG * math.cos(math.radians(lat))
    points = [((x - lon) * x_scale, (y - lat) * METRES_PER_DEG) for x, y in ring]
    nearest = math.inf
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        share = 0.0 if length2 == 0 else max(0.0, min(1.0, -(x1 * (x2 - x1) + y1 * (y2 - y1)) / length2))
        nearest = min(nearest, math.hypot(x1 + share * (x2 - x1), y1 + share * (y2 - y1)))
    return nearest


def shop_building(rings: list[list[list[float]]], lat: float, lon: float) -> int | None:
    """Index of the ring the shop stands in, else of the ring with a wall nearest the shop within NEAR_M, else None."""
    for i, ring in enumerate(rings):
        if contains(ring, lon, lat):
            return i
    nearest = min(((metres_to_ring(ring, lon, lat), i) for i, ring in enumerate(rings)), default=None)
    return nearest[1] if nearest and nearest[0] <= NEAR_M else None


def buildings(answer: dict, lat: float, lon: float,
              google: Callable[[list[list[float]]], float | None] = no_heights) -> list[dict]:
    """GeoJSON features for the closed building ways in an Overpass `out geom` answer, `google` giving an outline's
    Open Buildings height (or None)."""
    ways = [e for e in answer.get("elements", []) if e.get("type") == "way" and len(e.get("geometry", [])) >= 4]
    rings = [[[round(p["lon"], 7), round(p["lat"], 7)] for p in way["geometry"]] for way in ways]
    shop = shop_building(rings, lat, lon)
    features = []
    for i, (way, ring) in enumerate(zip(ways, rings)):
        if ring[0] != ring[-1]:
            continue
        tags = way.get("tags", {})
        height, source = height_of(tags, None if osm_height(tags) is not None else google(ring))
        features.append({"type": "Feature", "id": way["id"],
                         "properties": {"h": height, "hsrc": source, "guessed": source == "guess", "shop": i == shop},
                         "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return features


def squares(town: dict, box: tuple[float, float, float, float]) -> list[dict]:
    """GeoJSON squares for the flood model's cells in the box that hold water in at least one flood size."""
    south, west, north, east = box
    size = town["cell_deg"]
    keys = [f"d{rp}" for rp in town["return_periods"]]
    features = []
    for cell_south, cell_west, *depths in town["cells"]:
        if not (south - size < cell_south < north and west - size < cell_west < east) or not any(depths):
            continue
        n, e = round(cell_south + size, 7), round(cell_west + size, 7)
        ring = [[cell_west, cell_south], [e, cell_south], [e, n], [cell_west, n], [cell_west, cell_south]]
        props = {key: depth or 0 for key, depth in zip(keys, depths)}
        features.append({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}})
    return features


def with_depths(building: dict, water: list[dict], keys: list[str]) -> dict:
    """The building with the depths of the square under its middle (0 where the model has no water), so the page can
    draw each building's walls wet up to the water line."""
    ring = building["geometry"]["coordinates"][0][:-1]
    lon, lat = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
    square = next((w for w in water if contains(w["geometry"]["coordinates"][0], lon, lat)), None)
    depths = {key: square["properties"][key] if square else 0 for key in keys}
    return {**building, "properties": {**building["properties"], **depths}}


def bake(area: str, place_id: str, radius_m: float, post: Callable[[str], dict] = overpass_post,
         heights: Callable[[tuple[float, float, float, float]], Heights] | None = None) -> dict:
    """The page's JSON for one shop: `post` answers the Overpass query, `heights` reads Google's raster over the box
    (None: no Google heights)."""
    premises = json.loads((AREAS / area / "premises.json").read_text())
    shop = next((p for p in premises if p["id"] == place_id), None)
    if shop is None:
        raise SystemExit(f"no place {place_id!r} in {area}")
    box = box_around(shop["lat"], shop["lon"], radius_m)
    south, west, north, east = box
    query = f"[out:json][timeout:{QUERY_TIMEOUT_S}];way[building]({south},{west},{north},{east});out geom;"
    town = json.loads((AREAS / area / "town.json").read_text())
    sections = json.loads((AREAS / area / "sections.json").read_text())["sections"]
    section_name = next((s["name"] for s in sections if s["id"] == shop["section"]), "")
    grid = heights(box) if heights else None
    google = (lambda ring: google_height(grid, ring)) if grid else no_heights
    water = squares(town, box)
    keys = [f"d{rp}" for rp in town["return_periods"]]
    houses = [with_depths(b, water, keys) for b in buildings(post(query), shop["lat"], shop["lon"], google)]
    # the shop's walls are wet to the depth the page states (the shop's own point), not that of its middle's square
    own = {f"d{rp}": shop["depth_m"].get(str(rp)) or 0 for rp in town["return_periods"]}
    houses = [{**b, "properties": {**b["properties"], **own}} if b["properties"]["shop"] else b for b in houses]
    return {
        "place": {**{key: shop[key] for key in ("id", "name", "kind", "sector", "section", "lat", "lon", "depth_m")},
                  "section_name": section_name},
        "flood_sizes": [str(rp) for rp in town["return_periods"]],
        "buildings": {"type": "FeatureCollection", "features": houses},
        "water": {"type": "FeatureCollection", "features": water},
        "credit": CREDIT,
        "fetched_on": date.today().isoformat(),
    }


def summary(baked: dict) -> str:
    found = baked["buildings"]["features"]
    sources = {name: sum(f["properties"]["hsrc"] == name for f in found) for name in ("osm", "google", "guess")}
    shop = "found" if any(f["properties"]["shop"] for f in found) else "NOT found"
    return (f"{len(found)} buildings (heights: {sources['osm']} OSM, {sources['google']} Google, {sources['guess']} "
            f"guessed; shop building {shop}), {len(baked['water']['features'])} wet squares")


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--area", default="shah-alam")
    args.add_argument("--place", default=DEFAULT_PLACE)
    args.add_argument("--radius-m", type=float, default=DEFAULT_RADIUS_M)
    args.add_argument("--heights", default=HEIGHTS_URL, help="Google raster: https URL, GeoTIFF, pieces folder or none")
    args.add_argument("--heights-dir", type=Path, default=HEIGHTS_DIR, help="where a URL's byte ranges are kept")
    args.add_argument("--osm-answer", type=Path, help="a saved Overpass answer to use instead of asking Overpass")
    opts = args.parse_args(argv)
    post = (lambda query: json.loads(opts.osm_answer.read_text())) if opts.osm_answer else overpass_post
    use_google = opts.heights.lower() != "none"
    heights = (lambda box: read_heights(heights_source(opts.heights, opts.heights_dir), box)) if use_google else None
    baked = bake(opts.area, opts.place, opts.radius_m, post, heights)
    if use_google:
        baked = {**baked, "credit": f"{baked['credit']} · {HEIGHTS_CREDIT.format(year=layer_year(opts.heights))}"}
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{opts.place}.json"
    out.write_text(json.dumps(baked, separators=(",", ":")))
    print(f"{out.relative_to(ROOT)}: {summary(baked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
