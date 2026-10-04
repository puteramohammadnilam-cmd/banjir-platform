"""Read-only lookups over the built data. These are also the tools the AI model may call.

Gemini reads each tool's docstring as the tool's description, so no docstring names a place. A chat question's scope
(start_question) holds its area, the section of it the user is looking at (for an area split into sections) and the
place the user selected, and the area's config fills the prompts. The section words and names come from the data.

Tools take a place id: a mapped business from any area, or SELECTED ("selected") for the place the user selected, which
is looked up here on the server. The model is never told a point's id or coordinates, and no tool result for a point
holds them, so nothing the model says or is asked can give away where the user is. Every point id a tool is sent is
refused: the model never has one, so one that arrives was made up or planted in text it read (a name on the map, a
search result), and it cannot steer a tool to read depths somewhere else or for coordinates that came from Google.
Names from the map and from Google are cleaned before the model sees them.
"""
from __future__ import annotations

import contextvars
from collections.abc import Mapping
from dataclasses import dataclass, replace

from . import areas, costs, googlemaps, places, sections

SCENARIOS = {"10": "a flood expected once in 10 years", "20": "a flood expected once in 20 years",
             "50": "a flood expected once in 50 years"}
LIMITS = (
    "Depths come from a global computer model (European Commission JRC, 90 m squares). "
    "It is not an official Malaysian flood map and not a record of real floods. "
    "It ignores local flood walls, pumps and floor heights. Several shops can share one square. "
    "It shows floods of three sizes, 1 in 10, 20 and 50 years; floods bigger than 1 in 50 years are not in the "
    "model, so a rarer, bigger flood can bring deeper water than any depth here. "
    "Flash flood potential is susceptibility from slope, land cover, soil and vegetation, not a water depth or a "
    "chance of flooding; flash floods are not in the river model. "
    "Businesses are points on a public map and have not been checked on the ground."
)
SCORE_MEANING = ("Our own rough ranking of sections from several map criteria: not a model, not a water depth and "
                 "not a chance of flooding.")
HIGH_CLASSES = ("high", "extreme")   # the flash flood potential classes that count as high in the city ranking
NO_SHELTERS = ("This tool has no relief centre list for this area yet. "
               "Ask the authorities: JPS Public Infobanjir, {council} or 999.")
NO_AREA = ("The user picked a point outside the listed areas, so this tool has no area summary and no list of "
           "mapped businesses for it.")
SELECTED = "selected"                     # the place_id the model gives for the place the user selected
SELECTED_POINT = "the selected point"     # how a tool result names a selected point: never by its id
POINT_ID_REFUSED = ('Point ids are not accepted. Use "selected" for the point the user picked; for any other spot, '
                    "ask the user to pick it on the map.")
NOTHING_SELECTED = ('Nothing is selected, so "selected" stands for nothing. Use a business id from find_business, '
                    "or ask the user to pick a point on the map.")
UNKNOWN_BUSINESS = "No business with that id. Call find_business first."
NOT_COVERED = "That point is not in the flood model."
NOT_A_BUSINESS = "A point picked on the map is not a business, so it has no Google Maps listing."
MAX_MATCHES = 8
MAX_DRY_NAMES = 15        # area_summary names this many businesses that stay dry, then gives the count
MAX_TOP_SECTIONS = 10     # area_summary of a whole split area: the sections with the most businesses with water
MAX_FLOODS = 20           # flood_history: the most recent records, then the count
KEY_RP = "50"             # the flood size area_summary ranks sections by: the largest the model has
UNKNOWN_SECTION = ('No section by that name. Use a section name or number as the prompt or find_business gives it, or '
                   '"" for the whole area.')
NO_SECTIONS = 'This area is not split into sections. Use "" for the whole area.'
NO_RECORD = ("No record in the sources checked is not proof that a place has never flooded: say only that no record "
             "was found.")
NO_HISTORY = "No flood records have been collected for this area. " + NO_RECORD
RECORDS_AND_MODEL = ("The records include flash floods from heavy rain and blocked drains; the flood model shows only "
                     "rivers overflowing. So a place can have records where the model shows no water, and the other "
                     "way round: give both, and do not use one to dismiss the other.")
