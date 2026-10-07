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

Flash flood potential (app/indexes.py) and our section score: the built indexes.json beside sections.json holds, for
every section, `flash` {mean score, share of its land squares in each class} and `score` {value, class, ratings} (the
flash and the score are null for a section with no land square, the score alone may be null), the city's own `flash`
and `score`, the method (`flash`, whose classes and breaks must be those of the flash flood potential files, and `score`
with its weights, deviations and citations) and `validation`, how the figures compare with the flood record. A section
is sent `indexes` {flash, score} (no ratings), the area's details `index_method` {flash, score, validation} and `layers`
{flash_flood (app/indexes.py layer), low_ground (app/lowground.py layer)}: null, or left out of a section, where there
are no files. While the area holds the
score back (area.json show_index_score false), nothing of it is sent: no `indexes.score`, no `index_method.score`, and
no score correlations or hotspot score ranks in the validation.

Flood record: an area's own area.json record, as before, else its built history.json (app/history.py for_scope), cut to
the city or to one section.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

from . import areas, geo, indexes, lowground, raster, tide
from . import history as flood_record

NEAREST_SECTION_M = 300   # a point in no (simplified) outline takes the nearest section this close, as the build does
RP_KEYS = tuple(str(rp) for rp in raster.RETURN_PERIODS)
SECTION_KEYS = ("id", "name", "bbox", "zoom", "outline", "area_km2", "counts")   # each needs these; others pass on
INDEX_KEYS = ("id", "name", "kind", "sector", "section")
SCORE_METHOD_KEYS = ("name", "summary", "weights_used", "weights_total", "classes", "breaks", "break_rule", "citations",
                     "deviations", "credit")
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
        index_doc(area.id)
        tide.check(area.id)
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


# ---------- indexes.json

@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def index_doc(area_id: str) -> Mapping | None:
    """The area's indexes.json, checked against its sections and the classes of its flash flood potential files; None
    for an area without one. Raises areas.AreaError, naming the area, for one that does not fit, and KeyError for an
    unknown area."""
    doc = areas.indexes_file(area_id)
    if doc is None:
        return None
    problems = _index_problems(doc, area_id)
    if problems:
        raise areas.AreaError(f"{area_id}: indexes.json: " + "; ".join(problems) + ".")
    return doc


def _index_problems(doc, area_id: str) -> list[str]:
    top = doc if isinstance(doc, Mapping) else {}
    found = top.get("sections")
    checks = {
        "an area not split into sections has no indexes.json": has_sections(areas.get(area_id)),
        "method must hold flash and score (with weights_used, classes, breaks, citations and deviations)":
            _is_method(top.get("method")),
        "validation must be an object": isinstance(top.get("validation"), Mapping),
        "sections must be exactly the ids of sections.json":
            isinstance(found, Mapping) and set(found) == {s["id"] for s in listed(area_id)},
    }
    failed = [problem for problem, passed in checks.items() if not passed]
    if failed:
        return failed[:1] if "not split" in failed[0] else failed
    classes = indexes.classes(area_id)
    problems = _flash_scale_problems(top["method"]["flash"], classes, indexes.breaks(area_id))
    figures = [*found.items(), *([("city", top["city"])] if "city" in top else [])]
    return problems + [f"{sid}: {problem}" for sid, one in figures for problem in _figure_problems(one, classes)]


def _is_method(method) -> bool:
    flash, score = (method.get(key) for key in ("flash", "score")) if isinstance(method, Mapping) else (None, None)
    texts = lambda items: isinstance(items, tuple) and all(areas._is_text(t) for t in items)  # noqa: E731
    return (isinstance(flash, Mapping) and isinstance(score, Mapping) and isinstance(score.get("weights_used"), Mapping)
            and all(isinstance(score.get(key), tuple) for key in ("classes", "breaks"))
            and texts(score.get("citations")) and texts(score.get("deviations")))


def _flash_scale_problems(flash: Mapping, classes, breaks) -> list[str]:
    """method.flash.classes and breaks, when the flash flood potential files are loaded, must be theirs: one place
    writes the breaks, so a build that disagrees is refused rather than sent."""
    if classes is None:
        return []
    return [] if (tuple(flash.get("classes", ())), tuple(flash.get("breaks", ()))) == (classes, breaks) else [
        "method.flash must give the classes and breaks of the flash flood potential files"]


