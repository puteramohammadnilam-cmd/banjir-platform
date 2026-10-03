"""Plan card G1: what a photo of the stock means in each flood size. Pure sums, no AI: Gemini only lists the items and
guesses their value (ai.read_stock_photo); which of them sit under the modelled water is worked out here.

An item is under water in a flood when the modelled water above the floor (street depth minus floor height) rises
above the lowest part of the item. Water that only reaches its base does not count it.
"""
from __future__ import annotations

from .floodtools import ESTIMATE_MAX

ROUND_M = 2


def _water_above_floor(depth: float | None, floor_cm: float) -> float:
    return round(max(0.0, (depth or 0.0) - floor_cm / 100), ROUND_M)


def _values(items: list[dict], picked: list[int]) -> dict:
    return {"value_rm_low": sum(items[i]["value_rm_low"] for i in picked),
            "value_rm_high": sum(items[i]["value_rm_high"] for i in picked)}


def summarise(items: list[dict], depth_m: dict, floor_cm: float) -> dict:
    """{total, suggested_value_rm, per_flood}: the low and high value of every item, the midpoint of that total (what
    the cost form may take as the value of stock and equipment), and for each flood size the water above the floor, the
    indexes of the items under it and their value."""
    every = list(range(len(items)))
    total = _values(items, every)
    per_flood = {}
    for rp, depth in depth_m.items():
        water = _water_above_floor(depth, floor_cm)
        under = [i for i in every if water > items[i]["lowest_cm"] / 100]
        per_flood[rp] = {"water_above_floor_m": water, "under_water": under, **_values(items, under)}
    middle = round((total["value_rm_low"] + total["value_rm_high"]) / 2)
    return {"total": total, "suggested_value_rm": min(middle, ESTIMATE_MAX["value_at_risk_rm"]),   # the form's limit
            "per_flood": per_flood}
