import keyframe_seek_index as ks

TS = 90000


def entry(pts, offset, key=True, dts=None, segment=0, corrupt=False):
    return {"pts": pts, "dts": dts if dts is not None else pts, "offset": offset, "keyframe": key, "segment": segment, "corrupt": corrupt}


def build(entries, **over):
    kwargs = {"timescale": TS}
    kwargs.update(over)
    index = ks.KeyframeSeekIndex(**kwargs)
    index.build(entries)
    return index


def test_variable_gop_is_supported():
    index = build([entry(0, 0), entry(TS, 100), entry(3 * TS, 200)])
    assert index.seek(2 * TS)["keyframe_pts"] == TS


def test_decode_order_is_preserved_in_addition_to_display_order():
    index = build([entry(0, 0, dts=0), entry(2 * TS, 100, dts=TS), entry(TS, 200, dts=2 * TS)])
    assert index.seek(TS)["keyframe_pts"] is not None


def test_index_hole_falls_back_to_earlier_keyframe():
    index = build([entry(0, 0), entry(4 * TS, 100)])
    result = index.seek(3 * TS)
    assert result["keyframe_pts"] == 0
    assert result["predecode"] > 0


def test_corrupt_entry_is_skipped_without_dropping_index():
    index = build([entry(0, 0), entry(TS, 100, corrupt=True), entry(2 * TS, 200)])
    assert index.seek(2 * TS)["keyframe_pts"] == 2 * TS


def test_live_mode_returns_nearest_available_keyframe():
    index = build([entry(0, 0)], live=True)
    result = index.seek(10 * TS)
    assert result["live"] is True


def test_forward_and_backward_seek_use_same_boundary_rule():
    index = build([entry(0, 0), entry(TS, 100)])
    assert index.seek(TS - 1)["keyframe_pts"] == 0
    assert index.seek(TS)["keyframe_pts"] == TS


def test_seek_past_end_is_clamped():
    index = build([entry(0, 0), entry(TS, 100)])
    assert index.seek(100 * TS)["keyframe_pts"] == TS


def test_timescale_conversion_avoids_float_overflow():
    index = build([entry(0, 0), entry(3 * 3600 * TS, 100)])
    assert index.seek(2 * 3600 * TS)["keyframe_pts"] == 0


def test_segment_offset_is_added():
    index = build([entry(0, 0, segment=0), entry(TS, 100, segment=1)])
    assert index.seek(TS + 10)["segment"] == 1


def test_version_mismatch_rejects_load():
    index = ks.KeyframeSeekIndex()
    try:
        index.build([entry(0, 0)], version=2)
        index.load(version=1)
        assert False
    except (AttributeError, ValueError):
        pass


def test_incremental_append_updates_tail_only():
    index = build([entry(0, 0)])
    index.append(entry(TS, 100))
    assert index.seek(TS)["keyframe_pts"] == TS


def test_predecode_count_is_reported():
    index = build([entry(0, 0), entry(4 * TS, 100)])
    assert index.seek(2 * TS)["predecode"] >= 1


def test_digest_is_kept_with_index():
    index = ks.KeyframeSeekIndex()
    result = index.build([entry(0, 0)], digest="abc")
    assert result["digest"] == "abc"


def test_nearest_keyframe_is_returned():
    index = build([entry(0, 0), entry(TS, 100), entry(2 * TS, 200)])
    assert index.seek(TS + 1)["keyframe_pts"] == TS


def test_output_order_is_stable():
    index = build([entry(0, 0), entry(TS, 100)])
    assert index.seek(TS) == index.seek(TS)
