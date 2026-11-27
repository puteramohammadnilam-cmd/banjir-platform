"""Read an area's sections from a GeoJSON file: the 56 Shah Alam sections (OSM Seksyen 1 to 36 and U1 to U20, ODbL)
from sections.geojson, or any other set of outlines (a state's districts) whose features carry their own id.

    from sections_io import load_sections
    sections = load_sections()      # list of dicts: the 56 in natural order, 1 to 36, then U1 to U20

Each section: {id, name, number_label, osm_id, geometry, bbox, area_km2}. geometry is the GeoJSON Polygon or
MultiPolygon, bbox is (west, south, east, north), and area_km2 is on the sphere, worked out with app/geo.py (the method
tools/fetch_mbsa_sections.py uses).
  - Shah Alam's file (no feature has an "id"): the id is "seksyen-" plus the label in lower case ("seksyen-25",
    "seksyen-u13"); number_label is the label as OSM writes it ("25", "U13"); 56 are needed unless `expected` says.
  - A named set (every feature has an "id"): the id as given (lower case words and digits joined by "-", as in
    "kota-tinggi", since it goes in the page's address), the name as given, number_label None, in the file's order;
    any count unless `expected` says.
The default file is looked for in BANJIR_RAW_DIR when that is set, else in ../05_Raw_Data_Sources. Place words are
fine here: this is a tool, not app code.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import geo  # noqa: E402
from rawpaths import RAW_SOURCES  # noqa: E402

SECTION_WORD = "seksyen"
EXPECTED_SECTIONS = 56
NUMBERED = 36            # Seksyen 1 to 36
UPPER = 20               # Seksyen U1 to U20
LABEL = re.compile(r"^(U?)(\d{1,2})$")
NAME_LABEL = re.compile(r"^(?:Seksyen|Section)\s+(\S+)$", re.I)
NAMED_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SectionsError(ValueError):
    """The sections file is missing, or is not a set of well-formed sections."""


def default_path() -> Path:
    raw = Path(os.environ["BANJIR_RAW_DIR"]) if os.environ.get("BANJIR_RAW_DIR") else RAW_SOURCES
    return raw / "shah_alam" / "mbsa_sections" / "sections.geojson"


def slug(label: str) -> str:
    """The section id for a label: "25" -> "seksyen-25", "U13" -> "seksyen-u13"."""
    return f"{SECTION_WORD}-{label.lower()}"


def label_order(label: str) -> tuple[int, int]:
    """Sort key: the numbered sections first, 1 to 36, then the U ones, 1 to 20."""
    match = LABEL.match(label)
    if not match:
        raise SectionsError(f"Section label {label!r} is not a number 1 to {NUMBERED} or U1 to U{UPPER}.")
    prefix, digits = match.group(1), int(match.group(2))
    if not 1 <= digits <= (UPPER if prefix else NUMBERED):
        raise SectionsError(f"Section label {label!r} is outside 1 to {NUMBERED} and U1 to U{UPPER}.")
    return (1 if prefix else 0, digits)


def expected_ids() -> list[str]:
    """The 56 ids, in natural order."""
    labels = [str(n) for n in range(1, NUMBERED + 1)] + [f"U{n}" for n in range(1, UPPER + 1)]
    return [slug(label) for label in labels]


def _label_of(properties: dict) -> str:
    label = properties.get("section")
    if not label:
        match = NAME_LABEL.match(properties.get("name") or "")
        label = match.group(1) if match else ""
    return str(label).strip().upper()


def _shape(feature: dict, what: str) -> dict:
    geometry = feature.get("geometry") or {}
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise SectionsError(f"Section {what!r} has a {geometry.get('type')!r} geometry; a Polygon or MultiPolygon is needed.")
    return {"geometry": geometry, "bbox": geo.bbox(geometry), "area_km2": round(geo.geometry_area_km2(geometry), 3)}


def _section_of(feature: dict) -> dict:
    properties = feature.get("properties") or {}
    label = _label_of(properties)
    label_order(label)   # raises for a label that is not one of the 56
    return {"id": slug(label), "name": properties.get("name") or f"Seksyen {label}", "number_label": label,
            "osm_id": properties.get("osm_id"), **_shape(feature, label)}


def _named_of(feature: dict) -> dict:
    properties = feature.get("properties") or {}
    sid, name = str(properties.get("id") or ""), str(properties.get("name") or "").strip()
    if not NAMED_ID.match(sid):
        raise SectionsError(f"Section id {sid!r} is not lower case words and digits joined by '-'.")
    if not name:
        raise SectionsError(f"Section {sid!r} has no name.")
    return {"id": sid, "name": name, "number_label": None, "osm_id": properties.get("osm_id"), **_shape(feature, sid)}


def load_sections(path: Path | str | None = None, expected: int | None = None) -> list[dict]:
    """The sections: Shah Alam's in natural order, a named set in its file's order (see the module docstring). Raises
    SectionsError for a missing file, a bad label, id or geometry, a file that mixes the two kinds, a repeated id, or a
    count other than `expected` (by default 56 for Shah Alam's file, any for a named set)."""
    source = Path(path) if path else default_path()
    try:
        collection = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SectionsError(f"Cannot read the sections file {source}: {error}") from error
    features = collection.get("features", [])
    named = [bool((f.get("properties") or {}).get("id")) for f in features]
    if any(named) and not all(named):
        raise SectionsError(f"{source.name}: some features have an id and some do not; one kind of file is needed.")
    is_named = bool(features) and all(named)
    sections = [(_named_of if is_named else _section_of)(feature) for feature in features]
    ids = [s["id"] for s in sections]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise SectionsError(f"Section ids repeat: {', '.join(repeated)}.")
    want = expected if expected is not None else (None if is_named else EXPECTED_SECTIONS)
    if want is not None and len(sections) != want:
        raise SectionsError(f"Expected {want} sections, found {len(sections)}.")
    return sections if is_named else sorted(sections, key=lambda s: label_order(s["number_label"]))
