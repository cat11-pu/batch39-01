import pytest

import yaml_tag_fence as yt


def fence(**over):
    kwargs = {"max_depth": 20, "max_nodes": 1000, "max_scalar": 10000, "allow_merge": False}
    kwargs.update(over)
    return yt.YamlTagFence(**kwargs)


def test_alias_cycle_is_reported_with_anchor_name():
    with pytest.raises(yt.YamlTagError) as exc:
        fence().convert("a: &x\n  b: *x\n")
    assert exc.value.code == "anchor_cycle"
    assert exc.value.anchor == "x"


def test_alias_expansion_respects_node_limit():
    text = "a: &x [1, 2, 3]\nb: *x\nc: *x\nd: *x\n"
    with pytest.raises(yt.YamlTagError) as exc:
        fence(max_nodes=8).convert(text)
    assert exc.value.code == "node_limit"


def test_dangerous_construction_tag_is_rejected():
    with pytest.raises(yt.YamlTagError) as exc:
        fence().convert("a: !!python/object/apply:os.system ['echo hi']\n")
    assert exc.value.code == "unsupported_tag"
    assert exc.value.line == 1


def test_multi_document_conversion_returns_every_document():
    docs = fence().convert("a: 1\n---\nb: 2\n")
    assert docs == [{"a": 1}, {"b": 2}]


def test_invalid_second_document_rejects_the_whole_batch():
    with pytest.raises(yt.YamlTagError):
        fence().convert("a: 1\n---\nb: !!python/name:os.system\n")


def test_timestamp_scalar_stays_raw_text():
    result = fence().convert("when: 2024-01-02T03:04:05Z\n")[0]
    assert result["when"] == "2024-01-02T03:04:05Z"
    assert isinstance(result["when"], str)


def test_binary_tag_and_quoted_number_stay_text():
    result = fence().convert('data: !!binary aGVsbG8=\ncode: "007"\n')[0]
    assert result["data"] == "aGVsbG8="
    assert result["code"] == "007"
    assert isinstance(result["code"], str)


def test_null_is_present_while_missing_key_is_missing():
    result = fence().convert("a: null\nc: 1\n")[0]
    assert "a" in result and result["a"] is None
    assert result.get("b", yt.MISSING) is yt.MISSING


def test_duplicate_mapping_key_is_rejected():
    with pytest.raises(yt.YamlTagError) as exc:
        fence().convert("a: 1\na: 2\n")
    assert exc.value.code == "duplicate_key"


def test_nesting_depth_limit_is_enforced():
    text = "a:\n  b:\n    c:\n      d:\n        e: 1\n"
    with pytest.raises(yt.YamlTagError) as exc:
        fence(max_depth=3).convert(text)
    assert exc.value.code == "depth_limit"


def test_single_scalar_length_limit_is_enforced():
    text = "a: " + "x" * 60 + "\n"
    with pytest.raises(yt.YamlTagError) as exc:
        fence(max_scalar=20).convert(text)
    assert exc.value.code == "scalar_limit"


def test_error_reports_line_and_column():
    with pytest.raises(yt.YamlTagError) as exc:
        fence().convert("ok: 1\nbad: !!python/name:os.system\n")
    assert exc.value.line == 2
    assert exc.value.column >= 1


def test_event_stream_exposes_document_boundaries():
    events = list(fence().events("a: 1\nb: 2\n"))
    assert events[0] == ("document_start",)
    assert events[-1] == ("document_end",)
    assert ("scalar", "a") in events


def test_key_order_is_preserved_and_comments_are_dropped():
    result = fence().convert("# lead\nb: 2\na: 1\n# mid\nc: 3\n")[0]
    assert list(result) == ["b", "a", "c"]


def test_repeated_conversion_is_stable():
    text = "a: [1, 2]\nb: {c: 3}\n"
    assert fence().convert(text) == fence().convert(text)
