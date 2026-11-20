import buff_stack_policy as bs


def target():
    return {"id": "mob-1", "stats": {"attack": 10}, "events": [], "buffs": {}}


def policy(**over):
    kwargs = {"max_stacks": 5, "max_sources": 3}
    kwargs.update(over)
    return bs.BuffStackPolicy(**kwargs)


def test_two_sources_stack_independently():
    p = policy()
    t = target()
    p.apply(t, "might", "potion", mode="independent", duration=10)
    p.apply(t, "might", "aura", mode="independent", duration=10)
    assert p.stats(t)["stacks"]["might"] == 2


def test_stack_limit_is_enforced():
    p = policy(max_stacks=2)
    t = target()
    for source in ("a", "b", "c"):
        p.apply(t, "might", source, mode="independent", duration=10)
    assert p.stats(t)["stacks"]["might"] == 2


def test_extend_mode_uses_remaining_time_plus_delta():
    p = policy()
    t = target()
    p.apply(t, "haste", "a", mode="extend", duration=10, now=0)
    p.apply(t, "haste", "a", mode="extend", duration=10, now=5)
    assert p.stats(t)["remaining"]["haste"] == 15


def test_dispel_removes_lowest_priority_first_and_skips_undispellable():
    p = policy()
    t = target()
    p.apply(t, "core", "passive", priority=10, dispellable=False)
    p.apply(t, "minor", "curse", priority=1)
    removed = p.dispel(t, priority=5)
    assert removed == ["minor"]
    assert "core" in p.stats(t)["buffs"]


def test_immunity_blocks_application_but_records_attempt():
    p = policy()
    t = target()
    t["immune"] = True
    result = p.apply(t, "poison", "trap")
    assert result["applied"] is False
    assert result["attempted"] is True


def test_stats_are_recalculated_when_stacks_change():
    p = policy()
    t = target()
    p.apply(t, "might", "a", mode="independent")
    before = p.stats(t)["attack"]
    p.apply(t, "might", "b", mode="independent")
    after = p.stats(t)["attack"]
    assert after != before


def test_expiry_event_fires_once():
    p = policy()
    t = target()
    p.apply(t, "haste", "a", duration=5, now=0)
    p.tick(t, 6)
    p.tick(t, 7)
    assert t["events"].count("haste_expired") == 1


def test_time_rollback_does_not_revive_expired_buff():
    p = policy()
    t = target()
    p.apply(t, "haste", "a", duration=5, now=0)
    p.tick(t, 6)
    p.tick(t, 1)
    assert "haste" not in p.stats(t)["buffs"]


def test_same_frame_apply_and_remove_keeps_event_order():
    p = policy()
    t = target()
    p.apply(t, "haste", "a", duration=5, now=0)
    p.remove(t, "haste", "a")
    assert t["events"][-1] == "haste_removed"


def test_same_id_different_sources_are_kept_separate():
    p = policy()
    t = target()
    p.apply(t, "might", "a", mode="independent")
    p.apply(t, "might", "b", mode="independent")
    assert set(p.stats(t)["sources"]["might"]) == {"a", "b"}


def test_replace_mode_drops_previous_source():
    p = policy()
    t = target()
    p.apply(t, "stance", "old", mode="replace")
    p.apply(t, "stance", "new", mode="replace")
    assert p.stats(t)["sources"]["stance"] == ["new"]


def test_source_limit_is_enforced():
    p = policy(max_sources=1)
    t = target()
    p.apply(t, "might", "a", mode="independent")
    p.apply(t, "might", "b", mode="independent")
    assert len(p.stats(t)["sources"]["might"]) == 1


def test_remove_and_reapply_does_not_duplicate_events():
    p = policy()
    t = target()
    p.apply(t, "haste", "a")
    p.remove(t, "haste", "a")
    p.apply(t, "haste", "a")
    assert t["events"].count("haste_applied") == 2


def test_snapshot_before_and_after_are_reported():
    p = policy()
    t = target()
    result = p.apply(t, "might", "a")
    assert "before" in result and "after" in result


def test_different_buff_ids_are_independent():
    p = policy()
    t = target()
    p.apply(t, "a", "x")
    p.remove(t, "b", "x")
    assert "a" in p.stats(t)["buffs"]
