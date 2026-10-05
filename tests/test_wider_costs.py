"""Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_wider_costs.py

Losses beyond the shop's stock and lost sales (app/wider_costs.py): built-in works on the stock's curve, vehicles on
the USACE sedan curve at the street's water, workers' unpaid pay at the minimum wage, and how floodtools adds them to
each flood without changing what a measure is worth."""
import pytest

from app import costs, floodtools, wider_costs

WET = next(p for p in floodtools.premises() if p["depth_m"]["10"])
DEPTHS = {"10": 0.4, "20": 0.9, "50": 1.4}


@pytest.mark.parametrize("depth, share", [
    (None, 0.0), (-1, 0.0), (0, 0.0), (0.15, 0.076), (0.30, 0.28), (0.61, 0.462), (1.22, 0.76), (2.13, 1.0), (3, 1.0),
])
def test_vehicle_share_follows_the_usace_sedan_curve(depth, share):
    assert wider_costs.vehicle_share(depth) == pytest.approx(share)


def test_vehicle_share_is_straight_between_points():
    assert wider_costs.vehicle_share(0.455) == pytest.approx((0.28 + 0.462) / 2, abs=1e-3)


def test_one_flood_counts_built_ins_above_the_floor_vehicles_at_the_street_and_pay_while_wet():
    found = wider_costs.per_flood(0.9, 0.5, built_in_rm=20_000, vehicles_rm=60_000, unpaid_workers=2, closed_days=7)
    assert found == {"built_in_rm": round(20_000 * 0.38), "vehicles_rm": round(60_000 * wider_costs.vehicle_share(0.9)),
                     "wages_rm": round(2 * 65.38 * 7)}
    dry = wider_costs.per_flood(None, 0, built_in_rm=20_000, vehicles_rm=60_000, unpaid_workers=2, closed_days=7)
    assert dry == {"built_in_rm": 0, "vehicles_rm": 0, "wages_rm": 0}


def test_the_minimum_day_wage_is_the_gazetted_monthly_wage_over_26_days():
    assert wider_costs.MIN_WAGE_DAY_RM == pytest.approx(1_700 / 26, abs=0.01)


def test_estimate_adds_the_wider_losses_to_each_flood_and_the_yearly_figure():
    plain = floodtools.estimate_for(WET, 40_000, daily_takings_rm=500, closed_days=7)
    wider = floodtools.estimate_for(WET, 40_000, daily_takings_rm=500, closed_days=7,
                                    built_in_rm=20_000, vehicles_rm=60_000, unpaid_workers=2)
    for rp, flood in wider["per_flood"].items():
        added = flood["built_in_rm"] + flood["vehicles_rm"] + flood["wages_rm"]
        assert flood["total_rm"] == plain["per_flood"][rp]["total_rm"] + added
    assert wider["expected_yearly_loss_rm"] > plain["expected_yearly_loss_rm"]
    assert set(wider["basis"]) == {"direct", "indirect", "built_in", "vehicles", "wages"}
    assert wider["inputs"]["unpaid_workers"] == 2


def test_with_no_wider_figures_the_answer_keeps_its_old_shape():
    found = floodtools.estimate_for(WET, 40_000)
    assert "vehicles_rm" not in found["per_flood"]["10"]
    assert set(found["basis"]) == {"direct", "indirect"}


def test_a_measure_is_worth_the_same_with_or_without_the_wider_losses():
    figures = {"floor_height_cm": 0, "raise_cm": 50, "measure_cost_rm": 1_000}
    plain = floodtools.estimate_for(WET, 40_000, **figures)
    wider = floodtools.estimate_for(WET, 40_000, **figures, built_in_rm=20_000, vehicles_rm=60_000, unpaid_workers=3)
    assert wider["measure"]["benefit_present_value_rm"] == plain["measure"]["benefit_present_value_rm"]


def test_built_in_works_need_the_owners_own_value_as_the_size_figure_counts_the_building():
    assert "already counts the building" in floodtools.estimate_for(WET, 0, shop_size="medium", built_in_rm=10_000)["error"]
    assert "error" not in floodtools.estimate_for(WET, 0, shop_size="medium", vehicles_rm=30_000, unpaid_workers=2)


@pytest.mark.parametrize("name, bad", [("built_in_rm", 0.5), ("vehicles_rm", 0.5), ("vehicles_rm", -1),
                                       ("unpaid_workers", 1_001), ("built_in_rm", float("nan"))])
def test_wider_figures_out_of_range_are_refused(name, bad):
    assert "error" in floodtools.estimate_for(WET, 40_000, **{name: bad})


def test_costs_estimate_takes_extra_losses_by_flood():
    extra = {"10": {"vehicles_rm": 100}, "20": {"vehicles_rm": 200}, "50": {"vehicles_rm": 300}}
    plain = costs.estimate(DEPTHS, value_at_risk_rm=40_000)
    found = costs.estimate(DEPTHS, value_at_risk_rm=40_000, extra_rm=extra)
    assert [found["per_flood"][rp]["total_rm"] - plain["per_flood"][rp]["total_rm"] for rp in DEPTHS] == [100, 200, 300]


def test_built_ins_use_the_shops_own_floor_and_a_measure_still_ignores_them():
    figures = {"floor_height_cm": 20, "raise_cm": 50, "measure_cost_rm": 1_000}
    plain = floodtools.estimate_for(WET, 40_000, **figures)
    wider = floodtools.estimate_for(WET, 40_000, **figures, built_in_rm=20_000)
    for rp, depth in WET["depth_m"].items():
        above = max(0.0, (depth or 0.0) - 0.2)
        assert wider["per_flood"][rp]["built_in_rm"] == round(20_000 * costs.damage_share(above))
    assert wider["measure"]["benefit_present_value_rm"] == plain["measure"]["benefit_present_value_rm"]


def test_the_shops_own_yearly_loss_leaves_out_vehicles_and_workers_pay():
    shop_only = floodtools.estimate_for(WET, 40_000, built_in_rm=10_000)
    wider = floodtools.estimate_for(WET, 40_000, built_in_rm=10_000, vehicles_rm=60_000, unpaid_workers=2, closed_days=7)
    assert wider["expected_yearly_shop_loss_rm"] == shop_only["expected_yearly_loss_rm"]
    assert wider["expected_yearly_loss_rm"] > wider["expected_yearly_shop_loss_rm"]


def test_the_estimate_route_takes_the_wider_figures_and_words_a_bad_one_for_people():
    from fastapi.testclient import TestClient
    from app import main
    client = TestClient(main.app)
    sent = {"place": WET["id"], "value_at_risk_rm": 40_000, "closed_days": 7,
            "built_in_rm": 10_000, "vehicles_rm": 60_000, "unpaid_workers": 2}
    answer = client.post("/api/estimate", json=sent)
    assert answer.status_code == 200
    assert answer.json()["data"]["per_flood"]["50"]["vehicles_rm"] > 0
    bad = client.post("/api/estimate", json={**sent, "vehicles_rm": 0.5})
    assert bad.status_code == 422
    too_many = client.post("/api/estimate", json={**sent, "unpaid_workers": 5_000})
    assert too_many.status_code == 422
    assert "The number of workers must be" in too_many.text
