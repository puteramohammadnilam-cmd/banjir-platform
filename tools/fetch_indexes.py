"""Download the inputs of the two Shah Alam indexes (plan Phase 3, gates G-P3-1 to G-P3-5), one subcommand per gate.

    .venv/bin/python tools/fetch_indexes.py worldcover   # G-P3-1 ESA WorldCover 2021 v200 land cover: byte ranges
    .venv/bin/python tools/fetch_indexes.py ndvi         # G-P3-3 WorldCover Sentinel-2 NDVI composite: byte ranges
    .venv/bin/python tools/fetch_indexes.py soilgrids    # G-P3-2 SoilGrids 2.0 sand, silt, clay, 0-5 and 5-15 cm (WCS)
    .venv/bin/python tools/fetch_indexes.py worldpop     # G-P3-4 WorldPop 2020 constrained, Malaysia (one file)
    .venv/bin/python tools/fetch_indexes.py drains       # G-P3-5 one Overpass request: rivers, canals, streams, drains,
                                                         #        ditches
    .venv/bin/python tools/fetch_indexes.py sources      # rewrite SOURCES.md from fetch_log.json

Run from 11_Platform_Draft. Everything lands in $BANJIR_RAW_DIR/shah_alam/indexes (else ../05_Raw_Data_Sources/...):
worldcover/<file stem>/ and vegetation/<file stem>/ hold the byte ranges read (tools/tiff_read.PieceSource: one file a
range and pieces.json with each range's SHA-256), soilgrids/, worldpop/ and osm_drains/ whole answers. fetch_log.json
records each download (what, URL, file, bytes, SHA-256, date, licence, credit) and SOURCES.md is written from it.

The area fetched is the grid the indexes are built on (index_inputs.grid_window(): the GLO-30 crop of app/data/dem, the
city box plus 2 km) and PAD_DEG more on each side. Requests go one at a time, PAUSE_S apart, with a User-Agent that
names the project and no person. A file already held is not fetched again.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import index_inputs as ii  # noqa: E402
import tiff_read as tr  # noqa: E402

USER_AGENT = "BanjirCheck-fetch-indexes/1.0 (flood risk research prototype; one-off data fetch)"
PAUSE_S = 1.0
HEAD_BYTES = 1 << 16
PAD_DEG = 0.005               # about 550 m: two SoilGrids squares past the grid's edge
WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
NDVI_URL = ("https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/ndvi/2021/{lat}/"
            "ESA_WorldCover_10m_2021_v200_{tile}_NDVI.tif")
SOIL_URL = ("https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
            "&COVERAGEID={prop}_{depth}_mean&FORMAT=image/tiff&SUBSET=long({west:.4f},{east:.4f})"
            "&SUBSET=lat({south:.4f},{north:.4f})&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
            "&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326")
SOIL_PROPERTIES, SOIL_DEPTHS = ("sand", "silt", "clay"), ("0-5cm", "5-15cm")
WORLDPOP_URL = ("https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/MYS/"
                "mys_ppp_2020_constrained.tif")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DRAIN_TYPES = ("river", "canal", "stream", "drain", "ditch")
LICENCES = {
    "worldcover": ("CC BY 4.0", "ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) "
                   "processed by ESA WorldCover consortium"),
    "ndvi": ("CC BY 4.0", "ESA WorldCover Sentinel-1 and Sentinel-2 10m Annual Composites accessed on {date} from "
             "https://registry.opendata.aws/esa-worldcover-vito-composites"),
    "soilgrids": ("CC BY 4.0", "SoilGrids 2.0, ISRIC - World Soil Information (Poggio et al. 2021, SOIL 7:217-240, "
                  "doi:10.5194/soil-7-217-2021)"),
    "worldpop": ("CC BY 4.0", "WorldPop (www.worldpop.org) 2020 constrained population counts, Malaysia, "
                 "doi:10.5258/SOTON/WP00660"),
    "drains": ("ODbL 1.0", "(c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright"),
}


def fetch_box() -> tuple[float, float, float, float]:
    """(west, south, east, north) of the grid's outer edges, PAD_DEG wider on each side."""
    west, south, east, north = ii.grid_window().bounds()
    return west - PAD_DEG, south - PAD_DEG, east + PAD_DEG, north + PAD_DEG


def worldcover_tiles(box: Sequence[float]) -> list[str]:
    """WorldCover map tiles (3 x 3 degrees, named by the south-west corner) a box touches, north first."""
    west, south, east, north = box
    return [f"N{lat:02d}E{lon:03d}" for lat in range(math.floor(north / 3) * 3, math.floor(south / 3) * 3 - 1, -3)
            for lon in range(math.floor(west / 3) * 3, math.floor(east / 3) * 3 + 1, 3)]


def ndvi_tiles(box: Sequence[float]) -> list[tuple[str, str]]:
    """(folder, tile) of the 1 x 1 degree NDVI composite tiles a box touches, north first."""
    west, south, east, north = box
    return [(f"N{lat:02d}", f"N{lat:02d}E{lon:03d}") for lat in range(math.floor(north), math.floor(south) - 1, -1)
            for lon in range(math.floor(west), math.floor(east) + 1)]


def drains_query(box: Sequence[float]) -> str:
    west, south, east, north = box
    kinds = "|".join(DRAIN_TYPES)
    return f'[out:json][timeout:180];way["waterway"~"^({kinds})$"]({south:.4f},{west:.4f},{north:.4f},{east:.4f});out geom;'


# --- HTTP ---

def _open(request: urllib.request.Request):
    time.sleep(PAUSE_S)
    return urllib.request.urlopen(request, timeout=300)   # noqa: S310  fixed https hosts only


def get(url: str, data: bytes | None = None) -> bytes:
    with _open(urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})) as answer:
        return answer.read()


