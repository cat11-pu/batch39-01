import struct

import pytest

import msgpack_depth_fence as mp


def unpack(data, **over):
    kwargs = {"max_depth": 16, "max_elements": 10000, "max_bytes": 4096}
    kwargs.update(over)
    return mp.MsgpackNestedCheck(**kwargs).unpack(data)


def test_array_header_larger_than_input_is_rejected():
    with pytest.raises(mp.MsgpackError) as exc:
        unpack(b"\x94\x01")
    assert exc.value.code == "length_overflow"


def test_map_header_larger_than_input_is_rejected():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\x83\xa1a\x01")


def test_nesting_depth_is_limited():
    data = b"\x91" * 5 + b"\x01"
    with pytest.raises(mp.MsgpackError):
        unpack(data, max_depth=2)


def test_string_length_beyond_remaining_is_rejected():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\xd9\xff")


def test_extension_length_must_match_remaining_bytes():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\xc7\x04\x01\x00")


def test_duplicate_map_key_is_rejected():
    data = b"\x82\xa1a\x01\xa1a\x02"
    with pytest.raises(mp.MsgpackError) as exc:
        unpack(data)
    assert exc.value.code == "duplicate_key"


def test_non_string_map_key_is_rejected():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\x81\x01\x02")


def test_reserved_tag_is_rejected():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\xc1")


def test_trailing_bytes_are_rejected():
    with pytest.raises(mp.MsgpackError) as exc:
        unpack(b"\x01\x02")
    assert exc.value.code == "trailing"


def test_special_float_is_flagged():
    result = unpack(b"\xcb" + struct.pack(">d", float("inf")))
    assert result["warnings"]


def test_truncated_data_is_rejected():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\xa5abc")


def test_total_element_limit_is_enforced():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\x93\x01\x02\x03", max_elements=2)


def test_string_length_limit_is_enforced():
    with pytest.raises(mp.MsgpackError):
        unpack(b"\xa5hello", max_bytes=3)


def test_error_reports_offset():
    with pytest.raises(mp.MsgpackError) as exc:
        unpack(b"\x92\x01")
    assert exc.value.offset is not None


def test_parsed_byte_count_is_reported():
    data = b"\x92\x01\x02"
    assert unpack(data)["consumed"] == len(data)
