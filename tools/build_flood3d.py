"""Bake the 3D flood page's data, one bundle per section: the buildings in the section's box from OpenStreetMap, each
with a height, and the flood model's wet squares, into app/static/flood3d/<area>/<section id>.json for
app/static/3d.html.

    .venv/bin/python tools/build_flood3d.py [--area shah-alam] (--section ID [ID ...] | --all)
        [--heights none | URL, GeoTIFF or pieces folder ...] [--heights-dir DIR] [--pixel-m 2] [--osm-dir DIR]

Run from 11_Platform_Draft. A section's box is its bbox widened by MARGIN_M on each side, so a shop near the section's
edge keeps its neighbours. One Overpass question per section (fetch_area_osm's polite overpass_post, which pauses before
each question and asks again when the server is busy): the building ways in the box, `out geom`. The answer is saved as
<section id>.json in --osm-dir and read from there on later bakes instead of asking again. A building is kept when the
middle of its corners lies in the box, with its outer ring and a height from the first of: OSM's `height`; OSM's
`building:levels` floors; Google Open Buildings 2.5D Temporal (below); a guess from its kind. The water is town.json's
squares over the box that hold water in at least one flood size.

The bundle, compact JSON, as the page reads it:
    version, area, section, box [west, south, east, north], origin [west, south] (the box's corner)
    buildings   [[h, src, x1, y1, x2, y2, ...], ...]: h in metres; src 0 OSM, 1 Google, 2 guess; the corners in whole
                millionths of a degree east and north of origin, the closing corner not repeated
    cell_deg, return_periods, water [[south, west, d10, d20, d50], ...] (0 where a flood size leaves it dry)
    credit, fetched_on (the date of the OSM data)
No shop and no depth per building: the page finds the shop's building and the water under each building itself.

Google's heights: the 2023 layer's GeoTIFFs over the area (12.5 km squares on UTM, float32 bands
building_fractional_count, building_height and building_presence at 0.5 m, about 4 m effective resolution), each read at
its internal overview with the largest squares no wider than --pixel-m. At 2 m that is about a ninth of the full grid's
bytes, and on the 451 buildings round one shop in Seksyen 7 its heights were 0.1 m from the full grid's at the median
(0.3 m at the 90th percentile; 3 lost their height). From a URL only the header and the 512 px blocks under buildings
that lack an OSM height are fetched (HTTP Range, tools/tiff_read.PieceSource), into --heights-dir with each range's
SHA-256, so a later bake reads the same bytes offline. A building reads the tile its middle lies in (where tiles
overlap, the one whose centre is nearest); in none of them, it falls to a guess. Its Google height is the median of
building_height over the squares whose centres fall inside its outline and where building_presence is at least
PRESENCE_MIN; none when those cover less than MIN_ROOF_M2 or the median is under MIN_HEIGHT_M (ground, or a roof the
model barely saw). Heights are metres above the ground, model output, not surveyed.

ponytail: buildings drawn as OSM ways only (multipolygon relations left out); a saved Overpass answer is reused as it
is, so delete it after changing MARGIN_M; HEIGHTS_TILES are Shah Alam's, found in the layer's Earth Engine manifest
(S2 cell 31, UTM 47N): another area passes its own with --heights.
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
from fetch_area_osm import QUERY_TIMEOUT_S, OverpassTimeout, checked, overpass_post, widen  # noqa: E402
from fetch_indexes import get_range, remote_size  # noqa: E402
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AREAS = ROOT / "app" / "data" / "areas"
OUT_DIR = ROOT / "app" / "static" / "flood3d"
OSM_DIR = SHAH_ALAM_RAW / "flood3d_osm"
VERSION = 1
MARGIN_M = 300.0                    # the section's bbox widened by this on each side
MICRO = 1_000_000                   # corners in millionths of a degree (about 0.11 m)
FLOOR_M = 3.2                       # one storey, floor to floor
GUESS_FLOORS = {"house": 2, "terrace": 2, "detached": 2, "semidetached_house": 2, "residential": 2, "bungalow": 1,
                "commercial": 3, "retail": 3, "office": 4, "apartments": 8, "industrial": 2, "warehouse": 2,
                "mosque": 2, "school": 3, "roof": 1, "shed": 1, "garage": 1}
DEFAULT_FLOORS = 2
OSM, GOOGLE, GUESS = 0, 1, 2        # where a building's height came from: the bundle's src
CREDIT = "Buildings © OpenStreetMap contributors (ODbL) · flood depth: JRC v2.1 (CC BY 4.0)"
HEIGHTS_CREDIT = "building heights: Google Open Buildings 2.5D Temporal, {year} (CC BY 4.0)"
TILES_URL = "https://storage.googleapis.com/open-buildings-temporal-data/v1/geotiffs/"
HEIGHTS_TILES = tuple(f"{TILES_URL}{name}.tif" for name in (
    "31cc4_2023_06_30/tile_PO8L06phMAw", "31cc4_2023_06_30/tile_z8ojqQWcNBY", "31cc4_2023_06_30/tile_hjx_dvHczCI",
    "31cc4_2023_06_30/tile_Rm-ZDzs2ThY", "31cc4_2023_06_30/tile_XgX7RExJBZo", "31cc4_2023_06_30/tile_86bhUIQ9Fvg",
    "31cdc_2023_06_30/tile_9IuZF450wHs", "31cdc_2023_06_30/tile_vT9LLrbKDBI", "31cdc_2023_06_30/tile_vJHjap2Zz7s"))
HEIGHTS_DIR = SHAH_ALAM_RAW / "open_buildings_temporal"
HEIGHT_BAND, PRESENCE_BAND = "building_height", "building_presence"
PIXEL_M = 2.0                 # the overview read: the data's effective resolution is about 4 m
PRESENCE_MIN = 0.5            # uncalibrated model confidence: Google says use it to rank or cut, not as a chance
MIN_ROOF_M2 = 2.0             # less roof than this is too little to take a median of (8 squares of 0.5 m, 1 of 2 m)
MIN_HEIGHT_M = 2.5            # under one storey: ground or a roof the model barely saw
WGS84_A, WGS84_F = 6_378_137.0, 1 / 298.257223563
UTM_K0, UTM_EAST0, UTM_NORTH = 0.9996, 500_000.0, range(32601, 32661)
TILE_HEAD_BYTES = 1 << 17     # a tile's header with every image's block list
JOIN_GAP = 1 << 16            # fetch neighbouring blocks less than 64 KB apart in one request

BBox = tuple[float, float, float, float]   # west, south, east, north
Ring = list[tuple[float, float]]           # (lon, lat) corners, the first repeated last


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


def height_of(tags: dict, google: float | None = None) -> tuple[float, int]:
    """A building's height in metres and where it came from: OSM (its `height` or `building:levels`), else GOOGLE
    (the Open Buildings height given), else GUESS (from its kind)."""
    known = osm_height(tags)
    if known is not None:
        return known, OSM
    if google is not None:
        return round(google, 1), GOOGLE
    return round(GUESS_FLOORS.get(tags.get("building"), DEFAULT_FLOORS) * FLOOR_M, 1), GUESS


def no_heights(rings: list[Ring]) -> list[float | None]:
    """Stands in for google_heights when there is no Google raster: no height for any outline."""
    return [None] * len(rings)


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


@dataclass(frozen=True)
class Tile:
    """One of Google's GeoTIFFs at the image read (an overview): where its bytes come from, and the sample numbers of
    building_height and building_presence."""

    source: object
    image: tr.Image
    bands: tuple[int, int]

    @property
    def zone(self) -> int:
        return self.image.crs - 32600

    def off_centre(self, lon: float, lat: float) -> float | None:
        """Metres from the tile's centre to the point, or None when the point lies outside the tile."""
        x, y = utm_north(lat, lon, self.zone)
        image = self.image
        east, south = image.west + image.px * image.width, image.north - image.py * image.height
        if not (image.west <= x < east and south < y <= image.north):
            return None
        return math.hypot(x - (image.west + east) / 2, y - (south + image.north) / 2)


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
    """Where a Google raster's bytes come from: an https URL (its header and blocks fetched as needed into a folder
    under `parent` named after the URL's last two parts), a folder of byte ranges saved before, or a GeoTIFF on disk."""
    if not spec.startswith("https://"):
        path = Path(spec)
        return tr.PieceSource(path) if (path / "pieces.json").exists() else tr.FileSource(path)
    folder = parent / "_".join(spec.rsplit("/", 2)[-2:]).removesuffix(".tif")
    held = tr.PieceSource(folder)
    if held.url not in (None, spec):
        raise SystemExit(f"{folder} holds byte ranges of {held.url}, not {spec}")
    source = tr.PieceSource(folder, url=spec, getter=get_range, size=held.size or remote_size(spec))
    source.fetch([(0, TILE_HEAD_BYTES)])
    return source


