"""Build the Shah Alam flood history (plan workstream F) from the curated events and the public ArcGIS flood points.

    .venv/bin/python tools/build_history.py [--events PATH] [--points PATH] [--sections PATH] [--out PATH]

Run from 11_Platform_Draft. Inputs (read only; BANJIR_RAW_DIR, else ../05_Raw_Data_Sources):
  shah_alam/flood_history/events.json           the curated events (every one with an opened https source), the place
                                                names that map to a section, and the two dataset credits
  shah_alam/arcgis_flood_points/shah_alam.geojson   the 2021 and 2022 points of ArcGIS Online user d1anameera (reuse with
                                                credit approved by the user; the raw rows stay out of the repo)
  shah_alam/mbsa_sections/sections.geojson      the 56 sections (OSM, ODbL), read with tools/sections_io.py
Output: app/data/areas/_shah-alam/history.json, in the form app/history.py checks (the build stops on any problem).

A point goes to a section in this order: a section the report's own text names ("Seksyen 22", "Sek. 26"); a place name
events.json maps to a section ("Sri Muda"); the section that holds the point, or the nearest within 300 m. Points given
to only 2 decimals (about 1 km) go to a section only when the whole 0.01 degree square around them lies in it, else to the
city with no section. Points in a district the city does not reach, or beyond 300 m of every section, are dropped and
counted. Points are grouped by day (or by the layer's year when the row has no date) and section, into one event of
"N reports in a public YYYY dataset" with the depth range; dated groups are medium confidence, undated ones low. A group
on the day and in a section of a curated event becomes that event's second source instead.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import geo, history  # noqa: E402
import sections_io  # noqa: E402

DEFAULT_OUT = ROOT / "app" / "data" / "areas" / "_shah-alam" / "history.json"
CITY_DISTRICTS = frozenset({"", "?", "KLANG", "PETALING"})   # Shah Alam lies in these two districts
NEAR_M = 300               # a point this close to a section counts as in it
COARSE_HALF_DEG = 0.005    # half the square a 2-decimal coordinate stands for
STATED = re.compile(r"\b(?:seksyen|sek\.?)\s*(u?\d{1,2})\b", re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:\.\d+)?")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MAX_PLACES = 3


def raw_dir() -> Path:
    return sections_io.default_path().parents[2]   # <raw>/shah_alam/mbsa_sections/sections.geojson


def section_names(sections: list[dict]) -> dict:
    """{id: {"en": "Seksyen 25", "ms": "Seksyen 25"}} in the sections' order: the section's name on the map, a proper
    noun, in both languages (as the page and sections.json name it)."""
    return {s["id"]: {"en": s["name"], "ms": s["name"]} for s in sections}


def _clean(text) -> str:
    return " ".join(str(text or "").split()).strip(" ,.;")


def stated_section(text: str, known: set[str]) -> str | None:
    """The first known section the text names as "Seksyen N" or "Sek. N"."""
    for match in STATED.finditer(text):
        section_id = sections_io.slug(match.group(1).upper())
        if section_id in known:
            return section_id
    return None


def alias_section(text: str, aliases: dict) -> str | None:
    lowered = text.lower()
    return next((section for name, section in aliases.items() if name in lowered), None)


def _is_coarse(lon: float, lat: float) -> bool:
    return all(abs(round(v, 2) - v) < 1e-9 for v in (lon, lat))


def _held_by(lon: float, lat: float, sections: list[dict]) -> str | None:
    found = geo.containing(lon, lat, sections) or (geo.nearest_within(lon, lat, sections, NEAR_M) or (None,))[0]
    return found["id"] if found else None


def _coarse_place(lon: float, lat: float, sections: list[dict]) -> tuple[str, str | None]:
    centre = _held_by(lon, lat, sections)
    if centre is None:
        return ("outside", None)
    corners = [(lon + dx, lat + dy) for dx in (-COARSE_HALF_DEG, COARSE_HALF_DEG) for dy in (-COARSE_HALF_DEG, COARSE_HALF_DEG)]
    held = {(geo.containing(x, y, sections) or {}).get("id") for x, y in corners}
    return ("section", centre) if held == {centre} else ("city", None)


def place_point(feature: dict, sections: list[dict], aliases: dict) -> tuple[str, str | None]:
    """("section", id), ("city", None) when in the city but not surely in one section, or ("district" | "outside", None)
    for a point that is dropped."""
    props = feature.get("properties") or {}
    if "".join(str(props.get("DAERAH") or "").split()).upper() not in CITY_DISTRICTS:
        return ("district", None)
    text = _clean(props.get("KWSN_BANJIR"))
    named = stated_section(text, {s["id"] for s in sections}) or alias_section(text, aliases)
    if named:
        return ("section", named)
    lon, lat = feature["geometry"]["coordinates"]
    if _is_coarse(lon, lat):
        return _coarse_place(lon, lat, sections)
    held = _held_by(lon, lat, sections)
    return ("section", held) if held else ("outside", None)


def parse_depth(text) -> tuple[float, float] | None:
    """The smallest and largest number in a typed depth such as "0.1m – 0.3m", or None."""
    numbers = [float(n) for n in NUMBER.findall(str(text or ""))]
    return (min(numbers), max(numbers)) if numbers else None


def group_points(features: list[dict], sections: list[dict], aliases: dict) -> tuple[dict, dict]:
    """{(day or layer year, layer, section id or None): [points]} in input order, and the dropped points by reason."""
    groups: dict[tuple, list] = {}
    drops: Counter = Counter()
    for feature in features:
        if not feature.get("geometry"):
            drops["no point"] += 1
            continue
        status, section_id = place_point(feature, sections, aliases)
        if status in ("district", "outside"):
            drops[status] += 1
            continue
        props = feature["properties"]
        layer = str(props["source_layer"])
        key = (props.get("Date") or layer, layer, section_id)
        groups[key] = [*groups.get(key, []), feature]
    return groups, dict(drops)


def year_of(text: str) -> float:
    """A number inside the date's year that places it on the strip: the day, the middle of the month or of the year."""
    first, last = history.day_range(text)
    if len(text) == 4:
        return first.year + 0.5
    if len(text) == 7:
        return round(first.year + (first.month - 0.5) / 12, 2)
    days = date(first.year, 12, 31).timetuple().tm_yday
    return min(round(first.year + (first.timetuple().tm_yday - 0.5) / days, 2), first.year + 0.99)


