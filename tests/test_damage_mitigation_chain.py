import pytest

import damage_mitigation_chain as dm


def hit(**over):
    item = {
        "base": 100.0,
        "crit": 1.0,
        "armor_flat": 10.0,
        "armor_pct": 0.2,
        "shield": 15.0,
        "shield_type": "physical",
        "damage_type": "physical",
        "vulnerability": 1.0,
        "final_mult": 1.0,
        "target_hp": 500.0,
        "min_damage": 0.0,
    }
    item.update(over)
    return item


def resolve(h=None, **over):
    kwargs = {"order": None, "min_damage": 0, "resist_cap": 0.8}
    kwargs.update(over)
    return dm.DamageMitigationChain(**kwargs).resolve(h or hit())


def test_flat_mitigation_runs_before_percent():
    result = resolve(hit(armor_flat=20, armor_pct=0.5))
    assert result["damage"] == 40.0


def test_shield_is_applied_after_mitigation():
    result = resolve(hit(base=100, armor_flat=20, armor_pct=0.5, shield=15))
    assert result["shield_absorbed"] == 15
    assert result["damage"] == 25


def test_true_damage_skips_armor_and_shield():
    result = resolve(hit(damage_type="true", shield=100, armor_flat=50, armor_pct=0.5))
    assert result["damage"] == 100


def test_crit_is_applied_before_mitigation():
    result = resolve(hit(base=100, crit=2.0, armor_flat=50, armor_pct=0.0))
    assert result["damage"] == 150


def test_minimum_damage_is_configurable():
    result = resolve(hit(base=10, armor_flat=100), min_damage=5)
    assert result["damage"] == 5


def test_rounding_uses_half_up():
    result = resolve(hit(base=1.5, armor_flat=0, armor_pct=0, shield=0))
    assert result["damage"] == 2


def test_resistance_cap_is_clamped():
    result = resolve(hit(base=100, armor_pct=1.5))
    assert result["damage"] >= 20


def test_multi_hit_sums_before_rounding():
    hits = [hit(base=10.5, armor_flat=0, armor_pct=0, shield=0) for _ in range(3)]
    result = dm.DamageMitigationChain().resolve_all(hits)
    assert result["damage"] == 32
    assert result["rounding_diff"] == 0


def test_reflect_uses_actual_health_loss():
    result = resolve(hit(base=100, target_hp=30, reflect=0.5))
    assert result["reflected"] == 15


def test_overflow_can_pass_to_next_target():
    result = resolve(hit(base=100, target_hp=30, overflow=True))
    assert result["overflow"] == 70


def test_negative_inputs_are_rejected():
    with pytest.raises(ValueError):
        resolve(hit(base=-1))


def test_shield_type_must_match_damage_type():
    result = resolve(hit(damage_type="magic", shield=50, shield_type="physical"))
    assert result["shield_absorbed"] == 0


def test_vulnerability_multiplies_after_shield():
    result = resolve(hit(base=100, armor_flat=0, armor_pct=0, shield=0, vulnerability=1.5))
    assert result["damage"] == 150


def test_order_is_exposed_in_result():
    result = resolve()
    assert result["order"][:2] == ["crit", "flat"]


def test_sum_and_per_hit_rounding_difference_is_reported():
    hits = [hit(base=1.4, armor_flat=0, armor_pct=0, shield=0) for _ in range(3)]
    result = dm.DamageMitigationChain().resolve_all(hits)
    assert "rounding_diff" in result
