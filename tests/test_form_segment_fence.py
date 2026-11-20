import hashlib

import pytest

import form_segment_fence as fs

B = "----resume42"


def part(name, filename=None, data=b"x", content_type=None, extra_headers=()):
    headers = [
        'Content-Disposition: form-data; name="%s"' % name
        + ('' if filename is None else '; filename="%s"' % filename)
    ]
    if content_type:
        headers.append("Content-Type: " + content_type)
    headers.extend(extra_headers)
    return b"\r\n".join(h.encode("utf-8") for h in headers) + b"\r\n\r\n" + data


def make_body(parts, boundary=B, close=True):
    out = b""
    for item in parts:
        out += b"--" + boundary.encode() + b"\r\n" + item + b"\r\n"
    if close:
        out += b"--" + boundary.encode() + b"--\r\n"
    return out


def ctype(boundary=B, quoted=False):
    if quoted:
        return 'multipart/form-data; boundary=" %s "' % boundary
    return "multipart/form-data; boundary=" + boundary


def test_duplicate_field_name_is_rejected():
    body = make_body([part("resume", "a.pdf", b"a"), part("resume", "b.pdf", b"b")])
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence().parse(body, ctype())
    assert exc.value.code == "duplicate_field"
    assert exc.value.field == "resume"


def test_path_separators_in_filename_are_rejected():
    for name in ("../secret.pdf", "..\secret.pdf", "dir/cv.pdf"):
        with pytest.raises(fs.FormSegmentError) as exc:
            fs.FormSegmentFence().parse(make_body([part("f", name, b"x")]), ctype())
        assert exc.value.code == "invalid_filename"


def test_control_characters_in_filename_are_rejected():
    for name in ("cv\x00.pdf", "cv\n.pdf"):
        with pytest.raises(fs.FormSegmentError) as exc:
            fs.FormSegmentFence().parse(make_body([part("f", name, b"x")]), ctype())
        assert exc.value.code == "invalid_filename"


def test_quoted_boundary_with_spaces_is_accepted():
    body = make_body([part("note", None, b"hello")])
    result = fs.FormSegmentFence().parse(body, ctype(quoted=True))
    assert len(result) == 1
    assert result[0]["name"] == "note"


def test_folded_header_is_unfolded_before_parsing():
    raw = (
        b"--" + B.encode() + b"\r\n"
        b"Content-Disposition: form-data;\r\n"
        b' name="report"; filename="cv.pdf"\r\n'
        b"\r\nPDF\r\n--" + B.encode() + b"--\r\n"
    )
    result = fs.FormSegmentFence().parse(raw, ctype())
    assert result[0]["name"] == "report"
    assert result[0]["filename"] == "cv.pdf"


def test_bare_newline_inside_header_value_is_rejected():
    raw = (
        b"--" + B.encode() + b"\r\n"
        b'Content-Disposition: form-data; name="a"\r\n'
        b"X-Note: ok\nX-Evil: 1\r\n"
        b"\r\nx\r\n--" + B.encode() + b"--\r\n"
    )
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence().parse(raw, ctype())
    assert exc.value.code == "invalid_header"


def test_missing_closing_boundary_is_truncated():
    body = make_body([part("a", None, b"x")], close=False)
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence().parse(body, ctype())
    assert exc.value.code == "truncated"


def test_segment_count_limit_is_enforced():
    body = make_body([part("a", None, b"1"), part("b", None, b"2"), part("c", None, b"3")])
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence(max_segments=2).parse(body, ctype())
    assert exc.value.code == "too_many_segments"


def test_single_segment_size_limit_is_enforced():
    body = make_body([part("a", None, b"12345")])
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence(max_segment_bytes=4).parse(body, ctype())
    assert exc.value.code == "segment_too_large"


def test_total_request_size_limit_is_enforced():
    body = make_body([part("a", None, b"x" * 100)])
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence(max_total_bytes=64).parse(body, ctype())
    assert exc.value.code == "request_too_large"


def test_header_line_limit_is_enforced():
    body = make_body([part("a", None, b"x", extra_headers=["X-A: 1", "X-B: 2", "X-C: 3"])])
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence(max_header_lines=2).parse(body, ctype())
    assert exc.value.code == "too_many_headers"


def test_manifest_keeps_order_and_reports_size_and_digest():
    body = make_body([part("first", "a.txt", b"alpha"), part("second", None, b"beta")])
    result = fs.FormSegmentFence().parse(body, ctype())
    assert [item["name"] for item in result] == ["first", "second"]
    assert result[0]["filename"] == "a.txt"
    assert [item["size"] for item in result] == [5, 4]
    assert result[0]["digest"] == hashlib.sha256(b"alpha").hexdigest()
    assert result[1]["digest"] == hashlib.sha256(b"beta").hexdigest()


def test_empty_filename_is_preserved_as_empty_string():
    body = make_body([part("f", "", b"x")])
    result = fs.FormSegmentFence().parse(body, ctype())
    assert result[0]["filename"] == ""


def test_invalid_utf8_in_header_is_rejected():
    raw = b"--" + B.encode() + b"\r\n"
    raw += b'Content-Disposition: form-data; name="' + b"\xff\xfe" + b'"\r\n\r\nx\r\n'
    raw += b"--" + B.encode() + b"--\r\n"
    with pytest.raises(fs.FormSegmentError) as exc:
        fs.FormSegmentFence().parse(raw, ctype())
    assert exc.value.code == "invalid_encoding"


def test_returned_manifest_is_detached_and_repeat_parse_is_stable():
    body = make_body([part("a", "a.txt", b"alpha")])
    fence = fs.FormSegmentFence()
    first = fence.parse(body, ctype())
    first[0]["digest"] = "0" * 64
    first[0]["filename"] = "changed"
    second = fence.parse(body, ctype())
    assert second[0]["digest"] == hashlib.sha256(b"alpha").hexdigest()
    assert second[0]["filename"] == "a.txt"
    assert fence.parse(body, ctype()) == second
