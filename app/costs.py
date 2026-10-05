"""Turn modelled flood depths into a rough ringgit loss for one shop. Pure arithmetic, no I/O.

The chain follows published methods. Malaysian sources are used wherever one exists:
  direct damage in one flood
      owner knows their value   value x damage share(depth)    ASEAN Flood Risk Assessment and Mapping Guideline, ch. 6
      owner does not            flat figure by shop size x 0.8  JPS / KTA Tenaga 2003, Rapid Assessment Method
                                (cannot price a measure)
  indirect loss in one flood
      owner gives closure       takings per day x days closed   Fadel et al. 2018, Table 2 (non-productive days)
      otherwise                 30% of direct damage            JPS / KTA Tenaga 2003, section 3.5.1
  yearly loss           area under loss against yearly chance   Fadel et al. 2018, eq. 7 (JPS 2003 calls it AAD)
  loss over n years     discounted sum                          Zuriyati Yusof et al. 2024 (JPS), eq. 2 and 3
  is a measure worth it benefit / cost > 1                      Zuriyati Yusof et al. 2024 (JPS), eq. 1

JPS / KTA Tenaga 2003 = "Flood Damage Assessment of 26 April 2001 Flooding Affecting the Klang Valley and the
Generalised Procedures and Guidelines for Assessment of Flood Damages", Final Report Vol. 2, October 2003.
"""
from __future__ import annotations

from bisect import bisect_right

# Huizinga, de Moel and Szewczyk (2017), JRC, Table 3-6: average damage function for Asia, commerce.
# ponytail: an Asia average, not Malaysian. Swap these two tuples when a Malaysian depth-damage curve is published.
CURVE_DEPTH_M = (0, 0.5, 1, 1.5, 2, 3, 4, 5, 6)
CURVE_SHARE = (0, 0.38, 0.54, 0.66, 0.76, 0.88, 0.94, 0.98, 1.0)

# JPS / KTA Tenaga 2003, section 4.1: potential damage per flooded commercial property, "established" in the
# consultant's study of the 2001 Klang Valley flood. Its classes are Small, Medium and "Large (Complexes)";
# small and medium are not defined. One flat figure per property, whatever the depth, meant for counting
# many properties in a study area. Using it for a single shop is our extrapolation.
JPS_POTENTIAL_DAMAGE_RM_2001 = {"small": 12_000, "medium": 24_000, "complex": 160_000}
SIZE_LABEL = {"small": "a small shop", "medium": "a medium shop", "complex": "a large commercial complex"}
# Actual damage as a share of potential ("damage reduction ratio"). The guideline's worked examples use 0.8.
# It says the ratio may be 0.5 for a community experienced with floods and 0.9 for an inexperienced one, and
# that longer warning leaves more time to move goods.
JPS_ACTUAL_SHARE = 0.8
# Indirect damage as a share of direct: 30% "will be adequate" in the majority of cases, 20% where population
# is low, 45% for a major city centre. (The urban worked example uses 40% for indirect plus intangible.)
JPS_INDIRECT_SHARE = 0.30
# World Bank, consumer price index for Malaysia (FP.CPI.TOTL, 2010 = 100), CC BY 4.0: 2001 = 81.66, 2025 = 134.60.
# ponytail: general consumer prices, not shop stock or fit-out, and the guideline does not state its price
# year. 2001 is the flood year; the report is dated 2003, which would make the factor 1.60, not 1.65.
PRICE_YEAR = 2025
PRICE_FACTOR = 134.60 / 81.66

DISCOUNT_RATE = 0.04   # used for flood mitigation cost-benefit analysis in Malaysia (Zuriyati Yusof et al. 2024, JPS)
YEARS = 10             # our own choice: roughly how long shelving or a door barrier lasts
WORTH_IT_ABOVE = 1.0   # benefit-cost ratio

DIRECT_FROM_OWNER = "your own value at risk x the Asia-wide damage share for that depth of water (JRC 2017)"
DIRECT_FROM_SIZE = (
    "the JPS guideline figure for {label} from its study of the 2001 Klang Valley flood (RM {unit:,}), raised "
    f"by {PRICE_FACTOR:.2f} for prices to {PRICE_YEAR} and x {JPS_ACTUAL_SHARE} for actual against potential "
    "damage (the guideline gives 0.5 to 0.9 depending on flood experience and warning time). It is the same "
    "in every flood that reaches the floor"
)
DIRECT_NONE = "none counted: no value at risk and no shop size was given"
INDIRECT_FROM_OWNER = "your daily takings x days closed, in every flood that puts water in the shop's map square"
INDIRECT_DEFAULT = ("30% of the direct damage, the JPS guideline's usual allowance for indirect damage such as "
                    "cleaning up and lost income (it gives 20% to 45%)")

