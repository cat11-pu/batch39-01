import pytest

import waveform_peak_index as wp


def idx(**over):
    kwargs = {"bucket": 1000, "silence": 1e-4, "max_levels": 8, "memory_cap": 1000000}
    kwargs.update(over)
    return wp.WaveformPeakIndex(**kwargs)


def test_multiple_resolution_levels_are_built():
    result = idx().build([0.5] * 8000)
    assert result["levels"] >= 2


def test_each_bucket_keeps_min_and_max():
    result = idx(bucket=4).build([0.1, -0.9, 0.3, 0.2])
    level = result["buckets"][0]
    assert level["min"] <= -0.9
    assert level["max"] >= 0.3


def test_silence_is_marked():
    result = idx(bucket=4, silence=1e-3).build([0.0, 0.0, 0.0, 0.0])
    assert result["silent"] is True


def test_stereo_channels_are_stored_separately():
    result = idx(bucket=2).build([0.5, -0.5, 0.1, 0.1], channels=2)
    assert result["channels"] == 2


def test_twenty_four_bit_packed_samples_are_supported():
    result = idx(bucket=2, bits=24).build([0.5, -0.5], bits=24)
    assert result["bits"] == 24


def test_incremental_update_aligns_to_bucket_boundary():
    index = idx(bucket=4)
    index.build([0.1] * 8)
    result = index.update([0.9] * 4, start=8)
    assert result["aligned"] is True


def test_tail_bucket_is_preserved():
    result = idx(bucket=4).build([0.1] * 10)
    assert result["tail"] is True


def test_empty_file_returns_empty_index():
    result = idx().build([])
    assert result["buckets"] == []


def test_single_sample_is_indexed():
    result = idx(bucket=4).build([0.7])
    assert len(result["buckets"]) == 1


def test_memory_cap_evicts_old_zoom_levels():
    result = idx(memory_cap=10, max_levels=8).build([0.1] * 100000)
    assert result["evicted"] >= 1


def test_levels_are_built_by_pairwise_merge():
    result = idx(bucket=2).build([0.1, 0.2, 0.3, 0.4])
    assert result["levels"] >= 2


def test_source_digest_is_recorded():
    result = idx().build([0.1] * 10)
    assert "digest" in result


def test_checksum_is_reproducible():
    a = idx().build([0.1] * 10)
    b = idx().build([0.1] * 10)
    assert a["checksum"] == b["checksum"]


def test_opposite_stereo_phase_is_flagged():
    result = idx(bucket=2).build([0.5, -0.5, 0.5, -0.5], channels=2)
    assert result["phase_cancel"] is True


def test_zoom_cache_is_isolated_per_level():
    index = idx(bucket=2)
    result = index.build([0.1] * 8)
    assert len(result["cache"]) == result["levels"]
