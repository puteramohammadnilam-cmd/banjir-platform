"""Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q"""
import pytest

from app import costs, floodtools

WET = next(p for p in floodtools.premises() if p["depth_m"]["10"])
DRY = next(p for p in floodtools.premises() if not p["depth_m"]["500"])
# Worked by hand from the JRC Asia commerce curve: shares 0.304, 0.508, 0.636 of RM 40,000.
DEPTHS = {"10": 0.4, "100": 0.9, "500": 1.4}
ANNUITY_10Y_4PCT = (1 - 1.04 ** -10) / 0.04   # 8.1109, the textbook closed form


@pytest.mark.parametrize("depth, share", [
    (-1, 0.0), (0, 0.0), (0.5, 0.38), (0.75, 0.46), (1, 0.54), (2.5, 0.82), (4.5, 0.96), (6, 1.0), (9, 1.0),
])
def test_damage_share_follows_the_published_asia_commerce_curve(depth, share):
    assert costs.damage_share(depth) == pytest.approx(share)


def test_expected_yearly_loss_is_the_area_under_the_loss_probability_curve():
    # nothing is assumed for floods more frequent than the most frequent one given
    yearly = costs.expected_yearly({"10": 1000, "100": 5000, "500": 9000})

    assert yearly == pytest.approx(0.09 * 3000 + 0.008 * 7000 + 0.002 * 9000)
    assert costs.expected_yearly({"100": 5000}) == pytest.approx(50)


def test_present_value_discounts_each_year_at_the_malaysian_rate():
    assert costs.DISCOUNT_RATE == 0.04
    assert costs.present_value(104, years=1) == pytest.approx(100)
    assert costs.present_value(100, years=2) == pytest.approx(100 / 1.04 + 100 / 1.04 ** 2)
    assert costs.present_value(100, years=0) == 0


def test_owner_value_route_matches_the_hand_worked_example():
    result = costs.estimate(DEPTHS, value_at_risk_rm=40_000)

    # direct 12,160 / 20,320 / 25,440; indirect is the JPS guideline 30% of direct when no closure is given
    floods = result["per_flood"]
    assert [f["direct_damage_rm"] for f in floods.values()] == [12_160, 20_320, 25_440]
    assert [f["indirect_loss_rm"] for f in floods.values()] == [3_648, 6_096, 7_632]
    assert [f["total_rm"] for f in floods.values()] == [15_808, 26_416, 33_072]
    assert floods["10"]["damage_share"] == 0.304
    assert result["expected_yearly_loss_rm"] == 2_204        # 1,695.52 x 1.3
    assert result["loss_over_years"] == {"years": 10, "discount_rate": 0.04,
                                         "present_value_rm": round(2_204.176 * ANNUITY_10Y_4PCT)}
    assert "your own value" in result["basis"]["direct"] and "30%" in result["basis"]["indirect"]
    assert result["measure"] is None


def test_owner_closure_figures_replace_the_30_percent_default():
    result = costs.estimate(DEPTHS, value_at_risk_rm=40_000, floor_height_cm=40,
                            daily_takings_rm=800, closed_days=5)

    flood = result["per_flood"]["100"]
    assert flood["water_above_floor_m"] == 0.5
    assert (flood["direct_damage_rm"], flood["indirect_loss_rm"], flood["total_rm"]) == (15_200, 4_000, 19_200)
    assert "days closed" in result["basis"]["indirect"]


def test_owner_closure_counts_when_the_street_floods_even_if_water_stays_below_the_floor():
    result = costs.estimate({"10": 0.1, "100": 0.2, "500": None}, value_at_risk_rm=40_000,
                            floor_height_cm=100, daily_takings_rm=500, closed_days=3)

    assert [f["total_rm"] for f in result["per_flood"].values()] == [1_500, 1_500, 0]


