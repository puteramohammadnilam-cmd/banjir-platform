"""Fetch the public ArcGIS flood-point layers "2021" and "2022" and keep the Shah Alam part (plan WS-B, data groundwork).

    .venv/bin/python tools/fetch_flood_points.py [--out DIR] [--date YYYY-MM-DD]

Run from 11_Platform_Draft. The two layers are public feature services of one ArcGIS Online account
(services5.arcgis.com/2ZRAaoTSJbQ20ceg), made by the dashboard owner d1anameera. Their rows are flood points with a date,
a district, the flooded place, a depth range, the nearest river station and its reading, in JPS-style columns. The
owner states no licence on either item; reuse with attribution was approved by the user, and SOURCES.md says so.

It writes outside the repo, into DIR (default ../05_Raw_Data_Sources/shah_alam/arcgis_flood_points):
  raw_YYYY-MM-DD/   what the service said, untouched: pages of each layer as GeoJSON, the service and layer JSON, and
                    the item's owner and licence fields
  shah_alam.geojson the points inside the Shah Alam box, both years, each with its `source_layer`
  SOURCES.md        where the data came from, when, counts, credit and the limits

Polite by design: a descriptive User-Agent, one request a second, a thousand rows a page (the service's own limit).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

DEFAULT_OUT = SHAH_ALAM_RAW / "arcgis_flood_points"

ACCOUNT = "https://services5.arcgis.com/2ZRAaoTSJbQ20ceg/ArcGIS/rest/services"
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{item_id}?f=json"
LAYERS = ("2021", "2022")
PAGE_SIZE = 1000   # the services' maxRecordCount
USER_AGENT = "banjir-check-research/0.1 (flood risk research prototype; one-off data fetch)"
PAUSE_SECONDS = 1.0
SHAH_ALAM_BOX = {"south": 2.95, "north": 3.23, "west": 101.43, "east": 101.59}   # as plan WS-B

GetJson = Callable[[str], dict]


def http_get_json(url: str) -> dict:
    """GET `url` as JSON, one request a second, with a descriptive User-Agent."""
    time.sleep(PAUSE_SECONDS)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def layer_url(name: str, suffix: str = "") -> str:
    return f"{ACCOUNT}/{urllib.parse.quote(name)}/FeatureServer{suffix}"


def page_url(name: str, offset: int) -> str:
    query = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "f": "geojson", "resultOffset": offset,
                                    "resultRecordCount": PAGE_SIZE, "orderByFields": "ObjectId"})
    return f"{layer_url(name, '/0/query')}?{query}"


def fetch_pages(name: str, get_json: GetJson) -> list[dict]:
    """Every page of one layer, as the service sent them. Stops on a short page, an empty one, or no transfer-limit flag."""
    pages: list[dict] = []
    offset = 0
    while True:
        page = get_json(page_url(name, offset))
        if "features" not in page:
            raise RuntimeError(f"layer {name}: no features in the answer at offset {offset}: {str(page)[:200]}")
        pages.append(page)
        count = len(page["features"])
        exceeded = (page.get("properties") or {}).get("exceededTransferLimit") or page.get("exceededTransferLimit")
        if not count or not exceeded:
            return pages
        offset += count


def fetch_layer(name: str, get_json: GetJson) -> dict:
    """One layer: its pages, the service and layer JSON, and the item's owner and licence."""
    service = get_json(layer_url(name) + "?f=json")
    layer = get_json(layer_url(name, "/0") + "?f=json")
    item = get_json(ITEM_URL.format(item_id=service["serviceItemId"])) if service.get("serviceItemId") else {}
    return {"name": name, "pages": fetch_pages(name, get_json), "service": service, "layer": layer, "item": item}


def features_of(layer: dict) -> list[dict]:
    return [feature for page in layer["pages"] for feature in page["features"]]


def in_box(feature: dict, box: dict = SHAH_ALAM_BOX) -> bool:
    """Whether a point feature's coordinates [lon, lat] lie inside the box (edges count). A feature without a point is out."""
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") != "Point" or len(coords) < 2:
        return False
    lon, lat = coords[0], coords[1]
    return box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]