def overview_at(source, pixel_m: float) -> tr.Image:
    """The file's image with the largest squares no wider than pixel_m (the finest it has, when all are wider)."""
    images = [tr.open_image(source, utm=True, index=i) for i in range(len(tr.image_starts(source)))]
    fits = [image for image in images if image.px <= pixel_m * (1 + 1e-9)]
    return max(fits, key=lambda image: image.px) if fits else min(images, key=lambda image: image.px)


def open_tile(spec: str, parent: Path, pixel_m: float = PIXEL_M) -> Tile:
    """A Google tile, checked to be on a UTM north zone with square pixels, read at its overview nearest pixel_m."""
    source = heights_source(spec, parent)
    first = tr.open_image(source, utm=True)
    image = overview_at(source, pixel_m)
    if first.crs not in UTM_NORTH or not math.isclose(image.px, image.py):
        raise tr.TiffError(f"{source.name}: EPSG {first.crs}, squares {image.px} x {image.py}; need square pixels on "
                           "a WGS 84 / UTM north zone (32601 to 32660)")
    metadata = tr.read_tags(source).get(tr.GDAL_METADATA, ("",))[0]
    return Tile(source, image, (band_of(metadata, HEIGHT_BAND), band_of(metadata, PRESENCE_BAND)))


def tile_for(tiles: Sequence[Tile], ring: Ring) -> Tile | None:
    """The tile the outline's middle lies in; where tiles overlap, the one whose centre is nearest it."""
    lon, lat = middle(ring)
    holding = [(off, i) for i, tile in enumerate(tiles) if (off := tile.off_centre(lon, lat)) is not None]
    return tiles[min(holding)[1]] if holding else None