METHOD = (
    "Loss in each flood = direct damage + indirect loss, plus any renovation and built-ins, vehicles parked at the "
    "shop and workers' unpaid pay the owner gave; see 'basis' for how each was worked out here. "
    "Yearly loss = area under the loss against yearly-chance curve for the 1 in 10, 20 and 50 year floods, "
    "with every flood rarer than 1 in 50 years counted at the 1 in 50 loss. "
    "Ten-year loss = yearly loss discounted at 4% a year, the rate used for flood mitigation cost-benefit "
    "studies in Malaysia. A measure that raises stock can only be priced from the owner's own value. It is "
    "credited only with the direct damage it avoids, and is worth it when that saving over ten years is more "
    "than it costs."
)
LIMITS = (
    "A rough estimate, not a valuation and not an insurance figure. With the owner's own value, the damage "
    "share is an Asia-wide average for shops (European Commission JRC, 2017), not measured in Malaysia. With "
    "a shop size instead, the figure is from a JPS guideline on the 2001 Klang Valley flood: it is over 20 "
    "years old, is adjusted by general consumer prices only, does not change with depth, and is an average "
    "meant for counting many properties, so for one shop it is only indicative. The guideline does not say "
    "what counts as small or medium, and calls its own method a first approximation that is not a basis for "
    "cost-benefit analysis for funding. The yearly figure is a floor at both ends: floods that come more "
    "often than once in 10 years are not in the model, so a shop that floods often will lose more than "
    "shown, and floods bigger than 1 in 50 years are counted as if they cost the same as the 1 in 50, though "
    "they cost more. A floor height of 0 means the floor is taken as level with the street. Daily takings are "
    "counted in full, not just the profit. A measure is "
    "assumed to lift everything counted in the value at risk; fittings that cannot be raised make the real "
    "saving smaller."
)


def damage_share(water_above_floor_m: float) -> float:
    """Share of the value at risk that is lost, 0 to 1, for a given depth of water above the floor."""
    if water_above_floor_m <= 0:
        return 0.0
    if water_above_floor_m >= CURVE_DEPTH_M[-1]:
        return 1.0
    hi = bisect_right(CURVE_DEPTH_M, water_above_floor_m)
    d0, d1, s0, s1 = CURVE_DEPTH_M[hi - 1], CURVE_DEPTH_M[hi], CURVE_SHARE[hi - 1], CURVE_SHARE[hi]
    return s0 + (s1 - s0) * (water_above_floor_m - d0) / (d1 - d0)


def expected_yearly(loss_by_return_period: dict[str, float]) -> float:
    """Average loss per year: trapezoid area under loss against yearly chance (1 / return period), plus the rarest
    flood's chance times its loss for every flood rarer still. For 1 in 10, 20 and 50 years that is
    0.035 x L50 + 0.04 x L20 + 0.025 x L10. A floor at both ends: see LIMITS."""
    # ponytail: no loss is counted for floods more frequent than the smallest return period given, and floods rarer
    # than the largest are counted at its loss. Add 1 in 2 and 1 in 5 year depth layers to close the first gap.
    points = sorted((1 / float(rp), loss) for rp, loss in loss_by_return_period.items())
    rarest_chance, rarest_loss = points[0]
    area = rarest_chance * rarest_loss
    for (p0, l0), (p1, l1) in zip(points, points[1:]):
        area += (p1 - p0) * (l0 + l1) / 2
    return area


def present_value(yearly: float, years: int = YEARS, rate: float = DISCOUNT_RATE) -> float:
    """What a loss repeated every year for `years` years is worth today."""
    return sum(yearly / (1 + rate) ** t for t in range(1, years + 1))


