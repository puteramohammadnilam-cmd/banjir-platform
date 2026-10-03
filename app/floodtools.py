"""Read-only lookups over the built data. These are also the tools the AI model may call."""
from __future__ import annotations

import contextvars
import json
from functools import lru_cache
from pathlib import Path

from . import costs, googlemaps

DATA = Path(__file__).parent / "data"

SCENARIOS = {"10": "a flood expected once in 10 years", "100": "a flood expected once in 100 years",
             "500": "a flood expected once in 500 years"}
LIMITS = (
    "Depths come from a global computer model (European Commission JRC, 90 m squares). "
    "It is not an official Malaysian flood map and not a record of real floods. "
    "It ignores local flood walls, pumps and floor heights. Several shops can share one square. "
    "Businesses are points on a public map and have not been checked on the ground."
)
NO_SHELTERS = ("This tool has no relief centre list for this area yet. "
               "Ask the authorities: JPS Public Infobanjir, the local council (MBSA) or 999.")
MAX_MATCHES = 8
RAIN_HOURS = 12
MAPS_OFF = "Google Maps is not set up in this build, so this cannot be checked."
MAPS_DOWN = "Google Maps did not answer just now. Try again later."
MAX_MAPS_LOOKUPS = 3   # per chat question, so a model told to check every shop cannot run up the bill
MAPS_SPENT = "Enough Google lookups for one question. Answer with what you have."
_maps_left: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar("maps_left", default=None)
ESTIMATE_MAX = {"value_at_risk_rm": 50_000_000, "floor_height_cm": 300, "daily_takings_rm": 1_000_000,
                "closed_days": 365, "raise_cm": 300, "measure_cost_rm": 50_000_000}


@lru_cache(maxsize=1)
def premises() -> tuple[dict, ...]:
    return tuple(json.loads((DATA / "premises.json").read_text()))


@lru_cache(maxsize=1)
def town() -> dict:
    return json.loads((DATA / "town.json").read_text())


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {p["id"]: p for p in premises()}


def get(business_id: str) -> dict | None:
    return _by_id().get(business_id)


def find_business(name: str) -> list[dict]:
    """Search the mapped businesses around Taman Sri Muda, Shah Alam, by name or type.

    Args:
        name: Part of a business name or type, for example "KFC", "kedai runcit" or "restaurant".

    Returns:
        Up to 8 matching businesses with their id, name, type and the road they are near. Chains
        have several outlets with the same name: ask which road if it is not clear. Use the id
        with flood_check.
    """
    needle = name.strip().lower()
    hits = [p for p in premises() if needle and (needle in p["name"].lower() or needle in p["kind"].lower())]
    return [{"id": p["id"], "name": p["name"], "type": p["sector"], "kind": p["kind"], "near": p["road"]["name"]}
            for p in hits[:MAX_MATCHES]]


def flood_check(business_id: str) -> dict:
    """Get the modelled flood depth and nearest road for one business.

    Args:
        business_id: The business id, for example "node-11075038761".

    Returns:
        Depth in metres at the business and at its nearest road for the 10, 100 and 500 year
        floods (null means no water in the model), the nearest relief centre (null means this
        tool has no list for the area), and the limits of the data. Returns an error if the id
        is unknown.
    """
    p = get(business_id)
    if p is None:
        return {"error": f"No business with id {business_id!r}. Call find_business first."}
    return {**p, "scenarios": SCENARIOS, "limits": LIMITS}


def town_summary() -> dict:
    """Summarise flood exposure across all mapped businesses around Taman Sri Muda, Shah Alam.

    Returns:
        For each flood size, how many businesses get water and which stay dry, plus the
        relief centres this tool knows of and the limits of the data.
    """
    out: dict = {"total_businesses": len(premises()), "scenarios": {}}
    for rp, label in SCENARIOS.items():
        wet = [p for p in premises() if p["depth_m"][rp]]
        dry = [p["name"] for p in premises() if not p["depth_m"][rp]]
        out["scenarios"][rp] = {"meaning": label, "businesses_with_water": len(wet), "stay_dry": dry}
    out["shelters"] = [s["name"] for s in town()["shelters"]] or NO_SHELTERS
    out["limits"] = LIMITS
    return out


