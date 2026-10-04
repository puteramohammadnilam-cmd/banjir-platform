"""tools/build_section_scores.py on hand cases, no network: the weights over 74, the rating classes, area-weighted
section means on a 4 x 4 grid of two sections, class shares, Spearman's rho with tied ranks against a hand working,
hotspot ranks, and the indexes.json shape against tests/fixtures/index_contract.json."""
import json
import math
import sys
from array import array
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_section_scores as bs  # noqa: E402
import grid_ops as go  # noqa: E402

CONTRACT = json.loads((ROOT / "tests" / "fixtures" / "index_contract.json").read_text(encoding="utf-8"))
SCORE_EXAMPLE = CONTRACT["indexes_json"]["example"]["method"]["score"]


def test_the_weights_are_leeonis_less_rainfall_and_loss_over_74():
    weights = {c.id: c.weight for c in bs.CRITERIA}
    assert weights == {"river_distance": 18, "drainage_density": 16, "elevation": 10, "land_cover": 9, "slope": 8,
                       "road_distance": 7, "population_density": 6}
    assert sum(weights.values()) == bs.WEIGHTS_TOTAL == 74
    used = bs.weights_used()
    assert used == {k: round(w / 74, 4) for k, w in weights.items()}
    assert sum(w / 74 for w in weights.values()) == pytest.approx(1.0)
    assert [c.id for c in bs.CRITERIA] == [c["id"] for c in SCORE_EXAMPLE["criteria"]]


@pytest.mark.parametrize("value, rating", [(0, 5), (99.9, 5), (100, 4), (249, 4), (250, 3), (500, 2), (999, 2),
                                           (1000, 1), (math.inf, 1)])
def test_distance_to_a_river_rates_5_near_and_1_from_a_kilometre(value, rating):
    river = next(c for c in bs.CRITERIA if c.id == "river_distance")
    assert bs.rate(value, river.breaks, river.ratings) == rating


def test_every_criterion_has_one_more_rating_than_breaks_and_rising_breaks():
    for c in bs.CRITERIA:
        if c.id == "land_cover":
            assert c.breaks == () and set(bs.LAND_SCORES) == {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
            continue
        assert len(c.ratings) == len(c.breaks) + 1 and list(c.breaks) == sorted(c.breaks), c.id
        assert sorted(c.ratings) == [1, 2, 3, 4, 5], c.id


@pytest.mark.parametrize("people, rating", [(0, 1), (999, 1), (1000, 2), (7440, 2), (7441, 3), (18187, 3),
                                            (18188, 4), (43791, 4), (43792, 5), (86548, 5)])
def test_population_is_rated_by_the_paper_s_people_per_section(people, rating):
    population = next(c for c in bs.CRITERIA if c.id == "population_density")
    assert population.unit == "people per section"
    assert bs.rate(people, population.breaks, population.ratings) == rating


def test_the_people_of_a_section_are_summed_and_given_to_each_of_its_squares():
    grid, holder, _ = four_by_four()
    people = array("d", [100.0] * 16)
    people[6] = 0.0                                       # water: no people, still in the section
    totals = bs.section_totals(people, holder, 3)
    assert totals == [800.0, 600.0, 0.0]                  # the north-east square is in no section
    spread = bs.by_section(totals, holder)
    assert [spread[i] for i in (0, 2, 6, 15)] == [800.0, 600.0, 600.0, 600.0] and spread[3] == go.NODATA


def test_the_population_criterion_rates_every_square_of_a_section_alike():
    grid, holder, _ = four_by_four()
    land = array("d", [3.0] * 16)
    people = array("d", [1500.0] * 16)                    # 12 000 in the west section, 9 000 in the east one
    values = {c.id: array("d", [0.0] * 16) for c in bs.CRITERIA}
    values["population_density"] = bs.by_section(bs.section_totals(people, holder, 2), holder)
    rated = bs.square_ratings(values, land)["population_density"]
    assert {rated[i] for i in range(16) if holder[i] == 0} == {3.0} == {rated[i] for i in range(16) if holder[i] == 1}
    assert bs.section_means(rated, holder, grid, 2) == pytest.approx([3.0, 3.0])


def test_a_square_without_a_value_has_no_rating_rather_than_the_highest():
    land = array("d", [3.0, 3.0, go.NODATA])
    values = {c.id: array("d", [10.0, 10.0, 10.0]) for c in bs.CRITERIA}
    values["elevation"][0] = go.NODATA                    # a hole in the surface model
    values["slope"][1] = go.NODATA
    rated = bs.square_ratings(values, land)
    assert rated["elevation"][0] == go.NODATA and rated["slope"][1] == go.NODATA
    assert rated["elevation"][1] == 5 and rated["slope"][0] == 3      # 10 m and 10 %, by the paper's classes
    assert all(rated[c.id][2] == go.NODATA for c in bs.CRITERIA)     # not land


def test_the_deviations_say_which_classes_are_ours_and_how_population_is_counted():
    text = " ".join(bs.score_text.DEVIATIONS)
    assert "drainage density classes" in text.lower() and "are ours" in text
    population = [d for d in bs.score_text.DEVIATIONS if "Population" in d]
    assert len(population) == 1 and "people per section" in population[0] and "per km2" not in population[0]
    assert "people per section" in bs.score_text.SOURCES["population_density"]


def test_the_score_credits_worldpop_and_openstreetmap():
    credit = bs.score_text.score_method()["credit"]
    for part in ("WorldPop 2020 constrained", "CC BY 4.0", "doi:10.5258/SOTON/WP00660", "OpenStreetMap contributors",
                 "ODbL"):
        assert part in credit, part
    assert bs.method_doc()["score"]["credit"] == credit


def test_land_cover_ratings_mix_by_pixel_share():
    assert bs.land_cover_rating({50: 60, 10: 40}) == pytest.approx((60 * 5 + 40 * 1) / 100)
    assert bs.land_cover_rating({}) is None


@pytest.mark.parametrize("value, name", [(1.0, "very_low"), (1.49, "very_low"), (1.5, "low"), (2.5, "moderate"),
                                         (3.49, "moderate"), (3.5, "high"), (4.5, "very_high"), (5.0, "very_high")])
def test_score_classes_break_at_1_5_2_5_3_5_4_5(value, name):
    assert bs.score_class(value) == name


def four_by_four():
    """Two sections on a 4 x 4 grid whose rows sit far apart in latitude, so the area weights differ: section 0 the
    west half, section 1 the east half, one square of section 1 water (no data), the north-east corner outside."""
    grid = go.Grid(101.0, 60.0, 10.0, 15.0, 4, 4)            # row centres at 52.5, 37.5, 22.5 and 7.5 N
    holder = array("i", [0, 0, 1, -1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1])
    values = array("d", [r * 4 + c for r in range(4) for c in range(4)])
    values[6] = go.NODATA
    return grid, holder, values


def test_section_means_weight_each_square_by_its_area():
    grid, holder, values = four_by_four()
    means = bs.section_means(values, holder, grid, 2)
    w = [math.cos(math.radians(lat)) for lat in (52.5, 37.5, 22.5, 7.5)]
    west = sum(w[r] * (r * 4 + c) for r in range(4) for c in (0, 1)) / sum(2 * w[r] for r in range(4))
    east = (w[0] * 2 + w[1] * 7 + w[2] * (10 + 11) + w[3] * (14 + 15)) / (w[0] + w[1] + 2 * w[2] + 2 * w[3])
    assert means[0] == pytest.approx(west) and means[1] == pytest.approx(east)


def test_flash_shares_are_area_weighted_and_add_up_to_one():
    grid, holder, _ = four_by_four()
    scores = array("d", [2.0, 4.0, 6.5, 9.0, 8.0, 5.5, go.NODATA, 4.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 8.5, 8.4])
    found = bs.flash_summary(scores, holder, grid, 2)
    w = [math.cos(math.radians(lat)) for lat in (52.5, 37.5, 22.5, 7.5)]
    east = w[0] + w[1] + 2 * w[2] + 2 * w[3]
    assert found[1]["share"]["high"] == round((w[0] + w[3]) / east, 3)            # 6.5 and 8.4
    assert found[1]["share"]["extreme"] == round(w[3] / east, 3)                  # 8.5
    assert found[1]["share"]["medium"] == round(w[1] / east, 3)                   # 4.5
    assert sum(found[0]["share"].values()) == pytest.approx(1.0, abs=0.002)
    assert list(found[0]["share"]) == ["low", "medium", "high", "extreme"]


def test_a_section_without_land_squares_has_no_figures():
    grid, holder, values = four_by_four()
    assert bs.section_means(values, holder, grid, 3)[2] is None
    assert bs.flash_summary(values, holder, grid, 3)[2] is None


def test_average_ranks_share_ties():
    assert bs.average_ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]