@pytest.mark.parametrize("takings, days", [(800, 0), (0, 5)])
def test_closure_needs_both_takings_and_days_or_the_30_percent_default_applies(takings, days):
    result = costs.estimate(DEPTHS, value_at_risk_rm=40_000, daily_takings_rm=takings, closed_days=days)

    assert [f["indirect_loss_rm"] for f in result["per_flood"].values()] == [3_648, 6_096, 7_632]
    assert "30%" in result["basis"]["indirect"]


def test_closure_alone_counts_no_direct_damage_and_says_so():
    result = costs.estimate(DEPTHS, value_at_risk_rm=0, daily_takings_rm=500, closed_days=3)

    assert [f["direct_damage_rm"] for f in result["per_flood"].values()] == [0, 0, 0]
    assert [f["indirect_loss_rm"] for f in result["per_flood"].values()] == [1_500, 1_500, 1_500]
    assert result["basis"]["direct"].startswith("none counted")


def test_a_dry_business_has_no_loss():
    result = costs.estimate(DRY["depth_m"], value_at_risk_rm=50_000, daily_takings_rm=800, closed_days=5)

    assert result["expected_yearly_loss_rm"] == 0
    assert all(f["total_rm"] == 0 for f in result["per_flood"].values())


def test_shop_size_route_uses_the_jps_klang_valley_figures_in_todays_prices():
    # small shop: RM 12,000 potential damage in 2001, x 134.60 / 81.66 for prices, x 0.8 actual-to-potential
    # the guideline's third class is "Large (Complexes)": a mall or hypermarket, not a big shop
    assert costs.JPS_POTENTIAL_DAMAGE_RM_2001 == {"small": 12_000, "medium": 24_000, "complex": 160_000}
    assert costs.PRICE_FACTOR == pytest.approx(1.6483, abs=0.0001)

    result = costs.estimate(DEPTHS, value_at_risk_rm=0, shop_size="small")

    floods = result["per_flood"]
    assert [f["direct_damage_rm"] for f in floods.values()] == [15_824] * 3   # flat: the guideline has no depth curve
    assert [f["indirect_loss_rm"] for f in floods.values()] == [4_747] * 3
    assert floods["10"]["damage_share"] is None
    assert result["expected_yearly_loss_rm"] == 2_057
    assert "JPS" in result["basis"]["direct"] and "2001" in result["basis"]["direct"]
    assert "0.5 to 0.9" in result["basis"]["direct"]          # the 0.8 is one point in the guideline's range
    assert costs.estimate(DEPTHS, 0, shop_size="medium")["per_flood"]["10"]["direct_damage_rm"] == 31_647
    assert "complex" in costs.estimate(DEPTHS, 0, shop_size="complex")["basis"]["direct"]


def test_shop_size_with_owner_closure_keeps_each_basis_separate():
    result = costs.estimate(DEPTHS, value_at_risk_rm=0, daily_takings_rm=500, closed_days=3, shop_size="small")

    assert result["per_flood"]["10"]["total_rm"] == 15_824 + 1_500
    assert "JPS" in result["basis"]["direct"] and "days closed" in result["basis"]["indirect"]


def test_shop_size_figure_cannot_price_a_measure():
    # a flat figure would make the saving jump from nothing to everything at one centimetre
    result = costs.estimate(DEPTHS, value_at_risk_rm=0, shop_size="small", raise_cm=50, measure_cost_rm=1_000)

    assert result["measure"] is None


def test_shop_size_route_counts_only_floods_that_reach_the_floor():
    result = costs.estimate(DEPTHS, value_at_risk_rm=0, floor_height_cm=50, shop_size="small")

    assert [f["direct_damage_rm"] for f in result["per_flood"].values()] == [0, 15_824, 15_824]


def test_the_owners_own_value_wins_over_the_shop_size():
    with_size = costs.estimate(DEPTHS, value_at_risk_rm=40_000, shop_size="complex")

    assert with_size == costs.estimate(DEPTHS, value_at_risk_rm=40_000)


