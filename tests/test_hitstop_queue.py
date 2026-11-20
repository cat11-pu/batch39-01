import hitstop_queue as hq


def queue(**over):
    kwargs = {"max_duration": 0.5, "min_scale": 0.05}
    kwargs.update(over)
    return hq.HitstopQueue(**kwargs)


def test_stacked_hits_are_clamped_to_max_duration():
    q = queue(max_duration=0.2)
    for _ in range(5):
        q.add("hit", 1.0, 1, 0.2)
    assert q.update(0.0)["remaining"] <= 0.2


def test_higher_priority_wins_same_frame():
    q = queue()
    q.add("light", 1.0, 1, 0.1)
    q.add("heavy", 2.0, 9, 0.2)
    state = q.update(0.0)
    assert state["source"] == "heavy"


def test_lower_priority_does_not_override():
    q = queue()
    q.add("heavy", 1.0, 9, 0.2)
    q.add("light", 5.0, 1, 0.1)
    assert q.update(0.0)["source"] == "heavy"


def test_time_scale_never_reaches_zero():
    q = queue(min_scale=0.05)
    q.add("hit", 1.0, 1, 0.5)
    assert q.update(0.0)["time_scale"] >= 0.05


def test_ui_audio_camera_keep_normal_scale():
    q = queue()
    q.add("hit", 1.0, 1, 0.2)
    state = q.update(0.0)
    assert state["ui_scale"] == 1.0
    assert state["audio_scale"] == 1.0


def test_pause_freezes_remaining_time():
    q = queue()
    q.add("hit", 1.0, 1, 0.2)
    before = q.update(0.0)["remaining"]
    after = q.update(1.0, paused=True)["remaining"]
    assert before == after


def test_large_dt_is_substepped():
    q = queue()
    q.add("hit", 1.0, 1, 0.2)
    assert q.update(1.0)["remaining"] == 0.0


def test_overkill_hit_can_be_ignored():
    q = queue()
    q.add("overkill", 5.0, 1, 0.5, ignore=True)
    assert q.update(0.0)["remaining"] == 0.0


def test_immune_target_ignores_hitstop():
    q = queue()
    q.add("boss", 5.0, 1, 0.5, ignore=True)
    assert q.update(0.0)["active"] is False


def test_invulnerable_dash_ignores_hitstop():
    q = queue()
    q.add("dash", 5.0, 1, 0.5, ignore=True)
    assert q.update(0.0)["active"] is False


def test_expired_requests_are_pruned():
    q = queue()
    q.add("old", 1.0, 1, 0.1, now=0.0)
    q.update(1.0)
    assert q.update(0.0)["pending"] == 0


def test_same_frame_requests_merge_source_list():
    q = queue()
    q.add("a", 1.0, 1, 0.1)
    q.add("b", 1.0, 2, 0.1)
    assert set(q.update(0.0)["sources"]) == {"a", "b"}


def test_output_reports_current_scale_remaining_and_source():
    q = queue()
    q.add("hit", 1.0, 1, 0.1)
    result = q.update(0.0)
    assert {"time_scale", "remaining", "source"} <= set(result)


def test_recovery_is_smooth():
    q = queue()
    q.add("hit", 1.0, 1, 0.1)
    q.update(0.05)
    first = q.update(0.02)["time_scale"]
    second = q.update(0.02)["time_scale"]
    assert second >= first


def test_scene_switch_clears_queue():
    q = queue()
    q.add("hit", 1.0, 1, 0.5)
    q.clear_scene()
    assert q.update(0.0)["active"] is False