def filter_shah_alam(layers: list[dict]) -> list[dict]:
    """The points inside the box, from every layer, each a new feature that also names the layer it came from."""
    return [{**feature, "properties": {**feature.get("properties", {}), "source_layer": layer["name"]}}
            for layer in layers for feature in features_of(layer) if in_box(feature)]


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_raw(raw_dir: Path, layers: list[dict]) -> None:
    """The service's answers, kept as they came, one file each."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for layer in layers:
        name = layer["name"]
        for number, page in enumerate(layer["pages"], start=1):
            write_json(raw_dir / f"{name}_page{number}.geojson", page)
        write_json(raw_dir / f"{name}_service.json", layer["service"])
        write_json(raw_dir / f"{name}_layer.json", layer["layer"])
        write_json(raw_dir / f"{name}_item.json", layer["item"])


def _district_counts(features: list[dict]) -> str:
    counts = Counter(" ".join(str(f["properties"].get("DAERAH") or "?").split()) for f in features)
    return ", ".join(f"{name} {n}" for name, n in counts.most_common()) or "none"


def _dates(features: list[dict]) -> str:
    found = sorted(str(f["properties"].get("Date")) for f in features if f["properties"].get("Date"))
    undated = len(features) - len(found)
    span = f"{found[0]} to {found[-1]}" if found else "no dates"
    return f"{span}; {undated} undated" if undated else span


def sources_md(layers: list[dict], kept: list[dict], fetched_on: str, box: dict = SHAH_ALAM_BOX) -> str:
    """The SOURCES.md text: provenance, counts, credit and limits."""
    rows = []
    for layer in layers:
        mine = [f for f in kept if f["properties"]["source_layer"] == layer["name"]]
        item = layer["item"]
        no_point = sum(1 for f in features_of(layer) if not f.get("geometry"))
        rows.append(f"| {layer['name']} | {item.get('id', '?')} | {item.get('owner', '?')} | {len(features_of(layer))} ({no_point} with no point) | {len(mine)} "
                    f"| {_dates(mine)} | {item.get('licenseInfo') or 'none stated'} |")
    return f"""# ArcGIS flood points, 2021 and 2022 (Shah Alam part)

Fetched {fetched_on} by tools/fetch_flood_points.py from the public ArcGIS Online feature services
`{ACCOUNT}/<layer>/FeatureServer/0` (layers "{'", "'.join(LAYERS)}"), query `where=1=1&outFields=*&f=geojson`, paged
with `resultOffset` ({PAGE_SIZE} rows a page, one request a second, a descriptive User-Agent).

| layer | item id | owner | points in layer | in the Shah Alam box | dates in the box | licence on the item |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

Shah Alam box: {box['south']} to {box['north']} N, {box['west']} to {box['east']} E ({len(kept)} points; `shah_alam.geojson`).
DAERAH of the points kept: {_district_counts(kept)}. The box also takes in the edges of Klang and Subang; the Shah Alam
city boundary itself is in ../mbsa_sections.

## Credit and reuse

Made and published by the ArcGIS Online user **d1anameera** (dashboard owner; both items belong to this account; the project notes also name Huda28, who is not the owner on either item). The rows
follow the columns of the Department of Irrigation and Drainage (JPS) flood records (RUJ No, NEGERI, DAERAH, KWSN_BANJIR,
SUNGAI, KEDALAMAN, STESEN, Water_Level, Status), so the origin is JPS-style, but we have not seen an official JPS
publication of these exact rows. The items state no licence. Reuse with attribution was approved by the user
(4 Oct 2026). Credit them wherever the points are shown; do not present them as an official record.

## Limits

- One resident or officer report per row. Not a complete record, not a survey.
- Free-text place names (KWSN_BANJIR) are as typed; NEGERI and RUJ No contain stray spaces and line breaks
  ("SELANGO R", "NORMA L"). The raw files keep them as sent.
- KEDALAMAN is a text range such as "0.1-0.3" (metres, as far as the sheets say; unit not stated).
- The raw answers are in `raw_{fetched_on}/`. They stay out of app/.
"""


def collect(get_json: GetJson = http_get_json) -> list[dict]:
    return [fetch_layer(name, get_json) for name in LAYERS]


def build(out: Path, fetched_on: str, get_json: GetJson = http_get_json) -> dict:
    """Fetch both layers, write the raw answers, the Shah Alam points and SOURCES.md under `out`. Returns the counts."""
    layers = collect(get_json)
    kept = filter_shah_alam(layers)
    out.mkdir(parents=True, exist_ok=True)
    write_raw(out / f"raw_{fetched_on}", layers)
    write_json(out / "shah_alam.geojson", {"type": "FeatureCollection", "features": kept})
    (out / "SOURCES.md").write_text(sources_md(layers, kept, fetched_on), encoding="utf-8")
    return {"total": sum(len(features_of(layer)) for layer in layers), "shah_alam": len(kept),
            "by_layer": {layer["name"]: len(features_of(layer)) for layer in layers}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--date", default=date.today().isoformat(), help="the date in the raw folder's name")
    args = parser.parse_args(argv)
    counts = build(args.out, args.date)
    print(f"{counts['total']} points in the two layers {counts['by_layer']}; {counts['shah_alam']} in the Shah Alam box -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
