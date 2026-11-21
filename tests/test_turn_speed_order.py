import pytest

import turn_speed_order as ts


def unit(uid, speed=10, priority=0, side="ally", slot=0, status="alive", **over):
    item = {
        "id": uid,
        "speed": speed,
        "priority": priority,
        "side": side,
        "slot": slot,
        "status": status,
        "haste": 1.0,
        "slow": 1.0,
        "reinforcement_round": 0,
        "delay_round": 0,
        "extra": False,
        "once_modifier": 0,
    }
    item.update(over)
    return item


def order(units, round_no=1):
    return ts.TurnSpeedOrder().order(units, round_no=round_no)


def test_speed_tie_breaks_by_side_slot_and_id():
    units = [unit("b", side="enemy", slot=1), unit("a", side="ally", slot=2), unit("c", side="ally", slot=1)]
    assert order(units)["order"][:3] == ["c", "a", "b"]


def test_haste_and_slow_multiply_and_clamp():
    units = [unit("fast", speed=10, haste=3.0), unit("slow", speed=10, slow=10.0)]
    result = order(units)
    assert result["order"][0] == "fast"
    assert "slow" in result["reasons"]


def test_priority_group_inserts_before_speed():
    units = [unit("fast", speed=100), unit("skill", speed=1, priority=1)]
    assert order(units)["order"][0] == "skill"


def test_stunned_unit_is_skipped_but_still_counted():
    result = order([unit("a", status="stunned"), unit("b")])
    assert result["order"] == ["b"]
    assert "a" in result["skipped"]
    assert result["turn_count"] == 2


def test_reinforcement_waits_for_next_round():
    result = order([unit("a"), unit("new", reinforcement_round=2)], round_no=1)
    assert "new" not in result["order"]
    assert "new" in order([unit("a"), unit("new", reinforcement_round=2)], round_no=2)["order"]


def test_extra_action_is_inserted_at_end_of_round():
    units = [unit("a", speed=100, extra=True), unit("b", speed=1)]
    result = order(units)
    assert result["order"][-1] == "a"
    assert result["order"].count("a") == 2


def test_delayed_action_moves_to_target_round():
    units = [unit("a", delay_round=2)]
    assert "a" not in order(units, round_no=1)["order"]
    assert "a" in order(units, round_no=2)["order"]


def test_zero_speed_uses_minimum_and_is_flagged():
    result = order([unit("a", speed=0), unit("b", speed=1)])
    assert result["order"][-1] == "a"
    assert "zero_speed" in result["reasons"]["a"]


def test_negative_speed_uses_minimum_and_is_flagged():
    result = order([unit("a", speed=-50), unit("b", speed=1)])
    assert result["order"][-1] == "a"
    assert "negative_speed" in result["reasons"]["a"]


def test_one_time_modifiers_are_cleared_at_round_end():
    units = [unit("a", once_modifier=5)]
    cleaned = ts.TurnSpeedOrder().end_round(units)
    assert cleaned[0]["once_modifier"] == 0


def test_loading_order_does_not_change_result():
    a = [unit("a", speed=5), unit("b", speed=5)]
    b = list(reversed(a))
    assert order(a) == order(b)


def test_round_limit_is_enforced():
    with pytest.raises(ValueError):
        ts.TurnSpeedOrder(max_rounds=2).order([unit("a")], round_no=3)


def test_side_order_is_stable_between_rounds():
    units = [unit("e", side="enemy", speed=5), unit("a", side="ally", speed=5)]
    assert order(units)["order"] == order(list(reversed(units)))["order"]


def test_reasons_are_reported_for_each_step():
    result = order([unit("a", speed=10), unit("b", speed=5)])
    assert set(result["reasons"]) == {"a", "b"}
    assert all(isinstance(value, list) for value in result["reasons"].values())


def test_dead_and_left_units_are_skipped():
    result = order([unit("a", status="dead"), unit("b", status="left"), unit("c")])
    assert result["order"] == ["c"]
    assert set(result["skipped"]) == {"a", "b"}