def window_under(tile: Tile, ring: Ring) -> tuple[int, int, int, int]:
    """(top, left, rows, cols) of the tile's squares whose centres lie in the outline's box (rows or cols 0: none)."""
    points = [utm_north(lat, lon, tile.zone) for lon, lat in ring]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return tr.pixel_window(tile.image, (min(xs), min(ys), max(xs), max(ys)))


def fetch_under(tile: Tile, rings: list[Ring]) -> int:
    """Fetch the blocks of both bands under the outlines that a remote tile does not hold yet. Returns the bytes."""
    if not getattr(tile.source, "getter", None):
        return 0
    image, blocks = tile.image, set()
    for ring in rings:
        top, left, rows, cols = window_under(tile, ring)
        if rows > 0 and cols > 0:
            blocks.update(i for band in tile.bands for i in tr.blocks_for(image, top, left, rows, cols, band))
    return tile.source.fetch([(image.offsets[i], image.counts[i]) for i in sorted(blocks) if image.counts[i]],
                             join_gap=JOIN_GAP)


def heights_under(tile: Tile, ring: Ring, cache: dict) -> Heights | None:
    """Google's squares under the outline's box, None when no square's centre lies in it. `cache` keeps the tile's
    decoded blocks between outlines."""
    top, left, rows, cols = window_under(tile, ring)
    if rows <= 0 or cols <= 0:
        return None
    image = tile.image
    height, presence = (tr.read_window(tile.source, image, top, left, rows, cols, band, cache) for band in tile.bands)
    return Heights(tile.zone, image.west + left * image.px, image.north - top * image.py, image.px, cols, height,
                   presence)


def squares_in(heights: Heights, ring: Ring) -> list[int]:
    """Indices into the bands of `heights` of the squares whose centres fall inside the (lon, lat) outline."""
    points = [utm_north(lat, lon, heights.zone) for lon, lat in ring]
    xs, ys, size = [x for x, _ in points], [y for _, y in points], heights.pixel
    c_lo = max(0, math.ceil((min(xs) - heights.west) / size - 0.5))
    c_hi = min(heights.cols - 1, math.floor((max(xs) - heights.west) / size - 0.5))
    r_lo = max(0, math.ceil((heights.north - max(ys)) / size - 0.5))
    r_hi = min(heights.rows - 1, math.floor((heights.north - min(ys)) / size - 0.5))
    return [r * heights.cols + c for r in range(r_lo, r_hi + 1) for c in range(c_lo, c_hi + 1)
            if contains(points, heights.west + (c + 0.5) * size, heights.north - (r + 0.5) * size)]


