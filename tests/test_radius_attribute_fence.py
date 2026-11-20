import struct

import pytest

import radius_attribute_fence as rf

HEADER = 20


def attr(kind, value):
    return bytes([kind, len(value) + 2]) + value


def packet(body, code=1, ident=1, authenticator=b"A" * 16):
    return bytes([code, ident]) + struct.pack(">H", HEADER + len(body)) + authenticator + body


def parse(body, **over):
    kwargs = {"max_attributes": 64, "max_value": 253, "max_total": 4096}
    kwargs.update(over)
    return rf.RadiusPacketGuard(**kwargs).parse(packet(body))


def test_zero_length_attribute_is_rejected():
    with pytest.raises(rf.RadiusError) as exc:
        parse(b"\x01\x00")
    assert exc.value.code == "zero_length"


def test_attribute_length_beyond_packet_is_rejected():
    with pytest.raises(rf.RadiusError):
        parse(b"\x01\x09abc")


def test_vendor_specific_inner_length_is_checked():
    inner = struct.pack(">I", 9) + b"\x01\x0aab"
    with pytest.raises(rf.RadiusError):
        parse(attr(26, inner))


def test_duplicate_message_authenticator_is_rejected():
    body = attr(80, b"\x00" * 16) + attr(80, b"\x00" * 16)
    with pytest.raises(rf.RadiusError) as exc:
        parse(body)
    assert exc.value.code == "duplicate_authenticator"


def test_proxy_state_is_passed_through_not_evaluated():
    result = parse(attr(33, b"state"))
    assert result["proxy_state"] == [b"state"]


def test_tunnel_attribute_requires_label_value_pair():
    with pytest.raises(rf.RadiusError):
        parse(attr(64, b"\x01"))


def test_integer_attribute_must_be_four_bytes():
    with pytest.raises(rf.RadiusError):
        parse(attr(27, b"\x00\x01"))


def test_address_attribute_must_be_four_or_sixteen_bytes():
    with pytest.raises(rf.RadiusError):
        parse(attr(4, b"\x01\x02"))


def test_attribute_count_limit_is_enforced():
    body = attr(1, b"a") * 5
    with pytest.raises(rf.RadiusError):
        parse(body, max_attributes=2)


def test_response_authenticator_uses_request_and_response():
    body = attr(80, b"\x00" * 16)
    result = parse(body)
    assert "response_authenticator" in result


def test_unknown_attributes_are_preserved():
    result = parse(attr(200, b"opaque"))
    assert result["unknown"]


def test_packet_length_mismatch_is_rejected():
    bad = packet(attr(1, b"a"))
    bad = bad[:2] + struct.pack(">H", len(bad) + 5) + bad[4:]
    with pytest.raises(rf.RadiusError):
        rf.RadiusPacketGuard().parse(bad)


def test_single_value_length_limit_is_enforced():
    with pytest.raises(rf.RadiusError):
        parse(attr(1, b"abcd"), max_value=3)


def test_total_length_limit_is_enforced():
    with pytest.raises(rf.RadiusError):
        parse(attr(1, b"abcd"), max_total=22)


def test_attributes_are_parsed_in_order():
    result = parse(attr(1, b"a") + attr(2, b"b"))
    assert [item["type"] for item in result["attributes"]] == [1, 2]
