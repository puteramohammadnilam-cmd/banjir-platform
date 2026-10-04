"""Areas split into sections: one city in one set of built data, with a page for the city and one for each section.

The built sections.json beside the area's data (app/areas.py reads it) holds the city's totals and `sections`, the
sections in their own order (1 to 36, then U1 to U20 for the first city), each as

    {"id", "name", "bbox": [west, south, east, north], "zoom", "outline": a simplified GeoJSON Polygon or
     MultiPolygon, "area_km2",
     "counts": {"businesses", "cells", "wet_businesses": {"10", "20", "50"}, "wet_cells": {"10", "20", "50"}}}

Each business in premises.json names its section by id. Words for a section, its ids and other names live in the data
(area.json section_word and aliases, sections.json), never here.

What the page is sent (GET /api/areas/{id}/data and /api/areas/{id}/sections/{sid}/data, see main.py):
  city     the area's details with the city's flood record, every section (outline and counts), a lean `index` row per
           business, the town with its relief centres but no squares, and no premises
  section  the details with the section's own flood record, the section, every section's id and name, the town cut to
           the section (view = its bbox, the squares that overlap it, every relief centre of the city) and the section's
           businesses in full

Squares overlapping a box: the rule of the page's place.js overlapsView, so the squares sent with a section are the
ones the page itself draws for that box; tests/fixtures/overlap_cases.json pins both to the same answers.

Flood record: an area's own area.json record, as before, else its built history.json (app/history.py for_scope), cut to
the city or to one section.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

from . import areas, geo, raster
from . import history as flood_record

NEAREST_SECTION_M = 300   # a point in no (simplified) outline takes the nearest section this close, as the build does
RP_KEYS = tuple(str(rp) for rp in raster.RETURN_PERIODS)
SECTION_KEYS = ("id", "name", "bbox", "zoom", "outline", "area_km2", "counts")   # each needs these; others pass on
INDEX_KEYS = ("id", "name", "kind", "sector", "section")
MAX_CACHED = 128
WORD = re.compile(r"\w+")


# ---------- the sections of an area

def has_sections(area: areas.Area) -> bool:
    return areas.sections_file(area.id) is not None


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def listed(area_id: str) -> tuple[Mapping, ...]:
    """The area's sections in their own order, checked; () for an area not split into sections. Raises
    areas.AreaError for a malformed sections.json and KeyError for an unknown area."""
    doc = areas.sections_file(area_id)
    if doc is None:
        return ()
    found = doc.get("sections") if isinstance(doc, Mapping) else None
    if not isinstance(found, tuple):
        raise areas.AreaError(f"{area_id}: sections.json must hold a list of sections.")
    problems = [f"section {index + 1}: {problem}" for index, item in enumerate(found) for problem in _problems(item)]
    ids = [item["id"] for item in found if isinstance(item, Mapping) and "id" in item]
    if len(set(ids)) != len(ids):
        problems.append("section ids repeat")
    if problems or not found:
        raise areas.AreaError(f"{area_id}: sections.json: " + ("; ".join(problems) or "no sections") + ".")
    return tuple(found)


def _problems(item) -> list[str]:
    if not isinstance(item, Mapping) or set(SECTION_KEYS) - item.keys():
        return [f"needs {', '.join(SECTION_KEYS)}"]
    counts = item["counts"]
    checks = {
        "id must be lower-case letters, digits and hyphens": isinstance(item["id"], str) and areas._is_id(item["id"]),
        "name must be text": areas._is_text(item["name"]),
        "bbox must be [west, south, east, north]": isinstance(item["bbox"], tuple) and areas._is_view(
            list(item["bbox"])),
        f"zoom must be a whole number from 1 to {areas.MAX_ZOOM}":
            areas._is_whole(item["zoom"]) and 1 <= item["zoom"] <= areas.MAX_ZOOM,
        "outline must be a Polygon or MultiPolygon": _is_outline(item["outline"]),
        "area_km2 must be a number": areas._is_number(item["area_km2"]),
        "counts must hold businesses, cells and wet_businesses and wet_cells by flood size":
            isinstance(counts, Mapping) and all(areas._is_whole(counts.get(name)) for name in ("businesses", "cells"))
            and all(_is_by_flood_size(counts.get(name)) for name in ("wet_businesses", "wet_cells")),
    }
    return [problem for problem, passed in checks.items() if not passed]


def _is_by_flood_size(counts) -> bool:
    return isinstance(counts, Mapping) and all(areas._is_whole(counts.get(rp)) for rp in RP_KEYS)


def _is_outline(outline) -> bool:
    try:
        return isinstance(outline, Mapping) and all(len(polygon) and all(len(ring) >= 4 for ring in polygon)
                                                    for polygon in geo.polygons_of(outline))
    except (ValueError, TypeError, KeyError):
        return False


def get(area: areas.Area, section_id) -> Mapping | None:
    """The area's section with exactly this id, or None."""
    return _by_id(area.id).get(section_id) if isinstance(section_id, str) else None


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def _by_id(area_id: str) -> dict[str, Mapping]:
    return {section["id"]: section for section in listed(area_id)}


