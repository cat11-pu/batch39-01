import pytest

import particle_curve_bake as pc


def key(t, v, ease="linear", cp=None):
    return {"t": t, "v": v, "ease": ease, "cp": cp or []}


def bake(keys, duration=10.0, loop=False, quality="high", value_range=(0.0, 1.0), fps=60):
    curve = pc.ParticleCurveBake(quality=quality, value_range=value_range)
    result = curve.bake(keys, duration, loop=loop, fps=fps)
    return curve, result


def test_unsorted_keys_are_sorted_by_time():
    _, result = bake([key(5, 0.9), key(0, 0.1), key(2, 0.5)])
    assert result["times"] == [0, 2, 5]


def test_duplicate_time_uses_last_key():
    curve, _ = bake([key(1, 0.2), key(1, 0.8)], duration=2)
    assert curve.sample(1) == 0.8


def test_loop_seam_is_continuous():
    curve, _ = bake([key(0, 0.2), key(10, 0.2)], duration=10, loop=True)
    assert curve.sample(0) == pytest.approx(curve.sample(10))


def test_linear_midpoint():
    curve, _ = bake([key(0, 0.0), key(10, 1.0)], duration=10)
    assert curve.sample(5) == pytest.approx(0.5)


def test_ease_in_starts_slower_than_linear():
    lin, _ = bake([key(0, 0.0), key(10, 1.0)], duration=10)
    ease, _ = bake([key(0, 0.0), key(10, 1.0, "in")], duration=10)
    assert ease.sample(2) < lin.sample(2)


def test_ease_out_starts_faster_than_linear():
    lin, _ = bake([key(0, 0.0), key(10, 1.0)], duration=10)
    ease, _ = bake([key(0, 0.0), key(10, 1.0, "out")], duration=10)
    assert ease.sample(2) > lin.sample(2)


def test_custom_control_points_are_used():
    curve, _ = bake([key(0, 0.0), key(10, 1.0, "custom", [0.8, 0.2])], duration=10)
    assert 0.0 <= curve.sample(5) <= 1.0


def test_low_quality_has_fewer_samples_but_keeps_endpoints():
    _, high = bake([key(0, 0.0), key(10, 1.0)], duration=10, quality="high")
    _, low = bake([key(0, 0.0), key(10, 1.0)], duration=10, quality="low")
    assert low["samples"] < high["samples"]
    assert low["times"][0] == 0 and low["times"][-1] == 10


def test_prewarm_uses_first_value_before_time_zero():
    curve, _ = bake([key(0, 0.3), key(10, 1.0)], duration=10)
    assert curve.sample(-5) == pytest.approx(0.3)


def test_values_are_clamped_to_configured_range():
    curve, _ = bake([key(0, -3.0), key(10, 4.0)], duration=10)
    assert curve.sample(0) == 0.0
    assert curve.sample(10) == 1.0


def test_reverse_time_wraps_in_loop_mode():
    curve, _ = bake([key(0, 0.0), key(10, 1.0)], duration=10, loop=True)
    assert curve.sample(-1) == pytest.approx(curve.sample(9))


def test_sample_times_are_strictly_sorted():
    _, result = bake([key(0, 0.0), key(10, 1.0)], duration=10)
    assert result["times"] == sorted(result["times"])
    assert len(result["times"]) == len(set(result["times"]))


def test_low_quality_keeps_extreme_values():
    _, result = bake([key(0, 0.0), key(4, 1.0), key(8, 0.0)], duration=8, quality="low")
    assert max(result["values"]) == pytest.approx(1.0)


def test_baked_result_is_marked_read_only():
    _, result = bake([key(0, 0.0), key(10, 1.0)], duration=10)
    assert result["readonly"] is True


def test_repeated_bake_is_identical():
    keys = [key(0, 0.0), key(5, 0.5), key(10, 1.0)]
    _, first = bake(keys, duration=10)
    _, second = bake(keys, duration=10)
    assert first == second