def google_height(heights: Heights | None, ring: Ring) -> float | None:
    """The median of Google's building_height over the outline's squares where building_presence is at least
    PRESENCE_MIN; None when those cover less than MIN_ROOF_M2 or the median is under MIN_HEIGHT_M."""
    if heights is None:
        return None
    values = [heights.height[i] for i in squares_in(heights, ring)
              if heights.presence[i] >= PRESENCE_MIN and heights.height[i] >= 0]
    if not values or len(values) < MIN_ROOF_M2 / heights.pixel ** 2:
        return None
    middle_value = statistics.median(values)
    return round(middle_value, 1) if middle_value >= MIN_HEIGHT_M else None


def google_heights(tiles: Sequence[Tile], rings: list[Ring]) -> list[float | None]:
    """Google's height for each outline (None where it gives none), from the tile its middle lies in, first fetching
    the blocks a remote tile does not hold yet."""
    picks = [tile_for(tiles, ring) for ring in rings]
    for tile in tiles:
        fetch_under(tile, [ring for ring, pick in zip(rings, picks) if pick is tile])
    caches: dict[int, dict] = {id(tile): {} for tile in tiles}
    return [google_height(heights_under(pick, ring, caches[id(pick)]), ring) if pick else None
            for ring, pick in zip(rings, picks)]


# --- outlines, the box and the water ---

def contains(ring: Sequence[Sequence[float]], x: float, y: float) -> bool:
    """Ray casting: whether (x, y) falls inside the closed ring of (x, y) points."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def middle(ring: Ring) -> tuple[float, float]:
    """(lon, lat) of the mean of the outline's corners, the closing one counted once: its centroid, near enough to
    say which box or tile a building is in."""
    corners = ring[:-1]
    return sum(lon for lon, _ in corners) / len(corners), sum(lat for _, lat in corners) / len(corners)


def section_box(bbox: Sequence[float]) -> BBox:
    """The section's (west, south, east, north) bbox widened by MARGIN_M on each side, to 6 decimals."""
    west, south, east, north = widen(tuple(bbox), MARGIN_M)
    return round(west, 6), round(south, 6), round(east, 6), round(north, 6)


def osm_query(box: BBox) -> str:
    """The Overpass question for the building ways in the box (Overpass wants south, west, north, east)."""
    west, south, east, north = box
    return (f"[out:json][timeout:{QUERY_TIMEOUT_S}];"
            f"way[building]({south:.6f},{west:.6f},{north:.6f},{east:.6f});out geom;")