def ref(area: areas.Area | None, section_id) -> dict | None:
    """{id, name} of the area's section with this id, or None."""
    section = get(area, section_id) if area else None
    return {"id": section["id"], "name": section["name"]} if section else None


def alias(alias_id) -> tuple[areas.Area, Mapping] | None:
    """(area, section) for an alias id in an area.json, such as the id of an area before it was split; else None."""
    return _aliases().get(alias_id) if isinstance(alias_id, str) else None


@lru_cache(maxsize=1)
def _aliases() -> dict[str, tuple[areas.Area, Mapping]]:
    return {entry["id"]: (area, get(area, entry["section"])) for area in areas.load_all() for entry in area.aliases}


def preload() -> None:
    """Check every area's sections and flood record now, so a bad sections.json or history.json, or an alias that
    clashes, stops the server at start-up rather than answering a page with a 500."""
    for area in areas.load_all():
        listed(area.id)
        _check_history(area)
    found = [entry["id"] for area in areas.load_all() for entry in area.aliases]
    clashes = sorted({alias_id for alias_id in found if found.count(alias_id) > 1 or areas.get(alias_id)})
    if clashes:
        raise areas.AreaError(f"An alias repeats or is also an area id: {', '.join(clashes)}.")
    _aliases()


def _check_history(area: areas.Area) -> None:
    """The area's history.json, if it has one, is sound and, for an area split into sections, names exactly its
    sections (section_names keys == the sections.json ids). Raises areas.AreaError otherwise."""
    try:
        doc = flood_record.load(str(areas.AREAS_DIR / area.id / flood_record.FILE_NAME))
    except flood_record.HistoryError as error:
        raise areas.AreaError(str(error)) from error   # it names the file
    if doc is None or not has_sections(area):
        return
    named, ids = set(doc["section_names"]), {section["id"] for section in listed(area.id)}
    if named != ids:
        odd = ", ".join(sorted(named ^ ids))
        raise areas.AreaError(f"{area.id}: history.json section_names must be the sections.json ids; differ: {odd}.")


def clear_caches() -> None:
    """Forget every area and section read so far (for tests that point areas.AREAS_DIR elsewhere)."""
    areas.clear_caches()
    for cached in (listed, _by_id, _aliases, city_index, section_premises, section_cells):
        cached.cache_clear()


# ---------- finding a section

def _words(area: areas.Area, text: str) -> str:
    """Text reduced for matching: lower case, the section words of the area left out, the rest run together, so
    "Section U 13", "u13" and an id ending "-u13" all give "u13"."""
    skipped = {word.casefold() for word in (area.section_word or {}).values()}
    return "".join(word for word in WORD.findall(text.casefold()) if word not in skipped)


def find_section(area: areas.Area | None, text) -> Mapping | None:
    """The area's section that text names: by its id, its name or number (with or without the section word), or by an
    alias's id or name. None when nothing matches or the area has no sections."""
    if area is None or not isinstance(text, str) or not has_sections(area):
        return None
    wanted = _words(area, text)
    if not wanted:
        return None
    for section in listed(area.id):
        if wanted in (_words(area, section["id"]), _words(area, section["name"])):
            return section
    for entry in area.aliases:
        if wanted in {_words(area, name) for name in (entry["id"], *entry["names"])}:
            return get(area, entry["section"])
    return None


def section_at(area: areas.Area, lat: float, lon: float) -> Mapping | None:
    """The section whose outline holds the point, else the nearest within NEAREST_SECTION_M, else None. The first in the
    list wins on a shared edge. It reads the simplified outlines of sections.json (about 10 m tolerance), while the
    build assigned businesses and squares to sections on the full outlines, so a point within about 10 m of a boundary
    may get the neighbouring section here."""
    items = [{"geometry": section["outline"], "bbox": tuple(section["bbox"]), "section": section}
             for section in listed(area.id)]
    found = geo.containing(lon, lat, items)
    if found is None:
        near = geo.nearest_within(lon, lat, items, NEAREST_SECTION_M)
        found = near[0] if near else None
    return found["section"] if found else None


