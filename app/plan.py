"""Plan card G2: the facts a flood plan is written from, the contacts printed with it, and the check on what Gemini
wrote. The facts and the contacts are ours: Gemini (ai.write_plan) only turns the facts into steps.

A point is named only as floodtools.SELECTED_POINT: no id and no coordinates go to the model. A business name from the
map is cleaned (places.clean_name) and the facts go to the model as data, not as instructions.
"""
from __future__ import annotations

import re

from . import areas, floodtools, places

SCENARIOS = ("10", "20", "50")
CHANCE_YEARS = 10
INFOBANJIR = "https://publicinfobanjir.water.gov.my/"
MAX_STEP_CHARS = 200
STEP_LIMITS = {"before": 6, "warning": 5, "during": 4, "after": 5}
TITLES = {"ms": "Pelan banjir", "en": "Flood plan"}
# What only contacts() may give: a link, a web or e-mail address, or a Malaysian phone number (0 or +60 first, or a
# 1-300 or 1-800 line). Seven digits in a row without those (such as "65 40 180") are not taken for a phone number.
CONTACT = re.compile(
    r"https?://|www\.|@|\b[\w-]+(?:\.[\w-]+)*\.(?:my|com|org|net|gov|edu|io|me|info|asia)\b"
    r"|(?:\+?60|\b0)\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b|\b1[\s-]?[38]00\b", re.IGNORECASE)
# What the plan may never promise (it says what the model shows): safe from floods, will or will not flood
PROMISE = re.compile(r"\b(?:is|are|stays?|kept)\s+safe\b|\bsafe from\b|\bwill (?:not )?flood\b|\bwon't flood\b"
                     r"|\b(?:akan|tidak akan|takkan) banjir\b|\bselamat daripada banjir\b", re.IGNORECASE)
# Figures the model may only repeat from the facts: ringgit, percentages, years and metres with decimals
MONEY = re.compile(r"\bRM\s?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
METRES = re.compile(r"\b(\d+\.\d+)\s?m\b")


def _chance_pct(rp: str) -> int:
    return round(100 * (1 - (1 - 1 / int(rp)) ** CHANCE_YEARS))


def _flood(rp: str, depth: float | None, floor_cm: float, estimate: dict | None) -> dict:
    flood = {"size": f"1 in {rp} years", "chance_in_10_years_pct": _chance_pct(rp), "street_depth_m": depth,
             "water_above_floor_m": round(max(0.0, (depth or 0.0) - floor_cm / 100), 2)}
    if estimate:
        flood["loss_rm"] = estimate["per_flood"][rp]["total_rm"]
    return flood


def _estimate(found: dict | None) -> dict | None:
    if not found:
        return None
    return {"value_of_stock_and_equipment_rm": found["inputs"]["value_at_risk_rm"] or None,
            "shop_size": found["inputs"]["shop_size"] or None,
            "expected_yearly_loss_rm": found["expected_yearly_loss_rm"],
            "basis": found["basis"]}


def facts(place: dict, area: areas.Area | None, floor_cm: float = 0, estimate: dict | None = None) -> dict:
    """What the plan may say: the place, its area, each flood size's chance, depth and water above the floor (and loss,
    with an estimate from floodtools.estimate_for), and the nearest relief centre. Depths are null where the model has
    no water."""
    shelter = place.get("shelter")
    return {
        "place": floodtools.SELECTED_POINT if place["is_point"] else places.clean_name(place["name"]),
        "kind": None if place["is_point"] else places.clean_name(place.get("kind")),
        "area": area.name if area else None,
        "floods": [_flood(rp, place["depth_m"][rp], floor_cm, estimate) for rp in SCENARIOS],
        "floor_height_cm": floor_cm,
        "relief_centre": {"name": places.clean_name(shelter["name"]), "distance_m": shelter["distance_m"]} if shelter else None,
        "estimate": _estimate(estimate),
        "model_note": "Depths are from a global river flood model in 90 m squares, not an official map or a forecast.",
    }


CONTACT_WORDS = {
    "en": ("Emergency (police, fire, ambulance)", "JPS Public Infobanjir: river levels and flood warnings",
           "your local council, for drains, clean-up and help after a flood"),
    "ms": ("Kecemasan (polis, bomba, ambulans)", "JPS Public Infobanjir: paras sungai dan amaran banjir",
           "majlis tempatan anda, untuk longkang, pembersihan dan bantuan selepas banjir"),
}


def contacts(area: areas.Area | None, language: str = "en") -> list[dict]:
    """Who to call or check, printed with every plan, in the plan's language. Ours, never the model's."""
    emergency, infobanjir, council = CONTACT_WORDS.get(language, CONTACT_WORDS["en"])
    found = [{"name": emergency, "how": "999"}, {"name": infobanjir, "how": INFOBANJIR}]
    if area:
        found.append({"name": area.council, "how": council})
    return found


def _numbers(value) -> set[float]:
    """Every number in the facts."""
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return {number for item in items for number in _numbers(item)}


def _invents(text: str, known: set[float]) -> bool:
    """Whether the text gives a ringgit amount, a percentage, a year or a depth in metres that the facts do not hold."""
    near = lambda value: any(abs(value - k) < 0.051 for k in known)   # noqa: E731 (a depth rounded to 0.1 m is fine)
    money = [float(m.replace(",", "")) for m in MONEY.findall(text)]
    return (any(value not in known for value in money)
            or any(float(p) not in known for p in PERCENT.findall(text))
            or bool(YEAR.search(text))
            or any(not near(float(m)) for m in METRES.findall(text)))


def _allowed(text: str, known: set[float]) -> bool:
    return not (CONTACT.search(text) or PROMISE.search(text) or _invents(text, known))


def clean(written, facts: dict, language: str) -> dict:
    """The plan as the page gets it. A step with a contact (only contacts() may give those), a promise, or a figure
    that is not in the facts is dropped; a title like that becomes a plain one and a summary like that is left out.
    Lists are cut to STEP_LIMITS and steps to MAX_STEP_CHARS, so a long answer is trimmed rather than refused."""
    known = _numbers(facts)
    plan = written.model_dump()
    for part, limit in STEP_LIMITS.items():
        steps = [step.strip() for step in plan[part] if step.strip() and _allowed(step, known)]
        plan[part] = [step if len(step) <= MAX_STEP_CHARS else step[:MAX_STEP_CHARS - 1] + "…" for step in steps[:limit]]
    if not _allowed(plan["title"], known) or not plan["title"].strip():
        plan["title"] = TITLES[language]
    plan["title"] = plan["title"][:80]
    if not _allowed(plan["summary"], known):
        plan["summary"] = ""
    plan["summary"] = plan["summary"][:400]
    return plan