RAIN_HOURS = 12
WEATHER_DECIMALS = 2   # a point outside the listed areas goes to Google Weather rounded to 0.01 degrees, about 1 km
# What rain_forecast passes on from googlemaps.rain_outlook: the forecast only, never where it was asked for
RAIN_FIELDS = ("hours", "total_mm", "max_chance_pct", "wettest", "now", "first_hour", "source")
MAPS_OFF = "Google Maps is not set up in this build, so this cannot be checked."
MAPS_DOWN = "Google Maps did not answer just now. Try again later."
MAX_MAPS_LOOKUPS = 3   # per chat question, so a model told to check every shop cannot run up the bill
MAPS_SPENT = "Enough Google lookups for one question. Answer with what you have."
ESTIMATE_MAX = {"value_at_risk_rm": 50_000_000, "floor_height_cm": 300, "daily_takings_rm": 1_000_000,
                "closed_days": 365, "raise_cm": 300, "measure_cost_rm": 50_000_000}


@dataclass(frozen=True)
class QuestionScope:
    """What one chat question works within: its area (None for a point outside the listed areas), the id of the
    place the user selected (None when nothing is selected), how many Google lookups it has left, and the section of
    the area the question is about (None for the whole area, or an area not split into sections)."""

    area: areas.Area | None
    place: str | None
    maps_left: int
    section: Mapping | None = None


_scope: contextvars.ContextVar[QuestionScope | None] = contextvars.ContextVar("question_scope", default=None)


def current_area() -> areas.Area | None:
    """The area of the chat question being answered, None for a point outside the listed areas. Outside a question
    (a test or a script): the default area."""
    scope = _scope.get()
    return scope.area if scope else areas.default()


def current_section() -> Mapping | None:
    """The section the chat question being answered is about, if any."""
    scope = _scope.get()
    return scope.section if scope else None


def _section_name(area: areas.Area | None, section_id) -> str | None:
    found = sections.get(area, section_id) if area else None
    return _clean(found["name"]) if found else None


def selected_place() -> str | None:
    """The id of the place selected for the chat question being answered, if any. For the server only: the model
    names a selected point SELECTED, never by this id."""
    scope = _scope.get()
    return scope.place if scope else None


def premises() -> tuple[dict, ...]:
    """The current area's mapped businesses; none for a point outside the listed areas."""
    area = current_area()
    return areas.premises(area.id) if area else ()


def town() -> dict:
    """The current area's view, flood squares and relief centres; none for a point outside the listed areas."""
    area = current_area()
    return areas.town(area.id) if area else {"view": None, "cells": [], "shelters": []}


def get(business_id: str) -> dict | None:
    """A business from any area, by id. None for an unknown id or one that is not text."""
    found = areas.business(business_id)
    return found[0] if found else None


def no_shelters(area: areas.Area) -> str:
    council = f"the local council ({area.council})" if area.council else "the local council"
    return NO_SHELTERS.format(council=council)


def _area_notes(area: areas.Area | None) -> dict:
    """Where an area's data came from, when its config says (such as relief centres named in the news)."""
    return {"area_notes": dict(area.notes)} if area and area.notes else {}


def _means_selected(ref) -> bool:
    return isinstance(ref, str) and ref.strip().lower() == SELECTED


def _reference(ref) -> tuple[str | None, str | None]:
    """(the place id a tool was given, None), with SELECTED standing for the place the user selected; or (None, the
    error to give the model). A point id is refused whatever it holds, the selected point's own included: the model is
    never told one, so one that reaches a tool was made up or planted in text the model read."""
    if places.is_point_id(ref):
        return None, POINT_ID_REFUSED
    if not _means_selected(ref):
        return ref, None
    chosen = selected_place()
    return (chosen, None) if chosen else (None, NOTHING_SELECTED)


def _usable(place_id) -> tuple[dict | None, str | None]:
    """(Place, None) when a tool may use the reference: any mapped business by its id, or SELECTED for the place the
    user selected. Otherwise (None, the error to give the model)."""
    ref, error = _reference(place_id)
    if error:
        return None, error
    try:
        return places.resolve(ref), None
    except places.PlaceError:
        return None, NOT_COVERED if places.is_point_id(ref) else UNKNOWN_BUSINESS