def test_spearman_with_ties_matches_a_hand_working():
    x, y = [1, 2, 2, 3, 4], [0, 1, 0, 2, 5]
    rx, ry = [1, 2.5, 2.5, 4, 5], [1.5, 3, 1.5, 4, 5]
    mx, my = sum(rx) / 5, sum(ry) / 5
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    hand = cov / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    assert bs.spearman(x, y) == pytest.approx(hand)
    assert bs.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert bs.spearman([1, 1, 1], [1, 2, 3]) is None


def test_hotspot_ranks_count_from_the_highest_and_ties_share_the_best_rank():
    assert bs.top_ranks([0.5, 0.9, 0.9, 0.1]) == [3, 1, 1, 4]


def test_history_counts_count_each_section_an_event_names():
    events = [{"sections": ["seksyen-1", "seksyen-2"]}, {"sections": ["seksyen-2"]}, {"sections": []}]
    assert bs.history_counts(events, ["seksyen-1", "seksyen-2", "seksyen-3"]) == [1, 2, 0]


def test_the_document_has_the_contract_s_keys():
    ids = ["seksyen-1", "seksyen-2"]
    flash = [{"mean": 5.0, "share": {"low": 0.0, "medium": 1.0, "high": 0.0, "extreme": 0.0}}, None]
    ratings = {c.id: [3.0, None] for c in bs.CRITERIA}
    doc = bs.indexes_doc(ids, flash, ratings, {"flash": flash[0], "score": None}, {"n": 2})
    example = CONTRACT["indexes_json"]["example"]
    assert set(doc) == set(example)
    assert set(doc["method"]) == set(example["method"]) and set(doc["method"]["score"]) >= set(SCORE_EXAMPLE)
    assert doc["sections"]["seksyen-2"] == {"flash": None, "score": None}
    one = doc["sections"]["seksyen-1"]
    assert set(one["score"]) == {"value", "class", "ratings"} and list(one["score"]["ratings"]) == list(ratings)
    assert one["score"]["value"] == 3.0 and one["score"]["class"] == "moderate"
