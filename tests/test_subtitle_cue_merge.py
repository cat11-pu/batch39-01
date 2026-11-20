import subtitle_cue_merge as sc


def cue(start, end, text="hello", style="default", speaker=None, index=0):
    return {"start": start, "end": end, "text": text, "style": style, "speaker": speaker, "index": index}


def merge(cues, **over):
    fps = over.pop("fps", 25)
    kwargs = {"min_duration": 1000, "gap": 100, "max_chars": 42, "cps": 15}
    kwargs.update(over)
    return sc.SubtitleCueMerge(**kwargs).merge(cues, fps=fps)


def test_overlapping_cues_are_merged():
    result = merge([cue(0, 2000, "a"), cue(1000, 3000, "b")])
    assert len(result["cues"]) == 1


def test_short_gap_is_merged():
    result = merge([cue(0, 1000, "a"), cue(1050, 2000, "b")])
    assert len(result["cues"]) == 1


def test_min_duration_extends_short_cue():
    result = merge([cue(0, 200, "a")])
    assert result["cues"][0]["end"] >= 1000


def test_long_line_is_wrapped_at_width():
    result = merge([cue(0, 3000, "x" * 80)], max_chars=20)
    assert "\n" in result["cues"][0]["text"]


def test_reading_speed_warning_is_emitted():
    result = merge([cue(0, 500, "这是一个很长的句子用来测试阅读速度")], cps=5)
    assert result["warnings"]


def test_frame_numbers_are_converted_with_fps():
    item = cue(0, 0)
    item["start_frame"] = 25
    item["end_frame"] = 50
    result = merge([item], fps=25)
    assert result["cues"][0]["start"] == 1000


def test_unsorted_cues_are_sorted():
    result = merge([cue(3000, 4000, "b"), cue(0, 1000, "a")])
    assert result["cues"][0]["start"] == 0


def test_zero_duration_is_dropped():
    result = merge([cue(1000, 1000, "a")])
    assert result["cues"] == []


def test_negative_duration_is_dropped():
    result = merge([cue(2000, 1000, "a")])
    assert result["cues"] == []


def test_speaker_change_prevents_merge():
    result = merge([cue(0, 2000, "a", speaker="A"), cue(1000, 3000, "b", speaker="B")])
    assert len(result["cues"]) == 2


def test_style_conflict_prevents_merge_and_is_flagged():
    result = merge([cue(0, 2000, "a", style="red"), cue(1000, 3000, "b", style="blue")])
    assert len(result["cues"]) == 2
    assert result["conflicts"]


def test_duplicate_import_is_deduplicated():
    result = merge([cue(0, 1000, "a"), cue(0, 1000, "a")])
    assert len(result["cues"]) == 1


def test_output_is_stably_sorted():
    result = merge([cue(5000, 6000, "c"), cue(0, 1000, "a"), cue(2000, 3000, "b")])
    assert [item["start"] for item in result["cues"]] == [0, 2000, 5000]


def test_all_warnings_are_returned():
    result = merge([cue(0, 200, "x" * 100)], max_chars=10, cps=1)
    assert len(result["warnings"]) >= 1


def test_original_index_mapping_is_preserved():
    result = merge([cue(0, 1000, "a", index=7)])
    assert result["cues"][0]["source_index"] == 7