def _clean(name) -> str | None:
    return None if name is None else places.clean_name(name)


def _for_model(place: dict) -> dict:
    """A Place as a tool gives it to the model, with every name and type from the map cleaned (its flash_flood is
    {score, class} or null). A point goes as _point_for_model gives it."""
    if place["is_point"]:
        return _point_for_model(place)
    named = {key: {**place[key], "name": _clean(place[key]["name"])} for key in ("road", "shelter") if place.get(key)}
    section = {"section": _clean(place["section"]["name"]) if place["section"] else None} if "section" in place else {}
    return {**place, "name": _clean(place["name"]), "kind": _clean(place["kind"]), **named, **section}


def _point_for_model(place: dict) -> dict:
    """The selected point as a tool gives it to the model: its depths, flash flood potential, its listed area and the
    nearest relief centre, named SELECTED_POINT. Never its id, coordinates or square, which would tell the model where the user is."""
    area, shelter = places.area_of(place), place["shelter"]
    section = place.get("section")
    return {"place": SELECTED_POINT, "is_point": True, "depth_m": dict(place["depth_m"]),
            "flash_flood": place.get("flash_flood"), "area": area.name if area else None, "section": _clean(section["name"]) if section else None,
            "shelter": {"name": _clean(shelter["name"]), "distance_m": shelter["distance_m"]} if shelter else None}


def find_business(name: str) -> list[dict]:
    """Search the mapped businesses in the area this chat is about, by name or type.

    Args:
        name: Part of a business name or type, for example "KFC", "kedai runcit" or "restaurant".

    Returns:
        Up to 8 matching businesses with their id, name, type, the road they are near and, where
        the area is split into sections, the section they are in (the section the user is looking
        at first). Chains have several outlets with the same name: ask which road or section if it
        is not clear. Use the id with flood_check.
    """
    needle = name.strip().lower() if isinstance(name, str) else ""
    hits = [p for p in premises() if needle and (needle in p["name"].lower() or needle in p["kind"].lower())]
    here = (current_section() or {}).get("id")
    hits.sort(key=lambda p: here is None or p.get("section") != here)   # stable: the map's order otherwise
    area = current_area()
    named = area is not None and sections.has_sections(area)
    return [{"id": p["id"], "name": _clean(p["name"]), "type": p["sector"], "kind": _clean(p["kind"]),
             "near": _clean(p["road"]["name"]), **({"section": _section_name(area, p.get("section"))} if named else {})}
            for p in hits[:MAX_MATCHES]]


def flood_check(place_id: str) -> dict:
    """Get the modelled flood depth for a mapped business or for the point the user selected.

    Args:
        place_id: The id of a mapped business, for example "node-11075038761", or "selected" for
            the point the user picked on the map.

    Returns:
        Depth in metres for the 10, 20 and 50 year floods (null means no water in the model).
        Also flash_flood, its flash flood potential: a score from 1 to 10 and a class, how easily
        rain runs off and pools there; it is not a depth or a chance, and null means it was not
        worked out for this spot. For a business, also its nearest road and the depth there. The selected point (is_point
        true) is one 90 m square of the model, not a mapped business; its listed area, if any, is
        given. Also the nearest relief centre (null means this tool has no list for the area) and
        the limits of the data. Returns an error for an unknown id, or for any other point.
    """
    place, error = _usable(place_id)
    if error:
        return {"error": error}
    return {**_for_model(place), "scenarios": SCENARIOS, "limits": LIMITS, **_area_notes(places.area_of(place))}


