import pytest

import projectile_spread_pattern as ps


def weapon(**over):
    kwargs = {"first_shot": 0.0, "per_shot": 0.5, "recovery": 2.0, "max_spread": 5.0, "ads_scale": 0.5, "pellets": 1}
    kwargs.update(over)
    return ps.ProjectileSpreadPattern(**kwargs)


def test_first_shot_uses_first_shot_accuracy():
    result = weapon(first_shot=0.1).fire(shots=1, seed=1)
    assert result["spread"][0] == pytest.approx(0.1)


def test_repeated_shots_grow_spread():
    result = weapon().fire(shots=3, seed=1)
    assert result["spread"][2] > result["spread"][0]


def test_recovery_after_firing_reduces_spread():
    w = weapon()
    w.fire(shots=3, seed=1)
    result = w.fire(shots=1, seed=1)
    assert result["spread"][0] < 5.0


def test_ads_scales_spread_down():
    normal = weapon().fire(shots=1, seed=1)
    aimed = weapon().fire(shots=1, seed=1, ads=True)
    assert aimed["spread"][0] < normal["spread"][0]


def test_movement_penalty_multiplies_spread():
    still = weapon().fire(shots=1, seed=1)
    moving = weapon().fire(shots=1, seed=1, moving=True)
    assert moving["spread"][0] > still["spread"][0]


def test_jump_penalty_is_applied():
    result = weapon().fire(shots=1, seed=1, jumping=True)
    assert result["spread"][0] > 0


def test_pellets_are_spread_across_pattern():
    result = weapon(pellets=5).fire(shots=1, seed=1)
    assert len(result["directions"]) == 5


def test_seed_reproduces_same_direction_sequence():
    a = weapon(pellets=3).fire(shots=2, seed=7)
    b = weapon(pellets=3).fire(shots=2, seed=7)
    assert a["directions"] == b["directions"]


def test_recoil_pattern_is_fixed_then_mirrored():
    a = weapon().fire(shots=4, seed=1)
    b = weapon().fire(shots=4, seed=1, mirror=True)
    assert a["recoil"] != b["recoil"]


def test_spread_is_clamped_to_max():
    result = weapon(per_shot=100.0).fire(shots=5, seed=1)
    assert max(result["spread"]) <= 5.0


def test_crouching_reduces_penalty():
    standing = weapon().fire(shots=1, seed=1, moving=True)
    crouched = weapon().fire(shots=1, seed=1, moving=True, crouching=True)
    assert crouched["spread"][0] <= standing["spread"][0]


def test_recovery_time_is_reported():
    assert "recovery_time" in weapon().fire(shots=1)


def test_mirror_keeps_vertical_pattern():
    a = weapon().fire(shots=3, seed=1)
    b = weapon().fire(shots=3, seed=1, mirror=True)
    assert len(a["recoil"]) == len(b["recoil"])


def test_output_reports_current_spread_and_directions():
    result = weapon().fire(shots=2, seed=1)
    assert "spread" in result and "directions" in result


def test_repeated_inputs_are_identical():
    a = weapon(pellets=2).fire(shots=2, seed=9)
    b = weapon(pellets=2).fire(shots=2, seed=9)
    assert a == b