def test_raising_stock_is_credited_with_the_stock_damage_it_avoids_and_nothing_else():
    # direct loss per year falls from 1,695.52 to 717.76; the indirect loss is left as it was
    for closure in ({}, {"daily_takings_rm": 500, "closed_days": 2}):
        before = costs.estimate(DEPTHS, value_at_risk_rm=40_000, **closure)

        measure = costs.estimate(DEPTHS, value_at_risk_rm=40_000, raise_cm=50, measure_cost_rm=1_000, **closure)["measure"]

        assert before["expected_yearly_loss_rm"] - measure["yearly_loss_after_rm"] == pytest.approx(977.76, abs=1)
        assert measure["benefit_present_value_rm"] == round(977.76 * ANNUITY_10Y_4PCT)
        assert measure["benefit_cost_ratio"] == 7.93
        assert measure["worth_it"] is True


def test_a_measure_that_saves_nothing_is_not_worth_it():
    # the floor is already above every flood, so only the closure loss remains and raising stock cannot cut it
    result = costs.estimate(DEPTHS, value_at_risk_rm=40_000, floor_height_cm=200, daily_takings_rm=500,
                            closed_days=3, raise_cm=50, measure_cost_rm=1_000)

    assert result["measure"]["yearly_loss_after_rm"] == result["expected_yearly_loss_rm"] == 150
    assert result["measure"]["benefit_cost_ratio"] == 0
    assert result["measure"]["worth_it"] is False


def test_a_cheap_measure_is_judged_on_unrounded_savings():
    # saves RM 0.46 a year, RM 3.70 over ten years: worth RM 3, not worth RM 4
    depth = {"10": None, "100": None, "500": 0.5}
    kwargs = {"value_at_risk_rm": 200, "raise_cm": 50}

    assert costs.estimate(depth, measure_cost_rm=3, **kwargs)["measure"]["worth_it"] is True
    assert costs.estimate(depth, measure_cost_rm=4, **kwargs)["measure"]["worth_it"] is False


def test_tool_returns_the_estimate_with_its_basis_method_and_limits():
    result = floodtools.damage_estimate(WET["id"], 50_000, "", 300, 800, 365, 0, 0)   # 300 cm and 365 days are allowed

    assert result["business"] == WET["name"]
    assert result["expected_yearly_loss_rm"] > 0
    assert result["basis"]["direct"] and result["basis"]["indirect"]
    assert result["inputs"]["shop_size"] == ""
    assert "Asia" in result["limits"] and "JPS" in result["limits"] and "4%" in result["method"]
    assert "first approximation" in result["limits"]


def test_tool_accepts_a_shop_size_when_the_owner_has_no_value():
    result = floodtools.damage_estimate(WET["id"], 0, "Medium ", 0, 0, 0, 0, 0)

    assert result["inputs"]["shop_size"] == "medium"
    assert result["expected_yearly_loss_rm"] > 0


def test_tool_does_not_echo_a_shop_size_it_did_not_use():
    result = floodtools.damage_estimate(WET["id"], 50_000, "complex", 0, 0, 0, 0, 0)

    assert result["inputs"]["shop_size"] == "" and "your own value" in result["basis"]["direct"]


def test_tool_estimates_closure_alone():
    result = floodtools.damage_estimate(WET["id"], 0, "", 0, 500, 3, 0, 0)

    assert result["expected_yearly_loss_rm"] > 0 and result["basis"]["direct"].startswith("none counted")


