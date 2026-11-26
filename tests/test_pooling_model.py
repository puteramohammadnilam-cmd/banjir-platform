"""The rain ponding screening model (app/pooling_model.py), on small made-up grids whose answer can be worked out by
hand. Run from 11_Platform_Draft:  .venv/bin/python -m pytest -q tests/test_pooling_model.py"""
import numpy as np
import pytest

from app import pooling_model as pm

SPACING = (10.0, 10.0)   # 100 m2 a square


def bowl(size=9, rim=10.0, floor=8.0):
    """A square plain at `rim` with one dip in the middle: the centre 3 x 3 squares at `floor`."""
    ground = np.full((size, size), rim)
    mid = size // 2
    ground[mid - 1:mid + 2, mid - 1:mid + 2] = floor
    return ground


def test_priority_flood_fills_a_dip_to_its_rim_and_leaves_the_plain():
    ground = bowl()
    filled, down = pm.priority_flood(ground)
    assert np.allclose(filled[3:6, 3:6], 10.0) and np.allclose(filled[0], 10.0)
    assert down[0] == pm.NO_DOWN and down[4 * 9 + 4] >= 0


def test_a_dip_holds_rain_from_its_catchment_and_spills_none_while_not_full():
    ground = bowl()
    # 9 squares 2 m deep hold 1800 m3. The flat plain has no steepest drop, so only the rain of the dip's 9 squares and
    # of the 16 squares sloping into it lands in it: 25 squares, 2500 m2.
    depth = pm.ponding(ground, storm_mm=130, spacing=SPACING, drains_mm=30, runoff=1.0)
    water = depth[3:6, 3:6]
    assert np.all(np.isfinite(water)) and np.allclose(water, water[0, 0])
    assert 0 < water[0, 0] < 2.0
    assert np.isnan(depth[0, 0]), "no water stands on the plain"


def test_no_water_below_the_drains_capacity_and_more_rain_more_water():
    ground = bowl()
    assert np.all(np.isnan(pm.ponding(ground, storm_mm=30, spacing=SPACING, drains_mm=30)))
    # 25 squares drain into the dip (its 9 and the 16 sloping into it): 80 mm leaves 0.04 m x 2500 m2 = 100 m3 over its
    # 900 m2, about 0.11 m; 150 mm about 0.27 m
    light = pm.ponding(ground, storm_mm=80, spacing=SPACING, drains_mm=30)
    heavy = pm.ponding(ground, storm_mm=150, spacing=SPACING, drains_mm=30)
    assert np.nanmax(heavy) > np.nanmax(light)


def test_a_full_dip_spills_into_the_dip_below_it():
    ground = np.full((7, 15), 10.0)
    ground[2:5, 2:5] = 9.8        # a shallow upper dip
    ground[2:5, 9:12] = 7.0       # a deep lower dip
    ground[3, 5:9] = [9.9, 9.7, 9.5, 9.3]   # a channel from the upper dip's rim down to the lower dip
    big = pm.ponding(ground, storm_mm=1000, spacing=SPACING, drains_mm=0, runoff=1.0)
    assert np.nanmax(big[2:5, 9:12]) > 0
    upper = big[2:5, 2:5]
    assert np.nanmax(upper) <= 0.2 + 1e-9, "the upper dip is at most full"


def test_fill_level_rises_through_the_squares_in_height_order():
    heights = np.array([0.0, 1.0, 2.0])
    assert pm.fill_level(heights, 0, 1.0, 5) == 0.0
    assert pm.fill_level(heights, 0.5, 1.0, 5) == pytest.approx(0.5)       # the lowest square only
    assert pm.fill_level(heights, 1.0, 1.0, 5) == pytest.approx(1.0)
    assert pm.fill_level(heights, 2.0, 1.0, 5) == pytest.approx(1.5)       # two squares share the next 1 m3
    assert pm.fill_level(heights, 100, 1.0, 2.5) == pytest.approx(2.5), "never above the spill level"


def test_upstream_finds_the_area_draining_to_a_square():
    ground = np.full((5, 5), 10.0)          # high walls, one gap at (2, 4)
    ground[1:4, 1:4] = [[4, 3, 2]] * 3      # the inside slopes down to the gap
    ground[2, 4] = 0.0
    _, down = pm.priority_flood(ground)
    inside = pm.upstream(down, ground.shape, 2 * 5 + 4)
    assert inside[1:4, 1:4].all() and inside.sum() == 10, "the nine inside squares and the gap itself"


def test_nan_squares_are_an_outlet_not_a_dip():
    ground = bowl()
    ground[4, 4] = np.nan          # a hole in the data in the middle of the dip: water leaves there
    depth = pm.ponding(ground, storm_mm=200, spacing=SPACING, drains_mm=30, runoff=1.0)
    assert np.all(np.isnan(depth[3:6, 3:6]))


def valley(with_upper_dip=True):
    """A valley sloping east between high walls, water leaving only at its low east end; a deep dip across the floor
    downhill, and (optionally) a dip uphill whose outlet's steepest slope runs back into it (Fable's case)."""
    ground = np.tile(20.0 - np.arange(15, dtype=float), (7, 1))
    ground[0, :] = ground[6, :] = ground[:, 0] = 30.0
    if with_upper_dip:
        ground[2:5, 4] = 13.0
    ground[1:6, 10:12] -= 3.0
    return ground


def test_what_a_full_dip_spills_reaches_the_dip_downhill_even_when_its_outlet_slopes_back():
    ground = valley()
    filled, down, dips, ends, reach = prepared = pm.prepare(ground, SPACING)
    upper, lower = dips.label[3, 4], dips.label[3, 11]
    outlet = dips.outlet[upper]
    assert dips.label.ravel()[ends[outlet]] == upper, "the outlet's steepest slope runs back into the dip"
    assert reach[outlet] == lower, "but its overflow path reaches the dip downhill"
    # 150 mm: the upper dip overflows, the lower is not full, so no water is lost: what both hold together equals what
    # the lower one holds with no upper dip at all
    with_upper = pm.ponding(ground, 150, SPACING, drains_mm=0, runoff=1.0, prepared=prepared)
    without = pm.ponding(valley(False), 150, SPACING, drains_mm=0, runoff=1.0)
    assert np.nansum(with_upper) == pytest.approx(np.nansum(without), abs=0.01)
    assert np.nanmax(with_upper[2:5, 4]) == pytest.approx(2.0), "the upper dip is full"


def test_rain_ending_in_a_pit_too_shallow_to_count_goes_on_to_the_next_dip():
    ground = valley(False)
    ground[3, 3] -= 0.05              # a pit under MIN_DIP_M up the valley: its rain must not vanish
    shallow = pm.ponding(ground, 100, SPACING, drains_mm=0, runoff=1.0)
    plain = pm.ponding(valley(False), 100, SPACING, drains_mm=0, runoff=1.0)
    assert np.nansum(shallow) == pytest.approx(np.nansum(plain), abs=0.01)


def test_first_dip_follows_the_overflow_path_and_ends_at_the_edge():
    label = np.array([-1, -1, 7, -1, -1])
    down = np.array([1, 2, 3, pm.NO_DOWN, 3])     # 0 -> 1 -> 2 (dip 7) -> 3 (edge); 4 -> 3
    assert pm.first_dip(label, down).tolist() == [7, 7, 7, -1, -1]
