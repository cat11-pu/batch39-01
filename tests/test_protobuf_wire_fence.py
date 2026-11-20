import pytest

import protobuf_wire_fence as pw


def varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field(number, wire, payload):
    return varint((number << 3) | wire) + payload


def scan(data, **over):
    kwargs = {"max_depth": 16, "max_bytes": 4096}
    kwargs.update(over)
    return pw.ProtobufWireScan(**kwargs).parse(data)


def test_varint_overflow_is_rejected():
    with pytest.raises(pw.WireError) as exc:
        scan(b"\x80" * 11)
    assert exc.value.code == "varint_overflow"


def test_field_number_zero_is_rejected():
    with pytest.raises(pw.WireError):
        scan(b"\x00\x01")


def test_length_prefix_beyond_remaining_is_rejected():
    with pytest.raises(pw.WireError) as exc:
        scan(field(1, 2, varint(99) + b"abc"))
    assert exc.value.code == "length_overflow"


def test_nesting_depth_is_limited():
    inner = field(1, 0, varint(1))
    for _ in range(5):
        inner = field(1, 2, varint(len(inner)) + inner)
    with pytest.raises(pw.WireError):
        scan(inner, max_depth=2)


def test_duplicate_fields_keep_order():
    data = field(1, 0, varint(1)) + field(1, 0, varint(2))
    result = scan(data)
    assert [item["value"] for item in result["fields"]] == [1, 2]


def test_map_entry_conflict_is_detected():
    entry = field(1, 0, varint(1)) + field(2, 0, varint(2))
    data = field(3, 2, varint(len(entry)) + entry) + field(3, 2, varint(len(entry)) + entry)
    result = scan(data)
    assert result["map_conflicts"] >= 1


def test_unknown_fields_are_preserved():
    result = scan(field(99, 0, varint(7)))
    assert result["unknown"]


def test_group_wire_type_is_rejected_or_parsed():
    with pytest.raises(pw.WireError):
        scan(varint((1 << 3) | 3))


def test_invalid_utf8_string_is_rejected():
    with pytest.raises(pw.WireError):
        scan(field(1, 2, varint(2) + b"\xff\xfe"))


def test_trailing_bytes_are_rejected():
    with pytest.raises(pw.WireError) as exc:
        scan(field(1, 0, varint(1)) + b"\x00")
    assert exc.value.code == "trailing_bytes"


def test_reserved_field_range_is_rejected():
    with pytest.raises(pw.WireError):
        scan(field(19000, 0, varint(1)))


def test_total_byte_limit_is_enforced():
    with pytest.raises(pw.WireError):
        scan(field(1, 2, varint(20) + b"x" * 20), max_bytes=10)


def test_invalid_wire_type_is_rejected():
    with pytest.raises(pw.WireError):
        scan(varint((1 << 3) | 6))


def test_field_order_matches_wire_order():
    result = scan(field(2, 0, varint(2)) + field(1, 0, varint(1)))
    assert [item["field"] for item in result["fields"]] == [2, 1]


def test_consumed_byte_count_is_reported():
    data = field(1, 0, varint(1))
    assert scan(data)["consumed"] == len(data)