def get_range(url: str, offset: int, length: int) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Range": f"bytes={offset}-{offset + length - 1}"}
    with _open(urllib.request.Request(url, headers=headers)) as answer:
        if answer.status != 206:
            raise tr.TiffError(f"{url.rsplit('/', 1)[-1]}: asked for a byte range, got HTTP {answer.status}")
        return answer.read()


def remote_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with _open(request) as answer:
        return int(answer.headers["Content-Length"])


# --- the log and SOURCES.md ---

def raw_dir() -> Path:
    return ii.raw_root() / "indexes"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_download(what: str, url: str, path: Path, note: str = "") -> dict:
    """Add one download to fetch_log.json (replacing an older entry for the same file) and rewrite SOURCES.md."""
    root = raw_dir()
    log_path = root / "fetch_log.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    stored = path.relative_to(root).as_posix()
    entry = {"what": what, "url": url, "file": stored, "bytes": path.stat().st_size, "sha256": sha256(path),
             "date": dt.date.today().isoformat(), "note": note}
    log = [e for e in log if e["file"] != stored] + [entry]
    log_path.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    write_sources(log)
    print(f"{stored}: {entry['bytes']} bytes, SHA-256 {entry['sha256']}")
    return entry


def write_sources(log: list[dict]) -> None:
    lines = ["# Inputs of the Shah Alam flash flood potential index and section score", "",
             "Fetched by tools/fetch_indexes.py (User-Agent: " + USER_AGENT + "). One entry per file; for a remote",
             "file read in byte ranges the file is its pieces.json, which lists each range with its own SHA-256.", ""]
    for what in LICENCES:
        entries = [e for e in log if e["what"] == what]
        if not entries:
            continue
        licence, credit = LICENCES[what]
        lines += [f"## {what}", "", f"- Licence: {licence}", f"- Credit: {credit.format(date=entries[0]['date'])}", ""]
        for e in entries:
            lines += [f"- {e['file']}: {e['bytes']} bytes, SHA-256 {e['sha256']}, fetched {e['date']}",
                      f"  - URL: {e['url']}"] + ([f"  - {e['note']}"] if e["note"] else [])
        lines.append("")
    (raw_dir() / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


# --- one subcommand per gate ---

def fetch_ranges(url: str, folder: Path, box: Sequence[float], band: int = 0) -> tuple[Path, str]:
    """The header and every block of a remote GeoTIFF that the box touches, as saved byte ranges."""
    source = tr.PieceSource(folder, url=url, getter=get_range, size=remote_size(url))
    source.fetch([(0, HEAD_BYTES)])
    image = tr.open_image(source)
    top, left, rows, cols = tr.pixel_window(image, box)
    blocks = tr.blocks_for(image, top, left, rows, cols, band)
    fetched = source.fetch([(image.offsets[i], image.counts[i]) for i in blocks if image.counts[i]])
    return folder / "pieces.json", f"{len(blocks)} blocks of {image.block_w} px; {fetched} bytes of {source.size}"


def fetch_worldcover(box: Sequence[float]) -> None:
    for tile in worldcover_tiles(box):
        url = WORLDCOVER_URL.format(tile=tile)
        manifest, note = fetch_ranges(url, raw_dir() / "worldcover" / Path(url).stem, box)
        log_download("worldcover", url, manifest, note)


def fetch_ndvi(box: Sequence[float]) -> None:
    for folder, tile in ndvi_tiles(box):
        url = NDVI_URL.format(lat=folder, tile=tile)
        manifest, note = fetch_ranges(url, raw_dir() / "vegetation" / Path(url).stem, box)
        log_download("ndvi", url, manifest, note)


def fetch_soilgrids(box: Sequence[float]) -> None:
    west, south, east, north = box
    for prop in SOIL_PROPERTIES:
        for depth in SOIL_DEPTHS:
            path = raw_dir() / "soilgrids" / f"{prop}_{depth}_mean.tif"
            url = SOIL_URL.format(prop=prop, depth=depth, west=west, south=south, east=east, north=north)
            if not path.exists():
                data = get(url)
                if data[:4] != b"II*\x00":
                    raise SystemExit(f"{path.name}: the server did not send a GeoTIFF: {data[:200]!r}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            log_download("soilgrids", url, path)


def fetch_worldpop() -> None:
    path = raw_dir() / "worldpop" / Path(WORLDPOP_URL).name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(WORLDPOP_URL))
    log_download("worldpop", WORLDPOP_URL, path)


def fetch_drains(box: Sequence[float]) -> None:
    path = raw_dir() / "osm_drains" / "drains_shah-alam.json"
    query = drains_query(box)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(OVERPASS_URL, urllib.parse.urlencode({"data": query}).encode()))
    answer = json.loads(path.read_text(encoding="utf-8"))
    kinds = {k: sum(e.get("tags", {}).get("waterway") == k for e in answer["elements"]) for k in DRAIN_TYPES}
    note = f"Overpass query: {query} OSM data as of {answer.get('osm3s', {}).get('timestamp_osm_base')}; ways: {kinds}"
    log_download("drains", OVERPASS_URL, path, note)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("what", choices=("worldcover", "ndvi", "soilgrids", "worldpop", "drains", "sources"))
    args = parser.parse_args(argv)
    raw_dir().mkdir(parents=True, exist_ok=True)
    box = fetch_box()
    actions = {"worldcover": lambda: fetch_worldcover(box), "ndvi": lambda: fetch_ndvi(box),
               "soilgrids": lambda: fetch_soilgrids(box), "worldpop": fetch_worldpop,
               "drains": lambda: fetch_drains(box),
               "sources": lambda: write_sources(json.loads((raw_dir() / "fetch_log.json").read_text("utf-8")))}
    actions[args.what]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
