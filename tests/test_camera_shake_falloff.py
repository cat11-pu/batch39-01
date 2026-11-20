import pytest

import camera_shake_falloff as cs


def shake(**over):
    kwargs = {"decay": 1.5, "max_trauma": 1.0, "aim_scale": 0.5, "seed": 7}
    kwargs.update(over)
    return cs.CameraShakeFalloff(**kwargs)


def test_multiple_sources_use_squared_sum_and_clamp():
    s = shake()
    s.add("rifle", 0.6)
    s.add("explosion", 0.6)
    result = s.update(0.0)
    assert result["trauma"] <= 1.0
    assert result["trauma"] == pytest.approx(0.72)


def test_trauma_decays_per_second():
    s = shake(decay=2.0)
    s.add("hit", 1.0)
    assert s.update(0.1)["trauma"] == pytest.approx(0.8)


def test_low_frame_rate_uses_substeps():
    a = shake()
    a.add("hit", 1.0, frequency=2.0)
    b = shake()
    b.add("hit", 1.0, frequency=2.0)
    one = a.update(0.2)
    many = [b.update(0.05) for _ in range(4)]
    assert one["trauma"] == pytest.approx(many[-1]["trauma"])


def test_same_seed_produces_same_sequence():
    a = shake(seed=11)
    b = shake(seed=11)
    for s in (a, b):
        s.add("hit", 1.0, frequency=3.0)
    first = [a.update(0.01)["offset"] for _ in range(5)]
    second = [b.update(0.01)["offset"] for _ in range(5)]
    assert first == second


def test_pause_freezes_time_and_trauma():
    s = shake()
    s.add("hit", 1.0)
    before = s.update(0.0)
    paused = s.update(0.5, paused=True)
    assert paused["trauma"] == before["trauma"]


def test_three_axes_are_independent():
    s = shake()
    s.add("hit", 1.0, axis=(1.0, 0.0, 0.0))
    result = s.update(0.01)
    assert result["offset"] != (0, 0)
    assert result["rotation"] == 0


def test_aiming_scales_offset_down():
    a = shake()
    b = shake()
    for s in (a, b):
        s.add("hit", 1.0)
    normal = a.update(0.01)
    aimed = b.update(0.01, aim=True)
    assert abs(aimed["offset"][0]) <= abs(normal["offset"][0])


def test_ui_is_not_affected_by_shake():
    s = shake()
    s.add("hit", 1.0)
    result = s.update(0.01)
    assert result["ui_offset"] == (0, 0)


def test_source_expires_after_duration():
    s = shake(decay=0.0)
    s.add("hit", 1.0, duration=0.05)
    s.update(0.1)
    assert s.update(0.0)["trauma"] == 0.0


def test_new_source_does_not_replace_old_trauma():
    s = shake(decay=0.0)
    s.add("rifle", 0.2)
    s.add("explosion", 0.5)
    assert s.update(0.0)["trauma"] == pytest.approx(0.29)


def test_zero_strength_is_ignored():
    s = shake()
    s.add("none", 0.0)
    assert s.update(0.0)["trauma"] == 0.0


def test_negative_strength_is_rejected():
    with pytest.raises(ValueError):
        shake().add("bad", -1.0)


def test_large_dt_is_split_into_substeps():
    s = shake(decay=1.0)
    s.add("hit", 1.0, duration=10.0)
    assert s.update(2.0)["trauma"] == pytest.approx(0.0, abs=1e-6)


def test_different_seed_produces_different_offsets():
    a = shake(seed=1)
    b = shake(seed=2)
    for s in (a, b):
        s.add("hit", 1.0, frequency=5.0)
    assert a.update(0.02)["offset"] != b.update(0.02)["offset"]


def test_snapshot_reports_trauma_and_sources():
    s = shake()
    s.add("hit", 0.4)
    snap = s.snapshot()
    assert "trauma" in snap and "sources" in snap