def damage_estimate(business_id: str, value_at_risk_rm: float, shop_size: str, floor_height_cm: float,
                    daily_takings_rm: float, closed_days: float, raise_cm: float, measure_cost_rm: float) -> dict:
    """Estimate the ringgit loss from flooding for one business.

    Only call this with ringgit amounts the user gave. Never guess them. Pass 0 for anything not given.

    Args:
        business_id: The business id, for example "node-11075038761".
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
        Loss in each of the 10, 100 and 500 year floods, the average loss per year, the loss over
        ten years, whether the measure pays for itself, the basis used for the direct and indirect
        figures, the method and its limits. Or an error.
    """
    p = get(business_id) if isinstance(business_id, str) else None
    if p is None:
        return {"error": "No business with that id. Call find_business first."}
    given = {"value_at_risk_rm": value_at_risk_rm, "floor_height_cm": floor_height_cm,
             "daily_takings_rm": daily_takings_rm, "closed_days": closed_days,
             "raise_cm": raise_cm, "measure_cost_rm": measure_cost_rm}
    size = shop_size.strip().lower() if isinstance(shop_size, str) else None
    if size not in ("", *costs.JPS_POTENTIAL_DAMAGE_RM_2001):
        return {"error": 'shop_size must be "small", "medium", "complex" (a mall or hypermarket) or "". '
                         "Ask the owner which one fits."}
    for name, value in given.items():
        # the range test also rejects NaN and infinity, and unlike isfinite() cannot overflow on a huge int
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not (is_number and 0 <= value <= ESTIMATE_MAX[name]):
            return {"error": f"{name} must be a number from 0 to {ESTIMATE_MAX[name]}."}
    if 0 < value_at_risk_rm < 1 or 0 < measure_cost_rm < 1:
        return {"error": "Ringgit amounts must be 0 or at least 1."}
    if (raise_cm > 0) != (measure_cost_rm > 0):
        return {"error": "To test a measure give both raise_cm and measure_cost_rm, or 0 for both."}
    if raise_cm > 0 and not value_at_risk_rm:
        return {"error": "A measure can only be priced from the owner's own value of stock and equipment. "
                         "The shop-size figure does not change with depth. Ask for that value."}
    if not (value_at_risk_rm or size or daily_takings_rm * closed_days):
        return {"error": "Nothing to estimate from. Ask for the value of stock and equipment, or the shop size."}
    if value_at_risk_rm:
        size = ""   # the owner's own value wins, so do not echo a size that was not used
    return {"business": p["name"], "inputs": {**given, "shop_size": size},
            **costs.estimate(p["depth_m"], shop_size=size, **given),
            "method": costs.METHOD, "limits": f"{costs.LIMITS} {LIMITS}"}


def start_question() -> contextvars.Token:
    """Give one chat question its allowance of Google lookups. Pass the token to end_question."""
    return _maps_left.set([MAX_MAPS_LOOKUPS])


def end_question(token: contextvars.Token) -> None:
    _maps_left.reset(token)


def _may_look_up() -> bool:
    left = _maps_left.get()
    if left is None:   # called outside a chat question, e.g. by a test or a script
        return True
    if left[0] <= 0:
        return False
    left[0] -= 1
    return True


def area_centre() -> tuple[float, float]:
    west, south, east, north = town()["view"]
    return (south + north) / 2, (west + east) / 2


def rain_forecast() -> dict:
    """Rain expected over the next 12 hours around Taman Sri Muda, from Google Weather.

    Returns:
        Total rain in millimetres, the wettest hour, the highest chance of rain and the current
        condition, or an error. This is a weather forecast, not a flood warning: heavy rain raises
        the chance of local flooding but the tool cannot say whether a shop will flood.
    """
    if not _may_look_up():
        return {"error": MAPS_SPENT}
    try:
        return {**googlemaps.rain_outlook(*area_centre(), RAIN_HOURS),
                "note": "Weather forecast only. For flood warnings check JPS Public Infobanjir."}
    except googlemaps.NotConfigured:
        return {"error": MAPS_OFF}
    except googlemaps.UpstreamError:
        return {"error": MAPS_DOWN}


def business_status(business_id: str) -> dict:
    """Check on Google Maps whether a mapped business is listed as open, closed for now or closed for good.

    Args:
        business_id: The business id, for example "node-11075038761".

    Returns:
        found: whether Google Maps lists a business with that name within 150 m of the mapped point;
        if so its status, its name on Google Maps and a link. Or an error. A listing can be out of
        date, so say "Google Maps lists it as ...".
    """
    p = get(business_id) if isinstance(business_id, str) else None
    if p is None:
        return {"error": "No business with that id. Call find_business first."}
    if not _may_look_up():
        return {"error": MAPS_SPENT}
    try:
        listing = googlemaps.place_status(p["name"], p["lat"], p["lon"])
    except googlemaps.NotConfigured:
        return {"error": MAPS_OFF}
    except googlemaps.UpstreamError:
        return {"error": MAPS_DOWN}
    return {"business": p["name"], "found": listing is not None, **(listing or {})}


TOOLS = [find_business, flood_check, town_summary, damage_estimate, rain_forecast, business_status]