def area_summary(section: str = "") -> dict:
    """Summarise flood exposure across the mapped businesses in the area this chat is about, or in one
    section of it.

    Args:
        section: For an area split into sections, a section's name or number as the prompt or
            find_business gives it, to summarise that section only. "" for the whole area.

    Returns:
        For each flood size, how many businesses get water, how many stay dry and the names of
        up to 15 of those; for a whole area split into sections, the 10 sections with the most
        businesses with water; for one section, how many of its 90 m squares get water. Where
        flash flood potential is worked out, also the share of a section in each class, its average
        score and our own section score, and for a whole area the sections that rank highest on
        score and on the share of high or extreme flash flood potential. Also the relief centres
        this tool knows of and the limits of the data. Or an error when the user
        picked a point outside the listed areas, or the section is not known.
    """
    area = current_area()
    if area is None:
        return {"error": NO_AREA}
    part, error = _section_asked(area, section)
    if error:
        return {"error": error}
    shown = sections.section_premises(area.id, part["id"]) if part else areas.premises(area.id)
    shelters = [_clean(s["name"]) for s in areas.town(area.id)["shelters"]]
    return {"total_businesses": len(shown), "scenarios": _scenarios(shown), **_section_counts(area, part),
            **_flash_flood(area, part), "shelters": shelters or no_shelters(area), "limits": LIMITS, **_area_notes(area)}


def _section_asked(area: areas.Area, section) -> tuple[Mapping | None, str | None]:
    """(the section a tool was asked about, None), (None, None) for the whole area, or (None, the error)."""
    if not isinstance(section, str) or not section.strip():
        return None, None
    if not sections.has_sections(area):
        return None, NO_SECTIONS
    found = sections.find_section(area, section)
    return (found, None) if found else (None, UNKNOWN_SECTION)


def _scenarios(shown) -> dict:
    found = {}
    for rp, label in SCENARIOS.items():
        dry = [_clean(p["name"]) for p in shown if not p["depth_m"][rp]]
        found[rp] = {"meaning": label, "businesses_with_water": len(shown) - len(dry), "stay_dry": len(dry),
                     "some_that_stay_dry": dry[:MAX_DRY_NAMES]}
    return found


def _section_counts(area: areas.Area, part: Mapping | None) -> dict:
    """For one section: its name and how many of its squares get water; for a whole split area: the sections with the
    most businesses with water at the largest flood size; nothing for an area not split into sections."""
    if part is not None:
        counts = part["counts"]
        return {"section": _clean(part["name"]), "squares": counts["cells"],
                "squares_with_water": dict(counts["wet_cells"])}
    if not sections.has_sections(area):
        return {}
    ranked = sorted(sections.listed(area.id), key=lambda s: -s["counts"]["wet_businesses"][KEY_RP])
    return {"sections": len(ranked), "sections_with_most_businesses_with_water": [
        {"section": _clean(s["name"]), "businesses": s["counts"]["businesses"],
         "businesses_with_water": dict(s["counts"]["wet_businesses"]), "squares": s["counts"]["cells"],
         "squares_with_water": dict(s["counts"]["wet_cells"])} for s in ranked[:MAX_TOP_SECTIONS]]}


def _flash_flood(area: areas.Area, part: Mapping | None) -> dict:
    """The flash flood potential figures of one section, or of the whole area and its top sections; nothing for an area
    without an indexes.json (app/sections.py) and for a section with no land square."""
    doc = sections.index_doc(area.id)
    if doc is None:
        return {}
    if not area.show_index_score:   # the score is held back until its comparison with recorded floods is reviewed
        return _flash_only(doc, area, part)
    if part is not None:
        return _figures_for_model(doc["sections"][part["id"]], "share_of_section", "section_score")
    named = [(_clean(s["name"]), doc["sections"][s["id"]]) for s in sections.listed(area.id)]
    scored = sorted(((name, found["score"]) for name, found in named if found.get("score")),
                    key=lambda item: (-item[1]["value"], item[0]))
    high = sorted(((name, _high_share(found["flash"]["share"])) for name, found in named if found.get("flash")),
                  key=lambda item: (-item[1], item[0]))
    return {**_figures_for_model(doc.get("city") or {}, "share_of_area", "area_score"), "flash_flood_by_section": {
        "highest_score": [{"section": name, "score": score["value"], "class": _words(score["class"])}
                          for name, score in scored[:MAX_TOP_SECTIONS]],
        "most_high_or_extreme": [{"section": name, "share_high_or_extreme": share}
                                 for name, share in high[:MAX_TOP_SECTIONS]],
        "meaning": SCORE_MEANING}}


