"""Curated areas. Each folder in app/data/areas is one area: area.json (its config) beside the built
premises.json (mapped businesses) and town.json (flood squares and relief centres).

area.json fields:
  id            the folder name: lower-case letters, digits and single hyphens
  default       true for exactly one area, the one the page opens on (optional, false)
  name          short name for sentences, such as "Showing {name}"
  display_name  longer name for lists and headings
  view          [west, south, east, north] in degrees; the built data lies inside it
  zoom          the map's starting zoom
  ai_name       where the chat assistant's businesses are, filled into its system prompt
  news_place    the place named in the fixed flood news question
  news_region   the wider region the flood news search covers
  council       the local council's short name, or null when no source names one (optional)
  notes         where the area's data came from, by topic (optional)
  history       dated floods from the sources checked, or null when none were collected (optional)

The config is part of the repo, so it is trusted, but it is still checked (load_all, and preload at start-up):
a typo stops the server at start-up instead of failing in the middle of a chat. Folders whose names start with
"." or "_" are not areas and are skipped.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from . import elevation

AREAS_DIR = Path(__file__).parent / "data" / "areas"
AREA_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
MAX_ID_CHARS = 40
MAX_ZOOM = 19
TEXT_FIELDS = ("name", "display_name", "ai_name", "news_place", "news_region")
REQUIRED = frozenset({"id", "view", "zoom", *TEXT_FIELDS})
OPTIONAL = {"default": False, "council": None, "notes": {}, "history": None}
HISTORY_YEARS = ("first_year", "recent_from", "last_year")
FLOOD_TEXTS = ("when", "what", "source")
SKIPPED_PREFIXES = (".", "_")   # hidden or parked folders, never an area id
MAX_CACHED_AREAS = 32


class AreaError(ValueError):
    """An area folder whose config is missing or malformed."""


@dataclass(frozen=True)
class Area:
    """One curated area, as its area.json describes it."""

    id: str
    name: str
    display_name: str
    view: tuple[float, float, float, float]   # west, south, east, north
    zoom: int
    ai_name: str
    news_place: str
    news_region: str
    council: str | None = None
    is_default: bool = False
    notes: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}), hash=False)
    history: Mapping | None = field(default=None, hash=False, repr=False)   # read-only, as _freeze leaves it

    def contains(self, lat: float, lon: float) -> bool:
        west, south, east, north = self.view
        return west <= lon <= east and south <= lat <= north

    def centre(self) -> tuple[float, float]:
        """(lat, lon) of the middle of the view."""
        west, south, east, north = self.view
        return (south + north) / 2, (west + east) / 2


def load_all(root: Path | None = None) -> tuple[Area, ...]:
    """Every area under root (app/data/areas by default): the default first, then by name.

    Raises AreaError, naming the folder and the reason, if any folder is not a well-formed area. Only the app's
    own folder is cached; another root (a test's) is read afresh each time."""
    return _app_areas() if root is None else _load_root(root)


@lru_cache(maxsize=1)
def _app_areas() -> tuple[Area, ...]:
    return _load_root(AREAS_DIR)


def _load_root(root: Path) -> tuple[Area, ...]:
    folders = [folder for folder in sorted(root.iterdir())
               if folder.is_dir() and not folder.name.startswith(SKIPPED_PREFIXES)]
    found = tuple(_load(folder) for folder in folders)
    defaults = [area.id for area in found if area.is_default]
    if len(defaults) != 1:
        named = ", ".join(defaults) or "none"
        raise AreaError(f'Exactly one area must have "default": true; found {len(defaults)} ({named}).')
    return tuple(sorted(found, key=lambda area: (not area.is_default, area.name)))


def _load(folder: Path) -> Area:
    path = folder / "area.json"
    if not path.is_file():
        raise AreaError(f"{folder.name}: this folder has no area.json.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:   # bad JSON or bad UTF-8
        raise AreaError(f"{folder.name}: area.json is not valid JSON ({exc}).") from exc
    if not isinstance(raw, dict):
        raise AreaError(f"{folder.name}: area.json must hold one JSON object.")
    problems = _problems(raw, folder.name)
    if problems:
        raise AreaError(f"{folder.name}: " + "; ".join(problems) + ".")
    config = {**OPTIONAL, **raw}
    return Area(id=config["id"], name=config["name"], display_name=config["display_name"],
                view=tuple(config["view"]), zoom=config["zoom"], ai_name=config["ai_name"],
                news_place=config["news_place"], news_region=config["news_region"], council=config["council"],
                is_default=config["default"], notes=_freeze(config["notes"]), history=_freeze(config["history"]))


def _freeze(value):
    """A read-only copy of parsed JSON: objects become read-only mappings and arrays become tuples."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    """Plain dicts and lists again, as new objects, for a response."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _problems(raw: dict, folder: str) -> list[str]:
    """Everything wrong with one area.json, in plain words. Empty when it is fine."""
    missing = sorted(REQUIRED - raw.keys())
    unknown = sorted(raw.keys() - REQUIRED - OPTIONAL.keys())
    if missing or unknown:
        return [*([f"missing {', '.join(missing)}"] if missing else []),
                *([f"unknown field {', '.join(unknown)}"] if unknown else [])]
    config = {**OPTIONAL, **raw}
    checks = {
        f"id must match the folder name {folder!r}, in lower-case letters, digits and hyphens":
            config["id"] == folder and _is_id(folder),
        f"{', '.join(TEXT_FIELDS)} must be non-empty text": all(_is_text(config[name]) for name in TEXT_FIELDS),
        "council must be non-empty text or null": config["council"] is None or _is_text(config["council"]),
        "view must be [west, south, east, north] in degrees, west below east and south below north":
            _is_view(config["view"]),
        f"zoom must be a whole number from 1 to {MAX_ZOOM}":
            _is_whole(config["zoom"]) and 1 <= config["zoom"] <= MAX_ZOOM,
        "default must be true or false": isinstance(config["default"], bool),
        "notes must map topics to text": isinstance(config["notes"], dict)
            and all(_is_text(text) for text in config["notes"].values()),
        "history must be null, or hold first_year, recent_from, last_year in order and a list of floods dated "
        "within those years":
            config["history"] is None or _is_history(config["history"]),
    }
    return [problem for problem, passed in checks.items() if not passed]


def _is_id(text: str) -> bool:
    return len(text) <= MAX_ID_CHARS and AREA_ID.fullmatch(text) is not None


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return _is_whole(value) or (isinstance(value, float) and math.isfinite(value))


def _is_view(view) -> bool:
    if not (isinstance(view, list) and len(view) == 4 and all(_is_number(v) for v in view)):
        return False
    west, south, east, north = view
    return -180 <= west < east <= 180 and -90 <= south < north <= 90


def _is_history(history) -> bool:
    if not (isinstance(history, dict) and all(_is_whole(history.get(name)) for name in HISTORY_YEARS)):
        return False
    first, recent, last = (history[name] for name in HISTORY_YEARS)
    floods = history.get("floods")
    return (first <= recent <= last and isinstance(floods, list)
            and all(_is_flood(flood) and first <= flood["year"] < last + 1 for flood in floods))


def _is_flood(flood) -> bool:
    return (isinstance(flood, dict) and all(_is_text(flood.get(name)) for name in FLOOD_TEXTS)
            and _is_number(flood.get("year")) and isinstance(flood.get("account", False), bool))


@lru_cache(maxsize=1)
def _by_id() -> dict[str, Area]:
    return {area.id: area for area in load_all()}


def get(area_id: str) -> Area | None:
    """The area with this id, or None."""
    return _by_id().get(area_id) if isinstance(area_id, str) else None


def default() -> Area:
    """The area the page opens on."""
    return next(area for area in load_all() if area.is_default)


@lru_cache(maxsize=MAX_CACHED_AREAS)
def premises(area_id: str) -> tuple[dict, ...]:
    """The area's mapped businesses, each with its `elevation` (app/elevation.py: null where none is loaded) looked up
    once here at its own point. Raises KeyError for an unknown id."""
    return tuple({**premise, "elevation": elevation.at(premise["lat"], premise["lon"])}
                 for premise in _read(area_id, "premises.json"))


@lru_cache(maxsize=MAX_CACHED_AREAS)
def town(area_id: str) -> dict:
    """The area's view, flood squares and relief centres. Raises KeyError for an unknown id."""
    return _read(area_id, "town.json")


def _read(area_id: str, name: str):
    area = get(area_id)
    if area is None:
        raise KeyError(f"No area with id {area_id!r}.")
    return json.loads((AREAS_DIR / area.id / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _businesses() -> dict[str, tuple[dict, Area]]:
    pairs = [(premise["id"], (premise, area)) for area in load_all() for premise in premises(area.id)]
    index = dict(pairs)
    if len(index) != len(pairs):
        raise AreaError("A business id appears more than once; ids must be unique across all areas.")
    return index


def business(business_id: str) -> tuple[dict, Area] | None:
    """The business with this id and the area that holds it, from any area; None if there is none."""
    return _businesses().get(business_id) if isinstance(business_id, str) else None


def area_at(lat: float, lon: float) -> Area | None:
    """The first area (the default first) whose view holds the point, or None."""
    return next((area for area in load_all() if area.contains(lat, lon)), None)


def preload() -> None:
    """Read and check every area's config and data now, so a bad file or a repeated business id stops the server
    at start-up instead of failing a visitor's request."""
    for area in load_all():
        check_built(area, premises(area.id), town(area.id))
    _businesses()


def check_built(area: Area, shown: tuple, built) -> None:
    """Raise AreaError unless an area's built data fits its config."""
    checks = {
        "town.json must hold the same view as area.json":
            isinstance(built, dict) and built.get("view") == list(area.view),
        "town.json must list flood squares (cells) and relief centres (shelters)":
            isinstance(built, dict) and isinstance(built.get("cells"), list)
            and isinstance(built.get("shelters"), list),
        "every business in premises.json needs a text id and a point inside the view":
            all(isinstance(p, dict) and isinstance(p.get("id"), str) and _is_inside(area, p) for p in shown),
    }
    failed = [problem for problem, passed in checks.items() if not passed]
    if failed:
        raise AreaError(f"{area.id}: " + "; ".join(failed) + ".")


def _is_inside(area: Area, point: dict) -> bool:
    lat, lon = point.get("lat"), point.get("lon")
    return _is_number(lat) and _is_number(lon) and area.contains(lat, lon)


def counts(area: Area) -> dict[str, int]:
    built = town(area.id)
    return {"businesses": len(premises(area.id)), "squares": len(built["cells"]), "shelters": len(built["shelters"])}


def summary(area: Area) -> dict:
    """One entry of GET /api/areas."""
    found = counts(area)
    return {"id": area.id, "name": area.name, "display_name": area.display_name, "view": list(area.view),
            "zoom": area.zoom, "counts": found, "has_history": area.history is not None,
            "has_shelters": found["shelters"] > 0}


def details(area: Area) -> dict:
    """The area as GET /api/areas/{id}/data sends it: its summary plus its council, notes and flood history."""
    return {**summary(area), "council": area.council, "notes": _thaw(area.notes), "history": _thaw(area.history)}
