"""Flood history of an area split into sections: the built history.json beside its area.json (tools/build_history.py
writes it), checked on load, and cut to the whole area or to one section.

history.json:
  first_year, recent_from, last_year   the years the sources were searched, and the start of "recent"
  checked                              the day the sources were checked, "YYYY-MM-DD"
  section_names                        {section id: {"en": ..., "ms": ...}} for every section of the area
  events                               the floods, oldest first, each:
    id          lower-case letters, digits and hyphens, unique
    date        "YYYY", "YYYY-MM" or "YYYY-MM-DD", from first_year to today; date_end (optional) the same, not before it
    date_note   (optional) why the date is given as it is
    when        the date as words; year: a number inside the date's year, to place it on the strip
    place       the places as the sources name them
    sections    the section ids the sources place it in ([] when no source names a section)
    point       (optional) [lon, lat]
    depth       the depth as the sources give it, or null
    what        what happened, in our words
    sources     at least one {title, url (https only), type: news | official | dataset | paper}
    confidence  high | medium | low; account: true for one person's memory; undated (optional): no day or month given

No text may hold markup or a script link: the page shows it as text, but it is checked here all the same. A missing
record is not a dry record: a section with no event gets floods: [], and the page says no record was found.
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

AREAS_DIR = Path(__file__).parent / "data" / "areas"
FILE_NAME = "history.json"
FOLDER_ID = re.compile(r"_?[a-z0-9]+(?:-[a-z0-9]+)*")
EVENT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SECTION_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DAY = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?")
MARKUP = re.compile(r"[<>]|javascript:|vbscript:|data:text", re.IGNORECASE)
MAX_ID_CHARS = 80
EARLIEST_YEAR = 1992
CONFIDENCE = ("high", "medium", "low")
SOURCE_TYPES = ("news", "official", "dataset", "paper")
YEARS = ("first_year", "recent_from", "last_year")
EVENT_TEXTS = ("when", "place", "what")
LANGS = ("en", "ms")


class HistoryError(ValueError):
    """A history.json that is malformed, or a section the area does not have."""


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not MARKUP.search(value)


def _is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_https(url) -> bool:
    """An absolute https link with a host and no spaces, quotes or angle brackets."""
    if not isinstance(url, str) or re.search(r"[\s\"'<>\\]", url):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def day_range(text) -> tuple[date, date] | None:
    """The first and last day a "YYYY", "YYYY-MM" or "YYYY-MM-DD" date covers, or None when it is not one."""
    match = DAY.fullmatch(text) if isinstance(text, str) else None
    if not match:
        return None
    year, month, day = (int(part) if part else None for part in match.groups())
    try:
        if day:
            return date(year, month, day), date(year, month, day)
        if month:
            last = date(year + (month == 12), month % 12 + 1, 1).toordinal() - 1
            return date(year, month, 1), date.fromordinal(last)
        return date(year, 1, 1), date(year, 12, 31)
    except ValueError:
        return None


def _source_problems(where: str, source) -> list[str]:
    if not isinstance(source, dict):
        return [f"{where}: a source must be an object"]
    found = []
    if not _is_text(source.get("title")):
        found.append(f"{where}: a source title must be plain text, no markup")
    if not is_https(source.get("url")):
        found.append(f"{where}: a source url must be an https link")
    if source.get("type") not in SOURCE_TYPES:
        found.append(f"{where}: a source type must be one of {', '.join(SOURCE_TYPES)}")
    return found


def _date_problems(where: str, event: dict, first: int, today: date) -> list[str]:
    span = day_range(event.get("date"))
    if not span or span[0].year < first or span[0] > today:
        return [f"{where}: date must be YYYY, YYYY-MM or YYYY-MM-DD, from {first} to today"]
    found = []
    if "date_end" in event:
        end = day_range(event["date_end"])
        if not end or end[0] < span[0] or end[0] > today:
            found.append(f"{where}: date_end must be a date from the event's date to today")
    if "date_note" in event and not _is_text(event["date_note"]):
        found.append(f"{where}: date_note must be plain text, no markup")
    year = event.get("year")
    if not (isinstance(year, (int, float)) and not isinstance(year, bool) and math.floor(year) == span[0].year):
        found.append(f"{where}: year must be a number inside the date's year")
    return found


def _place_problems(where: str, event: dict, known) -> list[str]:
    found = []
    sections = event.get("sections")
    if not (isinstance(sections, list) and all(s in known for s in sections) and len(set(sections)) == len(sections)):
        found.append(f"{where}: sections must be known section ids, each once")
    point = event.get("point")
    if point is not None and not (isinstance(point, list) and len(point) == 2
                                  and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point)
                                  and -180 <= point[0] <= 180 and -90 <= point[1] <= 90):
        found.append(f"{where}: point must be [lon, lat] in degrees")
    if event.get("depth") is not None and not _is_text(event.get("depth")):
        found.append(f"{where}: depth must be plain text or null")
    return found


def _event_problems(index: int, event, known, first: int, today: date) -> list[str]:
    if not isinstance(event, dict):
        return [f"event {index}: must be an object"]
    event_id = event.get("id")
    where = f"event {event_id or index}"
    found = [] if isinstance(event_id, str) and len(event_id) <= MAX_ID_CHARS and EVENT_ID.fullmatch(event_id) else \
        [f"{where}: id must be lower-case letters, digits and hyphens"]
    found += [f"{where}: {name} must be plain text, no markup" for name in EVENT_TEXTS if not _is_text(event.get(name))]
    found += _date_problems(where, event, first, today) + _place_problems(where, event, known)
    sources = event.get("sources")
    if not (isinstance(sources, list) and sources):
        found.append(f"{where}: needs at least one source")
    else:
        found += [problem for source in sources for problem in _source_problems(where, source)]
    if event.get("confidence") not in CONFIDENCE:
        found.append(f"{where}: confidence must be one of {', '.join(CONFIDENCE)}")
    if not isinstance(event.get("account"), bool) or not isinstance(event.get("undated", False), bool):
        found.append(f"{where}: account and undated must be true or false")
    return found


def _names_problems(names) -> list[str]:
    if not (isinstance(names, dict) and names):
        return ["section_names must map section ids to names"]
    bad = [key for key, value in names.items() if not (isinstance(key, str) and SECTION_ID.fullmatch(key)
           and isinstance(value, dict) and all(_is_text(value.get(lang)) for lang in LANGS))]
    return [f"section_names: {key!r} needs a lower-case id and en and ms names" for key in bad]


def problems(doc, today: date | None = None) -> list[str]:
    """Everything wrong with a history document, as sentences; [] when it is sound."""
    today = today or date.today()
    if not isinstance(doc, dict):
        return ["the history must be an object"]
    years = [doc.get(name) for name in YEARS]
    if not (all(_is_whole(y) for y in years) and EARLIEST_YEAR <= years[0] <= years[1] <= years[2] <= today.year):
        return [f"years: first_year, recent_from, last_year must be whole years in order, {EARLIEST_YEAR} to today"]
    found = _names_problems(doc.get("section_names"))
    if day_range(doc.get("checked")) is None:
        found.append("checked must be the day the sources were checked, YYYY-MM-DD")
    events = doc.get("events")
    if not isinstance(events, list):
        return [*found, "events must be a list"]
    known = doc.get("section_names") if isinstance(doc.get("section_names"), dict) else {}
    for index, event in enumerate(events):
        found += _event_problems(index, event, known, years[0], today)
    ids = [event.get("id") for event in events if isinstance(event, dict)]
    found += [f"event ids must be unique: {i} repeats" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return found


@lru_cache(maxsize=8)
def load(path: str) -> dict | None:
    """The checked history at `path`, or None when there is no such file. Raises HistoryError for a bad one."""
    source = Path(path)
    if not source.is_file():
        return None
    try:
        doc = json.loads(source.read_text(encoding="utf-8"))
    except ValueError as error:
        raise HistoryError(f"{source}: not JSON ({error})") from error
    found = problems(doc)
    if found:
        raise HistoryError(f"{source}: " + "; ".join(found))
    return doc


def _years_of(flood: dict) -> range:
    start = day_range(flood["date"])[0].year
    end = day_range(flood["date_end"])[1].year if flood.get("date_end") else start
    return range(start, end + 1)


def gaps(floods: list[dict], first: int, last: int) -> list[list[int]]:
    """The runs of years, [from, to], with no flood record in `floods`."""
    covered = {year for flood in floods for year in _years_of(flood)}
    runs: list[list[int]] = []
    for year in range(first, last + 1):
        if year in covered:
            continue
        if runs and runs[-1][1] == year - 1:
            runs[-1] = [runs[-1][0], year]
        else:
            runs.append([year, year])
    return runs


def _flood(event: dict) -> dict:
    """An event in the page's flood shape: today's when, year, what, source, account, plus the new fields."""
    sources = copy.deepcopy(event["sources"])
    return {**copy.deepcopy(event), "sources": sources, "undated": event.get("undated", False),
            "source": "; ".join(source["title"] for source in sources), "url": sources[0]["url"],
            "source_type": sources[0]["type"]}


def for_scope(area_id: str, section_id: str | None = None, folder: Path = AREAS_DIR) -> dict | None:
    """The area's flood record for the whole area (section_id None) or one section: {first_year, recent_from,
    last_year, scope, checked, section_names, gaps, floods}. None when the area has no history.json. Raises
    HistoryError for a section the area does not have. The answer is a fresh copy."""
    if not (isinstance(area_id, str) and FOLDER_ID.fullmatch(area_id)):
        return None
    doc = load(str(Path(folder) / area_id / FILE_NAME))
    if doc is None:
        return None
    names = doc["section_names"]
    if section_id is not None and section_id not in names:
        raise HistoryError("Unknown section.")
    floods = [_flood(e) for e in doc["events"] if section_id is None or section_id in e["sections"]]
    used = {s for flood in floods for s in flood["sections"]} | ({section_id} if section_id else set())
    return {**{name: doc[name] for name in YEARS}, "scope": section_id, "checked": doc["checked"],
            "section_names": {key: dict(value) for key, value in names.items() if key in used},
            "gaps": gaps(floods, doc["first_year"], doc["last_year"]), "floods": floods}
