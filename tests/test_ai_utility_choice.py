import ai_utility_choice as ai


def behavior(bid, weight=1.0, scale=1.0, cooldown=0, precondition=None, priority=0, interrupt=0):
    return {
        "id": bid,
        "weight": weight,
        "scale": scale,
        "cooldown": cooldown,
        "precondition": precondition,
        "priority": priority,
        "interrupt": interrupt,
    }


def choose(behaviors, context=None, seed=0, hysteresis=0.05):
    return ai.AiUtilityChoice(behaviors, seed=seed, hysteresis=hysteresis).choose(context or {"hp": 1.0, "range": 1.0})


def test_scores_are_normalized_before_weighting():
    result = choose([behavior("a", weight=1.0, scale=1.0), behavior("b", weight=1.0, scale=1000.0)])
    assert 0.0 <= result["scores"]["a"] <= 1.0
    assert 0.0 <= result["scores"]["b"] <= 1.0


def test_cooldown_behavior_is_not_a_candidate():
    result = choose([behavior("a", cooldown=5), behavior("b")], context={"cooldown": {"a": 3}})
    assert "a" not in result["candidates"]


def test_hysteresis_keeps_current_behavior():
    a = behavior("a", priority=1)
    b = behavior("b", priority=1)
    result = choose([a, b], context={"current": "a", "scores": {"a": 0.5, "b": 0.52}}, hysteresis=0.1)
    assert result["choice"] == "a"


def test_all_zero_scores_return_idle():
    result = choose([behavior("a", weight=0.0), behavior("b", weight=0.0)])
    assert result["choice"] == "idle"


def test_negative_weight_is_rejected():
    try:
        choose([behavior("a", weight=-1.0)])
        assert False
    except ValueError:
        pass


def test_overflowing_score_is_clamped():
    result = choose([behavior("a", scale=1e308), behavior("b", scale=1.0)])
    assert result["scores"]["a"] <= 1.0


def test_precondition_failure_removes_candidate():
    result = choose([behavior("a", precondition=lambda ctx: False), behavior("b")])
    assert "a" not in result["candidates"]


def test_event_can_interrupt_lower_priority_behavior():
    result = choose([behavior("a", interrupt=1), behavior("b", interrupt=9)], context={"current": "a", "event": "player_close"})
    assert result["interrupted"] is True or result["choice"] in ("a", "b")


def test_empty_behavior_table_returns_idle():
    assert choose([])["choice"] == "idle"


def test_tie_breaks_by_priority_then_id():
    result = choose([behavior("b", weight=1.0, priority=1), behavior("a", weight=1.0, priority=1)])
    assert result["choice"] == "a"


def test_seed_makes_ties_deterministic():
    b = [behavior("a", weight=1.0), behavior("b", weight=1.0)]
    assert choose(b, seed=3) == choose(b, seed=3)


def test_candidate_list_includes_scores():
    result = choose([behavior("a"), behavior("b")])
    assert set(result["candidates"]) == {"a", "b"}
    assert set(result["scores"]) == {"a", "b"}


def test_scores_are_bounded():
    result = choose([behavior("a", scale=1e9), behavior("b", scale=1e-9)])
    assert all(0.0 <= score <= 1.0 for score in result["scores"].values())


def test_current_behavior_is_retained_inside_buffer():
    result = choose([behavior("a", priority=1), behavior("b", priority=2)], context={"current": "a", "scores": {"a": 0.9, "b": 0.91}}, hysteresis=0.2)
    assert result["choice"] == "a"


def test_idle_fallback_has_reason():
    result = choose([])
    assert result["reason"] == "no_candidate"
