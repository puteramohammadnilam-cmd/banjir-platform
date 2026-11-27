"""Fetch a state's districts (OpenStreetMap administrative boundaries, level 6) and the state's own outline (level 4).

    .venv/bin/python tools/fetch_state_districts.py [--state 2939653] [--expected 10] [--out DIR] [--date YYYY-MM-DD]

Run from 11_Platform_Draft. The default is Johor (relation 2939653, 10 districts). Two Overpass questions, a pause
before each, with tools/fetch_mbsa_sections.py's User-Agent, retries and ring joining:
  rel(STATE);map_to_area->.s;rel(area.s)[boundary=administrative][admin_level=6];out geom;   the districts
  rel(STATE);out geom;                                                                         the state's outline

It writes outside the repo, into DIR (default ../05_Raw_Data_Sources/johor/districts):
  raw_YYYY-MM-DD/districts.json, state.json   the Overpass answers as they came
  districts.geojson     one MultiPolygon feature per district, in name order: id (the name as a slug, "kota-tinggi"),
                        name, osm_id, area_km2 and town, [lon, lat] of the relation's admin_centre node (the district's
                        main town, where the page asks for rain), or null; tools/sections_io.py reads it as a named set
  state_outline.geojson the state's outline in the same form
  SOURCES.md            source, date, counts, areas, the ODbL credit and the limits

It stops, writing nothing, unless there are `expected` districts, each with a name and only closed rings, no two with
one id. Areas are on the sphere (fetch_mbsa_sections.ring_area_km2), within well under a percent of a surveyed area.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_mbsa_sections as fms  # noqa: E402
from rawpaths import RAW_SOURCES  # noqa: E402

JOHOR_RELATION = 2939653
EXPECTED = 10
DEFAULT_OUT = RAW_SOURCES / "johor" / "districts"


def districts_query(state: int) -> str:
    return (f'[out:json][timeout:180];rel({state});map_to_area->.s;'
            f'rel(area.s)["boundary"="administrative"]["admin_level"="6"];out geom;')


def state_query(state: int) -> str:
    return f"[out:json][timeout:180];rel({state});out geom;"


def slug(name: str) -> str:
    """"Johor Bahru" -> "johor-bahru": lower case words and digits joined by "-", as tools/sections_io.py needs."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def feature_of(relation: dict) -> dict:
    """A GeoJSON MultiPolygon feature for one boundary relation; ValueError for no name or a ring that does not close."""
    name = (relation.get("tags") or {}).get("name", "").strip()
    polygons, open_rings = fms.relation_polygons(relation)
    if not name or open_rings or not polygons:
        raise ValueError(f"relation {relation.get('id')} ({name or 'no name'}): {open_rings} rings do not close, "
                         f"{len(polygons)} polygons")
    centre = next((m for m in relation.get("members", []) if m.get("role") == "admin_centre" and "lat" in m), None)
    return {"type": "Feature",
            "properties": {"id": slug(name), "name": name, "osm_id": relation["id"],
                           "area_km2": round(sum(fms.polygon_area_km2(p) for p in polygons), 3),
                           "town": [round(centre["lon"], 6), round(centre["lat"], 6)] if centre else None},
            "geometry": {"type": "MultiPolygon", "coordinates": [[[list(pt) for pt in ring] for ring in poly] for poly in polygons]}}


def districts_of(answer: dict, expected: int) -> list[dict]:
    """The districts in name order; ValueError unless there are `expected`, with ids once each."""
    features = sorted((feature_of(e) for e in answer.get("elements", []) if e.get("type") == "relation"),
                      key=lambda f: f["properties"]["name"])
    ids = [f["properties"]["id"] for f in features]
    if len(features) != expected or len(set(ids)) != len(ids):
        raise ValueError(f"expected {expected} districts with different ids, got {len(features)}: {', '.join(ids)}")
    return features


def sources_md(districts: list[dict], state: dict, fetched_on: str, state_id: int) -> str:
    rows = [f"| {f['properties']['name']} | `{f['properties']['id']}` | {f['properties']['osm_id']} | "
            f"{f['properties']['area_km2']:,.1f} |" for f in districts]
    total = sum(f["properties"]["area_km2"] for f in districts)
    return "\n".join([
        f"# {state['properties']['name']} districts (OpenStreetMap)", "",
        f"Fetched {fetched_on} with tools/fetch_state_districts.py from the Overpass API: the administrative boundaries",
        f"of level 6 inside relation {state_id} (level 4), with `out geom`.", "",
        "| District | id | OSM relation | km² |", "|---|---|---|---|", *rows, "",
        f"Districts together: {total:,.1f} km². State outline: {state['properties']['area_km2']:,.1f} km².", "",
        "Credit: © OpenStreetMap contributors, ODbL 1.0. These are the lines volunteers drew, not a survey; a",
        "coastal district's line may run past the shore, so its area can hold some sea.", ""])


def build(out: Path, fetched_on: str, state_id: int = JOHOR_RELATION, expected: int = EXPECTED, post=fms.overpass_post) -> dict:
    """Ask Overpass, check, then write the files under `out`. Returns {districts, state}."""
    answers = {"districts": post(districts_query(state_id)), "state": post(state_query(state_id))}
    districts = districts_of(answers["districts"], expected)
    state = feature_of(next(e for e in answers["state"].get("elements", []) if e.get("id") == state_id))
    raw = out / f"raw_{fetched_on}"
    raw.mkdir(parents=True, exist_ok=True)
    for name, answer in answers.items():
        (raw / f"{name}.json").write_text(json.dumps(answer), encoding="utf-8")
    (out / "districts.geojson").write_text(json.dumps(fms.collection(districts)), encoding="utf-8")
    (out / "state_outline.geojson").write_text(json.dumps(fms.collection([state])), encoding="utf-8")
    (out / "SOURCES.md").write_text(sources_md(districts, state, fetched_on, state_id), encoding="utf-8")
    return {"districts": districts, "state": state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=int, default=JOHOR_RELATION, help="the state's OSM relation id")
    parser.add_argument("--expected", type=int, default=EXPECTED, help="how many districts there must be")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args(argv)
    found = build(args.out, args.date, args.state, args.expected)
    for feature in found["districts"]:
        print(f"{feature['properties']['id']}: {feature['properties']['area_km2']:,.1f} km²")
    print(f"state outline: {found['state']['properties']['area_km2']:,.1f} km²")
    return 0


if __name__ == "__main__":
    sys.exit(main())
