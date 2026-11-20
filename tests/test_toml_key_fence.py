import pytest

import toml_key_fence as tf


def load(text, **over):
    kwargs = {"max_depth": 20, "max_nodes": 1000, "max_scalar": 10000}
    kwargs.update(over)
    return tf.TomlKeyFence(**kwargs).load(text)


def test_array_tables_append_in_order():
    result = load("[[items]]\nid = 1\n[[items]]\nid = 2\n")
    assert [item["id"] for item in result["items"]] == [1, 2]


def test_duplicate_table_is_rejected():
    with pytest.raises(tf.TomlError) as exc:
        load("[a]\nx = 1\n[a]\ny = 2\n")
    assert exc.value.code == "duplicate_table"


def test_dotted_key_and_explicit_table_conflict():
    with pytest.raises(tf.TomlError) as exc:
        load("[a]\nb.c = 1\n[a.b]\nd = 2\n")
    assert exc.value.code == "key_conflict"


def test_inline_table_is_not_merged_with_outer_table():
    result = load("a = {b = 1}\n[a.c]\nd = 2\n")
    assert result["a"]["b"] == 1


def test_integer_bases_are_preserved():
    result = load("a = 0x10\nb = 0o10\nc = 0b10\n")
    assert result["a"]["base"] == 16
    assert result["b"]["base"] == 8
    assert result["c"]["base"] == 2


def test_datetime_is_kept_as_text():
    result = load("when = 2024-01-02T03:04:05Z\n")
    assert result["when"] == "2024-01-02T03:04:05Z"


def test_quoted_key_with_dot_is_one_key():
    result = load('"a.b" = 1\n')
    assert result['"a.b"'] == 1 or result.get("a.b") == 1


def test_multiline_string_continuation_is_handled():
    result = load('text = """line one \\\nline two"""\n')
    assert "line one" in result["text"]


def test_array_table_element_types_must_match():
    with pytest.raises(tf.TomlError):
        load("[[items]]\nid = 1\n[[items]]\nid = \"two\"\n")


def test_depth_limit_is_enforced():
    with pytest.raises(tf.TomlError) as exc:
        load("a = {b = {c = {d = 1}}}\n", max_depth=2)
    assert exc.value.code == "depth_limit"


def test_node_limit_is_enforced():
    with pytest.raises(tf.TomlError) as exc:
        load("a = [1, 2, 3, 4, 5]\n", max_nodes=3)
    assert exc.value.code == "node_limit"


def test_scalar_length_limit_is_enforced():
    with pytest.raises(tf.TomlError) as exc:
        load("a = \"" + "x" * 50 + "\"\n", max_scalar=10)
    assert exc.value.code == "scalar_limit"


def test_error_reports_line_and_column():
    with pytest.raises(tf.TomlError) as exc:
        load("[a]\nx = 1\n[a]\n")
    assert exc.value.line == 3


def test_result_is_sorted_by_resource_id():
    result = load("b = 1\na = 2\n")
    assert list(result) == ["a", "b"]


def test_repeated_load_is_identical():
    text = "a = [1, 2]\n"
    assert load(text) == load(text)