def overpass_answer(path: Path, box: BBox, post: Callable[[str], dict] = overpass_post) -> dict:
    """The Overpass answer saved at `path`, else Overpass's answer for the box, saved there first."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    answer = checked(post(osm_query(box)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answer, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return answer


def outlines(answer: dict, box: BBox) -> list[tuple[dict, Ring]]:
    """(tags, ring) of each closed building way in an Overpass `out geom` answer whose middle lies in the box."""
    west, south, east, north = box
    found = []
    for way in answer.get("elements", []):
        if way.get("type") != "way" or len(way.get("geometry") or []) < 4:
            continue
        ring = [(point["lon"], point["lat"]) for point in way["geometry"]]
        lon, lat = middle(ring)
        if ring[0] == ring[-1] and west <= lon <= east and south <= lat <= north:
            found.append((way.get("tags", {}), ring))
    return found


def encode(ring: Ring, origin: tuple[float, float]) -> list[int] | None:
    """The outline as the page reads it: x1, y1, x2, y2, ... in whole millionths of a degree east and north of
    `origin`, the closing corner not repeated and a corner that rounds onto the one before it left out. None when
    fewer than 3 distinct corners are left."""
    lon0, lat0 = origin
    points = [(round((lon - lon0) * MICRO), round((lat - lat0) * MICRO)) for lon, lat in ring[:-1]]
    kept = [point for i, point in enumerate(points) if point != points[i - 1]]   # points[-1] before the first
    if len(set(kept)) < 3:
        return None
    return [value for point in kept for value in point]


def water_rows(town: dict, box: BBox) -> list[list[float]]:
    """town.json's squares over the box that hold water in at least one flood size: [south, west, depth per flood
    size], 0 where a size leaves the square dry."""
    west, south, east, north = box
    size = town["cell_deg"]
    return [[cell_south, cell_west, *(depth or 0 for depth in depths)]
            for cell_south, cell_west, *depths in town["cells"]
            if south - size < cell_south < north and west - size < cell_west < east and any(depths)]


def bake(area: str, section: dict, town: dict, answer: dict,
         google: Callable[[list[Ring]], list[float | None]] = no_heights, credit: str = CREDIT) -> dict:
    """One section's bundle from its Overpass answer: `google` gives the Open Buildings heights of the outlines that
    lack an OSM height (no_heights: none)."""
    box = section_box(section["bbox"])
    origin = box[:2]
    kept = [(tags, ring, corners) for tags, ring in outlines(answer, box) if (corners := encode(ring, origin))]
    lacking = [i for i, (tags, _, _) in enumerate(kept) if osm_height(tags) is None]
    from_google = dict(zip(lacking, google([kept[i][1] for i in lacking])))
    stamp = str((answer.get("osm3s") or {}).get("timestamp_osm_base") or "")[:10]
    return {
        "version": VERSION, "area": area, "section": section["id"], "box": list(box), "origin": list(origin),
        "buildings": [[*height_of(tags, from_google.get(i)), *corners] for i, (tags, _, corners) in enumerate(kept)],
        "cell_deg": town["cell_deg"], "return_periods": town["return_periods"], "water": water_rows(town, box),
        "credit": credit, "fetched_on": stamp or date.today().isoformat(),
    }


def summary(bundle: dict, ways: int) -> str:
    """One line on a bundle: its buildings, where their heights came from, and its wet squares."""
    found = bundle["buildings"]
    split = [sum(b[1] == src for b in found) for src in (OSM, GOOGLE, GUESS)]
    dropped = f", {ways - len(found)} with under 3 corners dropped" if ways != len(found) else ""
    return (f"{len(found)} buildings (heights: {split[0]} OSM, {split[1]} Google, {split[2]} guessed{dropped}), "
            f"{len(bundle['water'])} wet squares")


def held_bytes(tiles: Sequence[Tile]) -> int:
    """Bytes of the tiles' remote files held on disk so far."""
    return sum(n for tile in tiles for _, n in getattr(tile.source, "pieces", []))


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--area", default="shah-alam")
    which = args.add_mutually_exclusive_group(required=True)
    which.add_argument("--section", nargs="+", help="section ids to bake")
    which.add_argument("--all", action="store_true", help="bake every section of the area")
    args.add_argument("--heights", nargs="+", default=list(HEIGHTS_TILES),
                      help="Google rasters (https URLs, GeoTIFFs or pieces folders), or none")
    args.add_argument("--heights-dir", type=Path, default=HEIGHTS_DIR, help="where a URL's byte ranges are kept")
    args.add_argument("--pixel-m", type=float, default=PIXEL_M, help="read each raster at its overview this coarse")
    args.add_argument("--osm-dir", type=Path, default=OSM_DIR, help="where each section's Overpass answer is kept")
    opts = args.parse_args(argv)
    sections = json.loads((AREAS / opts.area / "sections.json").read_text(encoding="utf-8"))["sections"]
    unknown = set(opts.section or []) - {s["id"] for s in sections}
    if unknown:
        raise SystemExit(f"no section {', '.join(sorted(unknown))} in {opts.area}")
    chosen = sections if opts.all else [s for s in sections if s["id"] in opts.section]
    town = json.loads((AREAS / opts.area / "town.json").read_text(encoding="utf-8"))
    use_google = [spec.lower() for spec in opts.heights] != ["none"]
    tiles = [open_tile(spec, opts.heights_dir, opts.pixel_m) for spec in opts.heights] if use_google else []
    credit = f"{CREDIT} · {HEIGHTS_CREDIT.format(year=layer_year(' '.join(opts.heights)))}" if tiles else CREDIT
    google = (lambda rings: google_heights(tiles, rings)) if tiles else no_heights
    held, failed = held_bytes(tiles), []
    (OUT_DIR / opts.area).mkdir(parents=True, exist_ok=True)
    for section in chosen:
        box = section_box(section["bbox"])
        try:
            answer = overpass_answer(opts.osm_dir / f"{section['id']}.json", box)
        except (OSError, ValueError, OverpassTimeout) as error:
            print(f"{section['id']}: Overpass gave no answer ({error}); run this section again later", file=sys.stderr)
            failed.append(section["id"])
            continue
        bundle = bake(opts.area, section, town, answer, google, credit)
        out = OUT_DIR / opts.area / f"{section['id']}.json"
        out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        ways = len(outlines(answer, box))
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} KB, {summary(bundle, ways)}", flush=True)
    if tiles:
        print(f"Google tiles: {(held_bytes(tiles) - held) / 1e6:.1f} MB fetched this run, "
              f"{held_bytes(tiles) / 1e6:.1f} MB held in all")
    if failed:
        print(f"not baked: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