def when_of(text: str) -> str:
    first, _ = history.day_range(text)
    return f"{first.day} {MONTHS[first.month - 1]} {first.year}" if len(text) == 10 else f"{text}, day not given"


def _places(points: list[dict]) -> str:
    """The places as the reports typed them, each once, the first few, then how many more."""
    names = [name for name in dict.fromkeys(_clean(p["properties"].get("KWSN_BANJIR")) for p in points) if name]
    if not names:
        return "Not named"
    more = len(names) - MAX_PLACES
    return "; ".join(names[:MAX_PLACES]) + (f"; and {more} more" if more > 0 else "")


def dataset_event(key: tuple, points: list[dict], datasets: dict) -> dict:
    """One event for a group of points: how many reports, where they were typed as being, and the depth range."""
    when, layer, section_id = key
    undated = len(when) == 4
    ranges = [r for r in (parse_depth(p["properties"].get("KEDALAMAN")) for p in points) if r]
    low, high = (min(r[0] for r in ranges), max(r[1] for r in ranges)) if ranges else (None, None)
    depth = None if low is None else (f"{low:g} m in the reports" if low == high else f"{low:g} to {high:g} m in the reports")
    count = len(points)
    return {"id": f"ds-{when}{'-undated' if undated else ''}-{section_id or 'city'}", "date": when,
            "when": when_of(when), "year": year_of(when), "place": _places(points),
            "sections": [section_id] if section_id else [], "depth": depth,
            "what": f"{count} report{'s' if count != 1 else ''} in a public {layer} dataset.",
            "sources": [{**datasets[layer], "type": "dataset"}], "confidence": "low" if undated else "medium",
            "account": False, "undated": undated}


