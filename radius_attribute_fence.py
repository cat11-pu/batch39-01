class RadiusError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


import hashlib
import struct

HEADER_LENGTH = 20
MIN_ATTRIBUTE_LENGTH = 2

ATTR_VENDOR_SPECIFIC = 26
ATTR_PROXY_STATE = 33
ATTR_MESSAGE_AUTHENTICATOR = 80

INTEGER_ATTRIBUTES = frozenset({
    5, 6, 7, 10, 12, 13, 27, 28, 29, 37, 38,
    40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51,
    55, 61, 62, 85,
})

ADDRESS_ATTRIBUTES = frozenset({4, 8, 9, 14, 95, 98})

TUNNEL_ATTRIBUTES = frozenset({64, 65, 66, 67, 68, 69, 81, 82, 83, 90, 91})

KNOWN_ATTRIBUTES = frozenset(range(1, 97))


class RadiusPacketGuard:
    def __init__(self, max_attributes=64, max_value=253, max_total=4096):
        self.max_attributes = max_attributes
        self.max_value = max_value
        self.max_total = max_total

    def parse(self, packet, secret=b"secret"):
        if len(packet) < HEADER_LENGTH:
            raise RadiusError("packet_too_short", 0)
        code, identifier, declared = struct.unpack_from(">BBH", packet, 0)
        if declared != len(packet):
            raise RadiusError("length_mismatch", 2)
        if declared > self.max_total:
            raise RadiusError("packet_too_long", 2)

        request_authenticator = packet[4:HEADER_LENGTH]
        body = packet[HEADER_LENGTH:]

        attributes = []
        proxy_state = []
        unknown = []
        tunnels = {}
        vendors = []
        authenticator_offset = None

        offset = HEADER_LENGTH
        end = len(packet)
        while offset < end:
            if offset + MIN_ATTRIBUTE_LENGTH > end:
                raise RadiusError("truncated_attribute", offset)
            atype = packet[offset]
            alen = packet[offset + 1]
            if alen < MIN_ATTRIBUTE_LENGTH:
                raise RadiusError("zero_length", offset)
            if alen - MIN_ATTRIBUTE_LENGTH > self.max_value:
                raise RadiusError("value_too_long", offset)
            if offset + alen > end:
                raise RadiusError("length_beyond_packet", offset)
            value = packet[offset + 2:offset + alen]

            if len(attributes) >= self.max_attributes:
                raise RadiusError("too_many_attributes", offset)

            if atype == ATTR_MESSAGE_AUTHENTICATOR:
                if authenticator_offset is not None:
                    raise RadiusError("duplicate_authenticator", offset)
                if len(value) != 16:
                    raise RadiusError("bad_authenticator_length", offset)
                authenticator_offset = offset
            elif atype == ATTR_PROXY_STATE:
                proxy_state.append(value)
            elif atype == ATTR_VENDOR_SPECIFIC:
                vendors.append(self._parse_vendor(value, offset))
            elif atype in TUNNEL_ATTRIBUTES:
                if len(value) < 2:
                    raise RadiusError("tunnel_unpaired", offset)
                tunnels.setdefault(value[0], []).append(value[1:])
            elif atype in INTEGER_ATTRIBUTES:
                if len(value) != 4:
                    raise RadiusError("bad_integer_length", offset)
            elif atype in ADDRESS_ATTRIBUTES:
                if len(value) not in (4, 16):
                    raise RadiusError("bad_address_length", offset)
            elif atype not in KNOWN_ATTRIBUTES:
                unknown.append({"type": atype, "value": value})

            attributes.append({"type": atype, "value": value, "offset": offset})
            offset += alen

        message_authenticator = None
        if authenticator_offset is not None:
            start = authenticator_offset + 2
            stop = start + 16
            stored = packet[start:stop]
            zeroed = packet[:start] + b"\x00" * 16 + packet[stop:]
            expected = hashlib.md5(zeroed + secret).digest()
            if stored != b"\x00" * 16 and stored != expected:
                raise RadiusError("bad_authenticator", authenticator_offset)
            message_authenticator = expected

        response_authenticator = hashlib.md5(
            packet[:4] + request_authenticator + body + secret
        ).digest()

        return {
            "code": code,
            "identifier": identifier,
            "request_authenticator": request_authenticator,
            "attributes": attributes,
            "proxy_state": proxy_state,
            "unknown": unknown,
            "tunnels": tunnels,
            "vendors": vendors,
            "message_authenticator": message_authenticator,
            "response_authenticator": response_authenticator,
        }

    def _parse_vendor(self, value, offset):
        if len(value) < 4:
            raise RadiusError("vendor_truncated", offset)
        vendor_id = struct.unpack_from(">I", value, 0)[0]
        inner = []
        pos = 4
        end = len(value)
        while pos < end:
            if pos + MIN_ATTRIBUTE_LENGTH > end:
                raise RadiusError("vendor_truncated", offset + pos)
            itype = value[pos]
            ilen = value[pos + 1]
            if ilen < MIN_ATTRIBUTE_LENGTH:
                raise RadiusError("zero_length", offset + pos)
            if pos + ilen > end:
                raise RadiusError("vendor_inner_length", offset + pos)
            inner.append({"type": itype, "value": value[pos + 2:pos + ilen]})
            pos += ilen
        return {"vendor": vendor_id, "attributes": inner}