def _figures_for_model(figures: Mapping, share_key: str, score_key: str) -> dict:
    """`flash_flood_potential` (average score and share by class) and the score (as score_key) of one entry of
    indexes.json."""
    flash, score = figures.get("flash"), figures.get("score")
    return {**({"flash_flood_potential": {"average_score": flash["mean"], share_key: dict(flash["share"])}}
               if flash else {}),
            **({score_key: {"value": score["value"], "class": _words(score["class"]), "meaning": SCORE_MEANING}}
               if score else {})}


def _flash_only(doc: Mapping, area: areas.Area, part: Mapping | None) -> dict:
    """The flash flood potential figures without the held-back score: one section's, or the whole area's and its top
    sections by high or extreme share."""
    if part is not None:
        return _figures_for_model({"flash": doc["sections"][part["id"]].get("flash")}, "share_of_section", "")
    named = [(_clean(s["name"]), doc["sections"][s["id"]]) for s in sections.listed(area.id)]
    high = sorted(((name, _high_share(found["flash"]["share"])) for name, found in named if found.get("flash")),
                  key=lambda item: (-item[1], item[0]))
    return {**_figures_for_model({"flash": (doc.get("city") or {}).get("flash")}, "share_of_area", ""),
            "flash_flood_by_section": {"most_high_or_extreme": [{"section": name, "share_high_or_extreme": share}
                                                                for name, share in high[:MAX_TOP_SECTIONS]]}}


def _words(class_id: str) -> str:
    """A class id as words, such as very_high as "very high"."""
    return class_id.replace("_", " ")


def _high_share(share: Mapping) -> float:
    return round(sum(share.get(name, 0) for name in HIGH_CLASSES), 3)


def flood_history(section: str = "") -> dict:
    """List recorded past floods in the area this chat is about, or in one section of it, from the
    news, official and research sources that were checked.

    Args:
        section: For an area split into sections, a section's name or number as the prompt or
            find_business gives it. "" for the whole area.

    Returns:
        The years the sources cover, the 20 most recent records (date, what happened, depth as
        reported, the sections named, the source and its link) and how many there are in all,
        the runs of years with no record, and a note. No record is not proof of no flood: never
        say a place has never flooded. Or an error.
    """
    area = current_area()
    if area is None:
        return {"error": NO_AREA}
    part, error = _section_asked(area, section)
    if error:
        return {"error": error}
    record = sections.history_for(area, part["id"] if part else None)
    if record is None:
        return {"error": NO_HISTORY}
    floods = sorted(record["floods"], key=lambda flood: -flood["year"])
    return {"scope": _clean(part["name"]) if part else area.name,
            "years_checked": [record["first_year"], record["last_year"]], "records": len(floods),
            "most_recent": [_flood_for_model(area, flood) for flood in floods[:MAX_FLOODS]],
            **({"years_with_no_record": record["gaps"]} if "gaps" in record else {}), "note": NO_RECORD,
            "records_and_model": RECORDS_AND_MODEL}


FLOOD_FIELDS = ("when", "what", "depth", "source", "url", "confidence", "account")


def _flood_for_model(area: areas.Area, flood: Mapping) -> dict:
    found = {key: flood[key] for key in FLOOD_FIELDS if flood.get(key) is not None}
    named = [_section_name(area, section_id) for section_id in flood.get("sections", ())]
    return {**found, **({"sections": [name for name in named if name]} if named else {})}