def _covers(event: dict, day: str, section_id: str | None) -> bool:
    if len(event["date"]) != 10 or len(day) != 10:
        return False
    first, end = event["date"], event.get("date_end", event["date"])
    return first <= day <= end and (section_id is None or section_id in event["sections"])


def merge(curated: list[dict], groups: dict, datasets: dict) -> list[dict]:
    """The curated events, each with a year and with any dataset group it covers as an extra source, then the other
    groups as events of their own; oldest first."""
    events = [{**copy.deepcopy(e), "year": year_of(e["date"])} for e in curated]
    for key, points in groups.items():
        source = {**datasets[key[1]], "type": "dataset"}
        home = next((e for e in events if _covers(e, key[0], key[2])), None)
        if home is None:
            events.append(dataset_event(key, points, datasets))
        elif source not in home["sources"]:
            home["sources"] = [*home["sources"], source]
    return sorted(events, key=lambda e: (e["year"], e["id"]))


def build(curated_doc: dict, points_doc: dict, sections: list[dict], today: date | None = None) -> dict:
    """The checked history document. Raises history.HistoryError when anything in it is wrong."""
    today = today or date.today()
    groups, _ = group_points(points_doc.get("features", []), sections, curated_doc.get("place_sections", {}))
    doc = {"first_year": curated_doc["first_year"], "recent_from": curated_doc["recent_from"],
           "last_year": history.day_range(curated_doc["checked"])[0].year, "checked": curated_doc["checked"],
           "section_names": section_names(sections),
           "events": merge(curated_doc["events"], groups, curated_doc["datasets"])}
    found = history.problems(doc, today=today)
    if found:
        raise history.HistoryError("; ".join(found))
    return doc


def build_from_files(events: Path, points: Path, sections: Path, today: date | None = None) -> dict:
    return build(json.loads(Path(events).read_text(encoding="utf-8")), json.loads(Path(points).read_text(encoding="utf-8")),
                 sections_io.load_sections(sections), today)


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def summary(doc: dict, drops: dict) -> str:
    """Counts for the report: events by decade and confidence, per section, and the dropped points."""
    events = doc["events"]
    decades = Counter(f"{int(e['year']) // 10 * 10}s" for e in events)
    confidence = Counter(e["confidence"] for e in events)
    per_section = Counter(s for e in events for s in e["sections"])
    lines = [f"{len(events)} events ({sum(e['id'].startswith('ds-') for e in events)} from the dataset)",
             "by decade: " + ", ".join(f"{k} {v}" for k, v in sorted(decades.items())),
             "by confidence: " + ", ".join(f"{k} {confidence[k]}" for k in history.CONFIDENCE),
             "city only (no section): " + str(sum(not e["sections"] for e in events)),
             "per section: " + ", ".join(f"{k} {per_section[k]}" for k in doc["section_names"] if per_section[k]),
             "points dropped: " + (", ".join(f"{k} {v}" for k, v in sorted(drops.items())) or "none")]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    raw = raw_dir()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, default=raw / "shah_alam" / "flood_history" / "events.json")
    parser.add_argument("--points", type=Path, default=raw / "shah_alam" / "arcgis_flood_points" / "shah_alam.geojson")
    parser.add_argument("--sections", type=Path, default=sections_io.default_path())
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    doc = build_from_files(args.events, args.points, args.sections)
    points = json.loads(args.points.read_text(encoding="utf-8"))["features"]
    _, drops = group_points(points, sections_io.load_sections(args.sections),
                            json.loads(args.events.read_text(encoding="utf-8")).get("place_sections", {}))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps(doc), encoding="utf-8")
    print(f"wrote {args.out}\n{summary(doc, drops)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