@pytest.mark.parametrize("args", [
    ("nope", 50_000, "", 0, 0, 0, 0, 0),
    (["node-1"], 50_000, "", 0, 0, 0, 0, 0),
    (WET["id"], -1, "", 0, 0, 0, 0, 0),
    (WET["id"], 50_000, "", 301, 0, 0, 0, 0),
    (WET["id"], 50_000, "", 0, 0, 366, 0, 0),
    (WET["id"], float("nan"), "", 0, 0, 0, 0, 0),
    (WET["id"], float("inf"), "", 0, 0, 0, 0, 0),
    (WET["id"], 10 ** 400, "", 0, 0, 0, 0, 0),
    (WET["id"], True, "", 0, 0, 0, 0, 0),
    (WET["id"], "50000", "", 0, 0, 0, 0, 0),
    (WET["id"], None, "", 0, 0, 0, 0, 0),
    (WET["id"], 50_000, "", 0, 0, 0, 50, 0),      # a measure needs a cost to be judged
    (WET["id"], 50_000, "", 0, 0, 0, 0, 500),     # and a cost needs a measure
    (WET["id"], 0, "huge", 0, 0, 0, 0, 0),        # not a size the guideline has
    (WET["id"], 0, "large", 0, 0, 0, 0, 0),       # the guideline's large class is a complex; make the model ask
    (WET["id"], 0, None, 0, 0, 0, 0, 0),
    (WET["id"], 0, 0, 0, 0, 0, 0, 0),
    (WET["id"], 0, ["small"], 0, 0, 0, 0, 0),
    (WET["id"], 0, "", 0, 0, 0, 0, 0),            # nothing to estimate from
    (WET["id"], 0, "small", 0, 0, 0, 50, 1_000),  # a flat shop-size figure cannot price a measure
    (WET["id"], 0, "", 0, 500, 3, 50, 1_000),     # nor can closure alone
    (WET["id"], 0.5, "small", 0, 0, 0, 0, 0),     # a value under RM 1 is a slip, not a value
    (WET["id"], 50_000, "", 0, 0, 0, 50, 5e-324),  # nor is a cost under RM 1
])
def test_tool_rejects_bad_input_with_an_error_the_model_can_relay(args):
    assert "error" in floodtools.damage_estimate(*args)


# ---------- the same estimate as a form on the page

def estimate_body(**change):
    return {"business_id": WET["id"], "value_at_risk_rm": 50_000, "shop_size": "", "floor_height_cm": 30,
            "daily_takings_rm": 800, "closed_days": 5, "raise_cm": 50, "measure_cost_rm": 1_500, **change}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app import main
    main._hits.clear()
    return TestClient(main.app)


def test_estimate_endpoint_returns_the_tool_result(client):
    body = client.post("/api/estimate", json=estimate_body()).json()

    assert body["success"] is True
    assert body["data"] == floodtools.damage_estimate(**estimate_body())


def test_estimate_endpoint_fills_missing_fields_with_zero(client):
    data = client.post("/api/estimate", json={"business_id": WET["id"], "shop_size": "small"}).json()["data"]

    assert data["inputs"]["shop_size"] == "small" and data["expected_yearly_loss_rm"] > 0


@pytest.mark.parametrize("change, status", [
    ({"raise_cm": 50, "measure_cost_rm": 0}, 422),   # the tool's own rule, passed on as its message
    ({"floor_height_cm": 301}, 422),
    ({"value_at_risk_rm": "a lot"}, 422),
    ({"business_id": "node-nope"}, 404),
])
def test_estimate_endpoint_rejects_bad_input(client, change, status):
    response = client.post("/api/estimate", json=estimate_body(**change))

    assert response.status_code == status and response.json()["success"] is False


def test_estimate_errors_are_worded_for_people_not_the_model(client):
    typo = client.post("/api/estimate", json=estimate_body(value_at_risk_rm="a lot")).json()["error"]
    pair = client.post("/api/estimate", json=estimate_body(measure_cost_rm=0)).json()["error"]
    size = client.post("/api/estimate", json=estimate_body(value_at_risk_rm=0, shop_size="huge")).json()["error"]

    assert "figures" in typo and "Questions" not in typo
    assert "raise" in pair and "raise_cm" not in pair and "measure_cost_rm" not in pair
    assert size.startswith("The shop size") and "Ask the owner" not in size
