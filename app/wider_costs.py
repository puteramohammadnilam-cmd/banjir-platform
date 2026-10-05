"""Losses in one flood beyond the shop's stock and lost sales: its built-in works, the vehicles parked at it, and the
pay its workers lose while it is shut. Pure arithmetic, no I/O. Every figure and its source is in
05_Raw_Data_Sources/shah_alam/wider_damage/FINDINGS.md.

  built-in works   owner's value x damage share(water above floor)   JRC 2017 Asia commerce curve (as costs.py)
                   only with the owner's own value: the JPS shop-size figure already counts the building
  vehicles         their value x vehicle share(water at the street)  USACE EGM 09-04 (2009), sedan curve
  workers' pay     unpaid workers x minimum day wage x days closed   Minimum Wages Order 2024, P.U. (A) 376
"""
from __future__ import annotations

from bisect import bisect_right

from . import costs

# USACE Economic Guidance Memorandum 09-04 (22 June 2009), Table Three: sedan damage as a share of its value against
# water above the ground where it is parked (feet in the table, metres here). Public domain (US federal work).
# ponytail: a US curve from 640 cars in 10 floods; there is none for Malaysia, and none for motorcycles, which get the
# same curve (our assumption, said on the page). Swap these tuples when a Malaysian vehicle curve is published.
VEHICLE_DEPTH_M = (0, 0.15, 0.30, 0.61, 0.91, 1.22, 1.52, 1.83, 2.13)
VEHICLE_SHARE = (0, 0.076, 0.28, 0.462, 0.622, 0.76, 0.876, 0.97, 1.0)

# Minimum Wages Order 2024, P.U. (A) 376: RM1,700 a month from 1 Feb 2025 (1 Aug 2025 for employers of fewer than
# five), RM65.38 a day for a six-day week.
MIN_WAGE_DAY_RM = 65.38

BUILT_IN_BASIS = ("your value of built-in works (tiles, ceiling, wiring, counters, shutters) x the same damage "
                  "share as your stock")
VEHICLE_BASIS = ("the value of vehicles parked at the shop x the share of a car's value lost at that depth of water "
                 "in the street (US Army Corps of Engineers, 2009, from 640 cars in 10 US floods; motorcycles use "
                 "the same curve, our assumption). Counted as if they stay parked; moving them in time saves them")
WAGE_BASIS = (f"workers not paid while the shop is shut x RM{MIN_WAGE_DAY_RM} a day (the minimum wage, 6-day week) "
              "x days closed, in every flood that puts water in the street")


def vehicle_share(street_depth_m: float | None) -> float:
    """Share of a vehicle's value lost, 0 to 1, for a depth of water at the street."""
    depth = street_depth_m or 0.0
    if depth <= 0:
        return 0.0
    if depth >= VEHICLE_DEPTH_M[-1]:
        return 1.0
    hi = bisect_right(VEHICLE_DEPTH_M, depth)
    d0, d1, s0, s1 = VEHICLE_DEPTH_M[hi - 1], VEHICLE_DEPTH_M[hi], VEHICLE_SHARE[hi - 1], VEHICLE_SHARE[hi]
    return s0 + (s1 - s0) * (depth - d0) / (d1 - d0)


def per_flood(street_depth_m: float | None, water_above_floor_m: float, *, built_in_rm: float = 0,
              vehicles_rm: float = 0, unpaid_workers: float = 0, closed_days: float = 0) -> dict:
    """The three losses in one flood, in whole ringgit. Built-in works are counted on the floor as it is: raising
    stock cannot raise them."""
    is_wet = bool(street_depth_m and street_depth_m > 0)
    return {
        "built_in_rm": round(built_in_rm * costs.damage_share(water_above_floor_m)),
        "vehicles_rm": round(vehicles_rm * vehicle_share(street_depth_m)),
        "wages_rm": round(unpaid_workers * MIN_WAGE_DAY_RM * closed_days) if is_wet else 0,
    }


def basis(built_in_rm: float, vehicles_rm: float, unpaid_workers: float) -> dict:
    """How each wider loss was worked out, for the ones the owner gave."""
    given = {"built_in": (built_in_rm, BUILT_IN_BASIS), "vehicles": (vehicles_rm, VEHICLE_BASIS),
             "wages": (unpaid_workers, WAGE_BASIS)}
    return {key: text for key, (amount, text) in given.items() if amount > 0}