def listed_area_at(lat: float, lon: float) -> tuple[areas.Area | None, Mapping | None]:
    """(area, section) for a point: the first area (the default first) whose view holds it, with its section when the
    area is split into sections. A point in a split area's view but in none of its sections is in no area there."""
    for area in areas.load_all():
        if not area.contains(lat, lon):
            continue
        if not has_sections(area):
            return area, None
        section = section_at(area, lat, lon)
        if section is not None:
            return area, section
    return None, None


def centre(section: Mapping) -> tuple[float, float]:
    """(lat, lon) of the middle of a section's bbox."""
    west, south, east, north = section["bbox"]
    return (south + north) / 2, (west + east) / 2


def news_place(area: areas.Area, section: Mapping | None) -> str:
    """The place the fixed news question names: the area's, or the section's with its other names, then the area's."""
    if section is None:
        return area.news_place
    names = [name for entry in area.aliases if entry["section"] == section["id"] for name in entry["names"]]
    also = f" ({', '.join(names)})" if names else ""
    return f"{section['name']}{also}, {area.news_place}"


# ---------- flood record

def history_for(area: areas.Area, section_id: str | None = None) -> dict | None:
    """The flood record for the area (section_id None) or one of its sections, as the page shows it; None when none was
    collected. An area's own area.json record wins for the whole area; else its history.json (app/history.py), which
    raises history.HistoryError for a section it does not know."""
    if section_id is None and area.history is not None:
        return areas._thaw(area.history)
    return flood_record.for_scope(area.id, section_id, folder=areas.AREAS_DIR)


# ---------- what the page is sent

def summary(area: areas.Area) -> dict:
    """One entry of GET /api/areas: areas.summary with whether a flood record was collected, whether the area is split
    into sections and its aliases."""
    return {**areas.summary(area), "has_history": history_for(area) is not None, "has_sections": has_sections(area),
            "aliases": areas._thaw(area.aliases)}


def details(area: areas.Area, section_id: str | None = None) -> dict:
    """The `area` of a data answer: the summary, council, notes, the flood record of the area or the section, the
    bigger flood example and, for a split area, the section word and the default section."""
    found = {**summary(area), "council": area.council, "notes": areas._thaw(area.notes),
             "history": history_for(area, section_id), "bigger_flood_example": area.bigger_flood_example}
    if has_sections(area):
        found.update(section_word=areas._thaw(area.section_word), default_section=area.default_section)
    return found


def public(section: Mapping) -> dict:
    """A section as the page is sent it: its sections.json entry as built."""
    return areas._thaw(section)


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def city_index(area_id: str) -> tuple[dict, ...]:
    """One lean row per business of the area, {id, name, kind, sector, section, road: {name}, depth_m}, for the city's
    search and table."""
    return tuple({**{key: premise.get(key) for key in INDEX_KEYS}, "road": {"name": premise["road"]["name"]},
                  "depth_m": premise["depth_m"]} for premise in areas.premises(area_id))


def city_data(area: areas.Area) -> dict:
    """GET /api/areas/{id}/data for a split area, less the limits main.py adds."""
    built = areas.town(area.id)
    return {"area": details(area), "sections": [public(section) for section in listed(area.id)],
            "index": city_index(area.id), "town": {**built, "cells": []}, "premises": []}


@lru_cache(maxsize=MAX_CACHED)
def section_premises(area_id: str, section_id: str) -> tuple[dict, ...]:
    return tuple(premise for premise in areas.premises(area_id) if premise.get("section") == section_id)


def overlaps_view(view, south: float, west: float, px: float, py: float) -> bool:
    """Whether a square (south-west corner, size px by py degrees) overlaps a [west, south, east, north] box. Touching
    from outside is not overlapping. The rule of place.js overlapsView."""
    return (isinstance(view, (list, tuple)) and len(view) == 4 and west < view[2] and west + px > view[0]
            and south < view[3] and south + py > view[1])


@lru_cache(maxsize=MAX_CACHED)
def section_cells(area_id: str, section_id: str) -> tuple[list, ...]:
    """The area's squares that overlap the section's bbox, in town.json order. The square is cell_deg on each side."""
    area = areas.get(area_id)
    built, section = areas.town(area_id), get(area, section_id)
    size = built["cell_deg"]
    return tuple(cell for cell in built["cells"] if overlaps_view(section["bbox"], cell[0], cell[1], size, size))


def section_data(area: areas.Area, section: Mapping) -> dict:
    """GET /api/areas/{id}/sections/{sid}/data, less the limits main.py adds."""
    built = areas.town(area.id)
    town = {**built, "view": list(section["bbox"]), "cells": section_cells(area.id, section["id"])}
    return {"area": details(area, section["id"]), "section": public(section),
            "sections": [{"id": item["id"], "name": item["name"]} for item in listed(area.id)],
            "town": town, "premises": section_premises(area.id, section["id"])}
