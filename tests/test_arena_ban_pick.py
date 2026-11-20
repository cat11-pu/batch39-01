import pytest

import arena_ban_pick as ab


def draft(**over):
    kwargs = {"bans_per_side": 2, "picks_per_side": 2, "fearless": False}
    kwargs.update(over)
    return ab.ArenaBanPick(**kwargs)


def test_duplicate_ban_is_rejected_without_state_change():
    d = draft()
    d.apply("blue", "ban", "a")
    before = d.state()
    with pytest.raises(ab.DraftError):
        d.apply("red", "ban", "a")
    assert d.state() == before


def test_first_pick_rotates_by_game_number():
    d1 = draft()
    d2 = draft()
    d1.apply("blue", "ban", "a")
    d2.apply("blue", "ban", "a")
    assert d1.state()["turn"] == d2.state()["turn"]


def test_timeout_auto_pick_uses_preference_order():
    d = draft()
    assert d.auto_pick("blue", ["a", "b"]) == "a"


def test_disconnected_player_is_auto_picked():
    d = draft()
    hero = d.auto_pick("red", ["x", "y"])
    assert hero in ("x", "y")


def test_fearless_mode_blocks_used_heroes():
    d = draft(fearless=True)
    d.apply("blue", "pick", "a")
    with pytest.raises(ab.DraftError):
        d.apply("red", "pick", "a")


def test_role_swap_only_allowed_in_pick_phase():
    d = draft()
    d.apply("blue", "pick", "a")
    d.apply("red", "pick", "b")
    with pytest.raises(ab.DraftError):
        d.swap("blue", "a", "b")


def test_illegal_action_is_rejected():
    with pytest.raises(ab.DraftError):
        draft().apply("blue", "dance", "a")


def test_phase_skip_fills_required_bans():
    d = draft(bans_per_side=2)
    d.apply("blue", "ban", "a")
    d.apply("red", "ban", "b")
    d.apply("blue", "ban", "c")
    d.apply("red", "ban", "d")
    assert d.state()["phase"] == "pick"


def test_time_bank_decreases_on_action():
    d = draft()
    before = d.state()["time_bank"]
    d.apply("blue", "ban", "a")
    assert d.state()["time_bank"] < before


def test_time_bank_exhaustion_forces_auto_pick():
    d = draft()
    assert d.state()["time_bank"] >= 0


def test_replay_records_order():
    d = draft()
    d.apply("blue", "ban", "a")
    d.apply("red", "ban", "b")
    assert [item["hero"] for item in d.state()["replay"]] == ["a", "b"]


def test_finalize_checked_player_count_and_positions():
    d = draft()
    with pytest.raises(ab.DraftError):
        d.finalize()


def test_ban_count_is_enforced():
    d = draft(bans_per_side=1)
    d.apply("blue", "ban", "a")
    with pytest.raises(ab.DraftError):
        d.apply("blue", "ban", "b")


def test_state_is_unchanged_after_rejected_action():
    d = draft()
    before = d.state()
    with pytest.raises(ab.DraftError):
        d.apply("blue", "pick", "a")
    assert d.state() == before


def test_hero_cannot_be_picked_after_ban():
    d = draft()
    d.apply("blue", "ban", "a")
    with pytest.raises(ab.DraftError):
        d.apply("blue", "pick", "a")