def _direct(depth_m: dict[str, float | None], value_rm: float, shop_size: str, floor_m: float) -> dict:
    """Direct damage per flood: the owner's value on the depth curve, else the JPS flat figure for the size."""
    flat = JPS_POTENTIAL_DAMAGE_RM_2001.get(shop_size, 0) * PRICE_FACTOR * JPS_ACTUAL_SHARE
    floods = {}
    for rp, depth in depth_m.items():
        above = max(0.0, (depth or 0.0) - floor_m)
        share = damage_share(above) if value_rm > 0 else None
        damage = value_rm * share if value_rm > 0 else flat if above > 0 else 0.0
        floods[rp] = {"depth_m": depth, "water_above_floor_m": round(above, 2),
                      "damage_share": None if share is None else round(share, 4), "direct": damage}
    return floods


def _basis(value_rm: float, shop_size: str, closure_rm: float) -> dict:
    """How the direct damage and the indirect loss were worked out, in words."""
    if value_rm > 0:
        direct = DIRECT_FROM_OWNER
    elif shop_size in JPS_POTENTIAL_DAMAGE_RM_2001:
        direct = DIRECT_FROM_SIZE.format(label=SIZE_LABEL[shop_size], unit=JPS_POTENTIAL_DAMAGE_RM_2001[shop_size])
    else:
        direct = DIRECT_NONE
    return {"direct": direct, "indirect": INDIRECT_FROM_OWNER if closure_rm > 0 else INDIRECT_DEFAULT}


def _yearly(floods: dict) -> float:
    return expected_yearly({rp: flood["total_rm"] for rp, flood in floods.items()})


def estimate(depth_m: dict[str, float | None], value_at_risk_rm: float, floor_height_cm: float = 0,
             daily_takings_rm: float = 0, closed_days: float = 0,
             raise_cm: float = 0, measure_cost_rm: float = 0, shop_size: str = "",
             extra_rm: dict[str, dict[str, int]] | None = None) -> dict:
    """Loss per flood, per year and over YEARS, and whether raising the stock by raise_cm pays for itself.

    The owner's own value_at_risk_rm is used when given; shop_size ("small", "medium", "complex") is the
    fallback. A measure is priced only from the owner's own value: the flat shop-size figure cannot do it.
    extra_rm adds other named losses per flood (wider_costs.per_flood: built-in works, vehicles, workers' pay) to
    each total; a measure that raises stock leaves them as they are.
    """
    closure_rm = daily_takings_rm * closed_days
    extra_rm = extra_rm or {}

    def priced(floor_cm: float, indirect_from: dict | None = None) -> dict:
        floods = {}
        for rp, flood in _direct(depth_m, value_at_risk_rm, shop_size, floor_cm / 100).items():
            direct = flood.pop("direct")
            if indirect_from:                      # a measure: the indirect loss stays as it was
                indirect = indirect_from[rp]["indirect_loss_rm"]
            elif closure_rm > 0:                   # a flooded street shuts the shop even if the floor stays dry
                indirect = round(closure_rm) if flood["depth_m"] else 0
            else:
                indirect = round(direct * JPS_INDIRECT_SHARE)
            extra = extra_rm.get(rp, {})
            floods[rp] = {**flood, "direct_damage_rm": round(direct), "indirect_loss_rm": indirect, **extra,
                          "total_rm": round(direct) + indirect + sum(extra.values())}
        return floods

    floods = priced(floor_height_cm)
    yearly = _yearly(floods)
    measure = None
    if raise_cm > 0 and value_at_risk_rm > 0:
        after = _yearly(priced(floor_height_cm + raise_cm, indirect_from=floods))
        benefit = present_value(yearly - after)
        # judged on unrounded ringgit, so rounding cannot flip the verdict on a cheap measure
        ratio = benefit / measure_cost_rm if measure_cost_rm > 0 else None
        measure = {"raise_cm": raise_cm, "cost_rm": measure_cost_rm, "yearly_loss_after_rm": round(after),
                   "benefit_present_value_rm": round(benefit),
                   "benefit_cost_ratio": None if ratio is None else round(ratio, 2),
                   "worth_it": None if ratio is None else ratio > WORTH_IT_ABOVE}
    return {"per_flood": floods, "basis": _basis(value_at_risk_rm, shop_size, closure_rm), "expected_yearly_loss_rm": round(yearly),
            "loss_over_years": {"years": YEARS, "discount_rate": DISCOUNT_RATE,
                                "present_value_rm": round(present_value(yearly))},
            "measure": measure}