def damage_estimate(place_id: str, value_at_risk_rm: float, shop_size: str, floor_height_cm: float,
                    daily_takings_rm: float, closed_days: float, raise_cm: float, measure_cost_rm: float) -> dict:
    """Estimate the ringgit loss from flooding for one business, or for the point the user selected.

    Only call this with ringgit amounts the user gave. Never guess them. Pass 0 for anything not given.

    Args:
        place_id: The id of a mapped business, for example "node-11075038761", or "selected" for
            the point the user picked on the map.
        value_at_risk_rm: Ringgit value of stock, equipment and fittings that water could reach.
            0 if the owner does not know it.
        shop_size: "small" or "medium" for a shop, "complex" for a large commercial complex such as a
            mall or hypermarket, as the owner describes it. Only used when value_at_risk_rm is 0: a
            JPS guideline figure for that class stands in. "" (empty text, not 0) if not given.
        floor_height_cm: Height of the shop floor above the street in centimetres. 0 if unknown.
        daily_takings_rm: Income lost per day the shop is closed, in ringgit. 0 if not given: 30% of
            the direct damage is then used for cleaning up and lost trade.
        closed_days: Days the owner expects to stay closed after a flood. 0 if not given.
        raise_cm: To test a measure, how many centimetres the stock would be raised (shelving,
            platform). Needs value_at_risk_rm, and assumes everything in it is raised. 0 for no measure.
        measure_cost_rm: What that measure costs in ringgit. 0 for no measure.

    Returns:
        Loss in each of the 10, 20 and 50 year floods, the average loss per year, the loss over
        ten years, whether the measure pays for itself, the basis used for the direct and indirect
        figures, the method and its limits. Or an error.
    """
    place, error = _usable(place_id)
    if error:
        return {"error": error}
    found = estimate_for(place, value_at_risk_rm, shop_size, floor_height_cm, daily_takings_rm, closed_days,
                         raise_cm, measure_cost_rm)
    if "error" in found or not place["is_point"]:
        return found
    return {**found, "place": SELECTED_POINT}   # the page's form gets the point's id; the model never does


def estimate_for(place: dict, value_at_risk_rm: float, shop_size: str = "", floor_height_cm: float = 0,
                 daily_takings_rm: float = 0, closed_days: float = 0, raise_cm: float = 0,
                 measure_cost_rm: float = 0) -> dict:
    """damage_estimate for a Place already found (the form's endpoint finds its own): the owner's figures are
    checked, then costs.estimate does the sums. An error, worded for the model, when a figure cannot be used."""
    given = {"value_at_risk_rm": value_at_risk_rm, "floor_height_cm": floor_height_cm,
             "daily_takings_rm": daily_takings_rm, "closed_days": closed_days,
             "raise_cm": raise_cm, "measure_cost_rm": measure_cost_rm}
    size = shop_size.strip().lower() if isinstance(shop_size, str) else None
    error = _figures_error(given, size)
    if error:
        return {"error": error}
    if value_at_risk_rm:
        size = ""   # the owner's own value wins, so do not echo a size that was not used
    return {"place": place["id"], "business": _clean(place["name"]), "inputs": {**given, "shop_size": size},
            **costs.estimate(place["depth_m"], shop_size=size, **given),
            "method": costs.METHOD, "limits": f"{costs.LIMITS} {LIMITS}"}


def _figures_error(given: dict, size: str | None) -> str | None:
    """Why the owner's figures cannot be used, worded for the model; None when they can."""
    if size not in ("", *costs.JPS_POTENTIAL_DAMAGE_RM_2001):
        return ('shop_size must be "small", "medium", "complex" (a mall or hypermarket) or "". '
                "Ask the owner which one fits.")
    for name, value in given.items():
        # the range test also rejects NaN and infinity, and unlike isfinite() cannot overflow on a huge int
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not (is_number and 0 <= value <= ESTIMATE_MAX[name]):
            return f"{name} must be a number from 0 to {ESTIMATE_MAX[name]}."
    value, raise_cm, measure = given["value_at_risk_rm"], given["raise_cm"], given["measure_cost_rm"]
    if 0 < value < 1 or 0 < measure < 1:
        return "Ringgit amounts must be 0 or at least 1."
    if (raise_cm > 0) != (measure > 0):
        return "To test a measure give both raise_cm and measure_cost_rm, or 0 for both."
    if raise_cm > 0 and not value:
        return ("A measure can only be priced from the owner's own value of stock and equipment. "
                "The shop-size figure does not change with depth. Ask for that value.")
    if not (value or size or given["daily_takings_rm"] * given["closed_days"]):
        return "Nothing to estimate from. Ask for the value of stock and equipment, or the shop size."
    return None