def _figure_problems(figures, classes: tuple[str, ...] | None) -> list[str]:
    flash = figures.get("flash") if isinstance(figures, Mapping) else None
    share = flash.get("share") if isinstance(flash, Mapping) else None
    score = figures.get("score") if isinstance(figures, Mapping) else None
    checks = {
        "flash must be null or hold a mean score and the share of the area in each class": flash is None or (
            isinstance(share, Mapping) and areas._is_number(flash.get("mean"))
            and all(areas._is_number(v) for v in share.values())),
        "flash shares must be by the classes of the flash flood potential files":
            not isinstance(share, Mapping) or classes is None or tuple(share) == classes,
        "score must be null or hold a number value and a class": score is None or (
            isinstance(score, Mapping) and areas._is_number(score.get("value")) and areas._is_text(score.get("class"))),
        "score must be null where flash is": flash is not None or score is None,
    }
    return [problem for problem, passed in checks.items() if not passed]


def index_method(area_id: str) -> dict | None:
    """How the area's figures were worked out, as the page is sent it: {flash, score, validation}, the plain-text parts
    of the flash flood potential method (app/indexes.py), the score's classes, breaks, weights, citations and
    deviations and its data credit, and the validation. None without an indexes.json."""
    doc = index_doc(area_id)
    if doc is None:
        return None
    shown = areas.get(area_id).show_index_score   # the page shows the score only when this is true
    validation = areas._thaw(doc["validation"])
    if not shown:
        return {"flash": indexes.flash_method(area_id), "validation": _without_score(validation), "show_score": False}
    score = {key: areas._thaw(value) for key, value in doc["method"]["score"].items() if key in SCORE_METHOD_KEYS}
    return {"flash": indexes.flash_method(area_id), "score": score, "validation": validation, "show_score": True}


def _without_score(validation: dict) -> dict:
    """The validation less the score's own figures: its correlations (score_*) and the hotspots' score ranks."""
    found = dict(validation)
    if isinstance(found.get("spearman"), dict):
        found["spearman"] = {k: v for k, v in found["spearman"].items() if not k.startswith("score_")}
    if isinstance(found.get("hotspots"), list):
        found["hotspots"] = [{k: v for k, v in spot.items() if k != "score_rank"} if isinstance(spot, dict) else spot
                             for spot in found["hotspots"]]
    return found


def city_figures(area_id: str) -> Mapping | None:
    """The whole city's `flash` and `score` figures from the area's indexes.json, None without it or without a city."""
    doc = index_doc(area_id)
    return doc.get("city") if doc else None


def clear_caches() -> None:
    """Forget every area and section read so far (for tests that point areas.AREAS_DIR elsewhere)."""
    areas.clear_caches()
    for cached in (listed, _by_id, _aliases, city_index, section_premises, section_cells, index_doc):
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
             "history": history_for(area, section_id), "bigger_flood_example": area.bigger_flood_example,
             "flash_flood_example": area.flash_flood_example, "index_method": index_method(area.id),
             "losses": areas._thaw(area.losses),
             "layers": {"flash_flood": indexes.layer(area.id), "low_ground": lowground.layer(area.id)}}
    if has_sections(area):
        found.update(section_word=areas._thaw(area.section_word), default_section=area.default_section)
    return found


def public(section: Mapping, area_id: str | None = None) -> dict:
    """A section as the page is sent it: its sections.json entry as built and, when its area (area_id) has an
    indexes.json, its `indexes` {flash: {mean, share}, score: {value, class} | null}; no `score` at all while the area
    holds the score back (area.json show_index_score false)."""
    sent = areas._thaw(section)
    doc = index_doc(area_id) if area_id else None
    if doc is not None:
        figures = doc["sections"][section["id"]]
        score = figures.get("score")
        sent["indexes"] = {"flash": areas._thaw(figures["flash"]) if figures.get("flash") else None}
        if areas.get(area_id).show_index_score:   # held back until its comparison with past floods is reviewed
            sent["indexes"]["score"] = {"value": score["value"], "class": score["class"]} if score else None
    return sent


@lru_cache(maxsize=areas.MAX_CACHED_AREAS)
def city_index(area_id: str) -> tuple[dict, ...]:
    """One lean row per business of the area, {id, name, kind, sector, section, road: {name}, depth_m}, for the city's
    search and table."""
    return tuple({**{key: premise.get(key) for key in INDEX_KEYS}, "road": {"name": premise["road"]["name"]},
                  "depth_m": premise["depth_m"]} for premise in areas.premises(area_id))


def city_data(area: areas.Area) -> dict:
    """GET /api/areas/{id}/data for a split area, less the limits main.py adds."""
    built = areas.town(area.id)
    return {"area": details(area), "sections": [public(section, area.id) for section in listed(area.id)],
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
    return {"area": details(area, section["id"]), "section": public(section, area.id),
            "sections": [{"id": item["id"], "name": item["name"]} for item in listed(area.id)],
            "town": town, "premises": section_premises(area.id, section["id"])}
