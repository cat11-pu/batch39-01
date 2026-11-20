import pytest

import crlf_header_fence as hf


def fence(**over):
    kwargs = {"allowed_hosts": ("shop.example.com",), "max_headers": 50, "max_value": 4096, "max_total": 16384}
    kwargs.update(over)
    return hf.CrlfHeaderFence(**kwargs)


def pairs(headers):
    return list(headers)


def test_carriage_return_in_value_is_rejected():
    with pytest.raises(hf.HeaderError) as exc:
        fence().build([("X-Test", "a\r\nX-Evil: 1")])
    assert exc.value.code == "invalid_value"


def test_folded_value_is_unfolded_before_validation():
    result = pairs(fence().build([("X-Test", "a\r\n b")]))
    assert result == [("x-test", "a b")]


def test_unicode_line_separator_is_rejected():
    with pytest.raises(hf.HeaderError) as exc:
        fence().build([("X-Test", "a\u2028b")])
    assert exc.value.code == "invalid_value"


def test_duplicate_names_merge_case_insensitively():
    result = pairs(fence().build([("X-Test", "a"), ("x-test", "b")]))
    assert result == [("x-test", "a, b")]


def test_surrounding_whitespace_is_trimmed():
    result = pairs(fence().build([("X-Test", "  a  ")]))
    assert result == [("x-test", "a")]


def test_non_ascii_filename_gets_compatible_encoding():
    result = pairs(fence().build([], filename="报告.pdf"))
    disposition = [value for name, value in result if name == "content-disposition"][0]
    assert "filename*=UTF-8''" in disposition


def test_hop_by_hop_header_is_not_forwarded():
    result = pairs(fence().build([("Connection", "keep-alive"), ("Transfer-Encoding", "chunked")]))
    assert result == []


def test_external_location_is_rejected():
    with pytest.raises(hf.HeaderError) as exc:
        fence().build([], location="https://evil.net/x")
    assert exc.value.code == "unsafe_location"


def test_empty_value_is_kept_while_missing_header_is_absent():
    result = pairs(fence().build([("X-Empty", "")]))
    assert result == [("x-empty", "")]
    assert all(name != "x-missing" for name, value in result)


def test_invalid_header_name_is_rejected():
    with pytest.raises(hf.HeaderError) as exc:
        fence().build([("Bad Name", "x")])
    assert exc.value.code == "invalid_name"


def test_header_count_limit_is_enforced():
    with pytest.raises(hf.HeaderError) as exc:
        fence(max_headers=1).build([("X-A", "1"), ("X-B", "2")])
    assert exc.value.code == "too_many_headers"


def test_multiple_set_cookie_headers_are_preserved():
    result = pairs(fence().build([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")]))
    assert [value for name, value in result if name == "set-cookie"] == ["a=1", "b=2"]


def test_colon_inside_value_is_not_a_separator():
    result = pairs(fence().build([("X-Test", "a:b")]))
    assert result == [("x-test", "a:b")]


def test_single_value_length_limit_is_enforced():
    with pytest.raises(hf.HeaderError) as exc:
        fence(max_value=4).build([("X-Test", "abcde")])
    assert exc.value.code == "value_too_long"


def test_output_order_is_stable():
    result = pairs(fence().build([("X-B", "2"), ("X-A", "1")]))
    assert result == [("x-b", "2"), ("x-a", "1")]
