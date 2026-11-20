import pytest

import audio_resample_plan as ar


def resampler(in_rate=44100, out_rate=48000, **over):
    kwargs = {"channels": 1, "filter_len": 32, "bits": 16}
    kwargs.update(over)
    return ar.AudioResamplePlan(in_rate, out_rate, **kwargs)


def test_non_integer_ratio_is_reduced_by_gcd():
    plan = resampler().plan(44100)
    assert plan["ratio"] == (147, 160)


def test_block_sizes_are_reported():
    plan = resampler().plan(44100)
    assert plan["blocks"] > 0
    assert plan["in_per_block"] > 0


def test_multichannel_is_planned_per_channel():
    plan = resampler(channels=2).plan(44100)
    assert plan["channels"] == 2


def test_total_output_samples_match_theory():
    plan = resampler().plan(44100)
    assert plan["total_out"] == 48000


def test_integer_output_is_clamped_before_conversion():
    result = resampler().execute([2.0, -2.0, 0.0])
    assert all(-32768 <= value <= 32767 for value in result["samples"])


def test_phase_remainder_is_passed_between_blocks():
    plan = resampler().plan(1000)
    assert "remainder" in plan


def test_same_rate_passes_through_without_filtering():
    plan = resampler(in_rate=48000, out_rate=48000).plan(1000)
    assert plan["passthrough"] is True


def test_zero_rate_is_rejected():
    with pytest.raises(ValueError):
        resampler(in_rate=0)


def test_negative_rate_is_rejected():
    with pytest.raises(ValueError):
        resampler(out_rate=-48000)


def test_channel_change_requires_mix_matrix():
    with pytest.raises(ValueError):
        resampler(channels=1).plan(1000, mix=None)


def test_filter_length_scales_with_transition():
    short = resampler(filter_len=16).plan(1000)
    long = resampler(filter_len=64).plan(1000)
    assert long["latency"] >= short["latency"]


def test_drift_does_not_accumulate_over_ten_minutes():
    plan = resampler().plan(44100 * 600)
    assert plan["total_out"] == 48000 * 600


def test_tail_padding_is_reported():
    plan = resampler().plan(12345)
    assert "tail_pad" in plan


def test_plan_contains_required_fields():
    plan = resampler().plan(44100)
    for key in ("ratio", "blocks", "in_per_block", "out_per_block", "total_out", "latency"):
        assert key in plan


def test_blocked_execution_matches_one_shot():
    signal = [0.1] * 2000
    a = resampler().execute(signal, block=256)
    b = resampler().execute(signal, block=100000)
    assert abs(a["total_out"] - b["total_out"]) <= 1