def start_question(area: areas.Area | None = None, place: dict | None = None,
                   section: Mapping | None = None) -> contextvars.Token:
    """Open one chat question's scope and its allowance of Google lookups. With a selected place (a Place from
    places.resolve) the area and section are the place's own: the area holding the business or point, or None for a
    point outside the listed areas. Without one, the area and section given, or the default area. Pass the token to
    end_question."""
    if place:
        scope_area = places.area_of(place)
        section = sections.get(scope_area, (place.get("section") or {}).get("id")) if scope_area else None
    else:
        scope_area = area or areas.default()
    return _scope.set(QuestionScope(scope_area, place["id"] if place else None, MAX_MAPS_LOOKUPS, section))


def end_question(token: contextvars.Token) -> None:
    _scope.reset(token)


def _may_look_up() -> bool:
    scope = _scope.get()
    if scope is None:   # called outside a chat question, e.g. by a test or a script
        return True
    if scope.maps_left <= 0:
        return False
    # The tools run one after another in the question's own context, so the next tool sees the new scope. Tools run
    # on other threads would each get a copy of the context and the cap would not hold; a test guards against that.
    _scope.set(replace(scope, maps_left=scope.maps_left - 1))
    return True


def _rain_at() -> tuple[float, float]:
    """Where to ask for rain: the middle of the question's section, else of its area, or for a point outside the listed
    areas its square's centre rounded to WEATHER_DECIMALS, so Google gets no more than about a kilometre of where the
    user is."""
    area, section = current_area(), current_section()
    if section is not None:
        return sections.centre(section)
    if area is not None:
        return area.centre()
    lat, lon = places.parse_point_id(selected_place() or "")
    return round(lat, WEATHER_DECIMALS), round(lon, WEATHER_DECIMALS)


def rain_forecast() -> dict:
    """Rain expected over the next 12 hours where this chat is about, from Google Weather.

    Returns:
        Total rain in millimetres, the wettest hour, the highest chance of rain and the current
        condition, or an error. This is a weather forecast, not a flood warning: heavy rain raises
        the chance of local flooding but the tool cannot say whether a shop will flood.
    """
    if not _may_look_up():
        return {"error": MAPS_SPENT}
    try:
        outlook = googlemaps.rain_outlook(*_rain_at(), RAIN_HOURS)
    except googlemaps.NotConfigured:
        return {"error": MAPS_OFF}
    except googlemaps.UpstreamError:
        return {"error": MAPS_DOWN}
    return {**{key: outlook[key] for key in RAIN_FIELDS if key in outlook},
            "note": "Weather forecast only. For flood warnings check JPS Public Infobanjir."}


def business_status(business_id: str) -> dict:
    """Check on Google Maps whether a mapped business is listed as open, closed for now or closed for good.

    Args:
        business_id: The business id, for example "node-11075038761".

    Returns:
        found: whether Google Maps lists a business with that name within 150 m of the mapped point;
        if so its status, its name on Google Maps and a link. Or an error. A listing can be out of
        date, so say "Google Maps lists it as ...".
    """
    ref, error = _reference(business_id)
    if error == POINT_ID_REFUSED or places.is_point_id(ref):   # a point id, or "selected" for a point
        return {"error": NOT_A_BUSINESS}
    p = None if error else get(ref)
    if p is None:
        return {"error": error or UNKNOWN_BUSINESS}
    if not _may_look_up():
        return {"error": MAPS_SPENT}
    try:
        listing = googlemaps.place_status(p["name"], p["lat"], p["lon"])
    except googlemaps.NotConfigured:
        return {"error": MAPS_OFF}
    except googlemaps.UpstreamError:
        return {"error": MAPS_DOWN}
    # a listing's name is set by whoever owns the listing: cleaned like a name from the map
    shown = {**listing, "name": places.clean_name(listing.get("name"))} if listing else {}
    return {"business": _clean(p["name"]), "found": listing is not None, **shown}


TOOLS = [find_business, flood_check, area_summary, flood_history, damage_estimate, rain_forecast, business_status]
