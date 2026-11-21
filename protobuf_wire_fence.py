import unicodedata


MAX_FIELD_NUMBER = (1 << 29) - 1
RESERVED_FIELD_FIRST = 19000
RESERVED_FIELD_LAST = 19999

WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_LENGTH_DELIMITED = 2
WIRE_START_GROUP = 3
WIRE_END_GROUP = 4
WIRE_FIXED32 = 5

SUPPORTED_WIRE_TYPES = frozenset(
    {WIRE_VARINT, WIRE_FIXED64, WIRE_LENGTH_DELIMITED, WIRE_FIXED32}
)
GROUP_WIRE_TYPES = frozenset({WIRE_START_GROUP, WIRE_END_GROUP})

DEFAULT_KNOWN_FIELDS = frozenset({1, 2, 3})


class WireError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


class ProtobufWireScan:
    def __init__(self, max_depth=16, max_bytes=4096, known_fields=None, map_fields=None):
        if not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")
        if not isinstance(max_bytes, int) or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")
        self.max_depth = max_depth
        self.max_bytes = max_bytes
        self.known_fields = frozenset(
            DEFAULT_KNOWN_FIELDS if known_fields is None else known_fields
        )
        self.map_fields = None if map_fields is None else frozenset(map_fields)

    def parse(self, data):
        if isinstance(data, str):
            raise TypeError("data must be bytes-like")
        try:
            buffer = bytes(data)
        except (TypeError, ValueError) as exc:
            raise TypeError("data must be bytes-like") from exc

        if len(buffer) > self.max_bytes:
            raise WireError("max_bytes_exceeded", 0)

        return self._parse_message(buffer, 0, 0, True)

    def _parse_message(self, buffer, depth, base_offset, is_root):
        if depth > self.max_depth:
            raise WireError("depth_exceeded", base_offset)
        if len(buffer) > self.max_bytes:
            raise WireError("max_bytes_exceeded", base_offset)

        fields = []
        unknown = []
        maps = {}
        map_conflicts = 0
        position = 0
        size = len(buffer)

        while position < size:
            field_start = position
            tag, position = self._read_varint(buffer, position, base_offset)
            field_number = tag >> 3
            wire_type = tag & 0x07

            if field_number == 0:
                if is_root and field_start > 0:
                    raise WireError("trailing_bytes", base_offset + field_start)
                raise WireError("invalid_field_number", base_offset + field_start)
            if field_number > MAX_FIELD_NUMBER:
                raise WireError("invalid_field_number", base_offset + field_start)
            if RESERVED_FIELD_FIRST <= field_number <= RESERVED_FIELD_LAST:
                raise WireError("reserved_field_number", base_offset + field_start)
            if wire_type in GROUP_WIRE_TYPES:
                raise WireError("group_not_supported", base_offset + field_start)
            if wire_type not in SUPPORTED_WIRE_TYPES:
                raise WireError("invalid_wire_type", base_offset + field_start)

            known = field_number in self.known_fields
            value_kind = "scalar"
            map_key = None
            map_value = None

            if wire_type == WIRE_VARINT:
                value, position = self._read_varint(
                    buffer, position, base_offset
                )
            elif wire_type == WIRE_FIXED64:
                end = position + 8
                if end > size:
                    raise WireError(
                        "truncated_fixed64", base_offset + position
                    )
                value = int.from_bytes(buffer[position:end], "little")
                position = end
            elif wire_type == WIRE_FIXED32:
                end = position + 4
                if end > size:
                    raise WireError(
                        "truncated_fixed32", base_offset + position
                    )
                value = int.from_bytes(buffer[position:end], "little")
                position = end
            else:
                length, payload_start = self._read_varint(
                    buffer, position, base_offset
                )
                if length > size - payload_start:
                    raise WireError(
                        "length_overflow", base_offset + payload_start
                    )
                payload_end = payload_start + length
                payload = buffer[payload_start:payload_end]
                position = payload_end

                if not known:
                    value = payload
                    value_kind = "bytes"
                else:
                    value, value_kind, map_key, map_value = (
                        self._decode_length_delimited(
                            payload,
                            field_number,
                            depth,
                            base_offset + payload_start,
                        )
                    )

            field_end = position
            raw = buffer[field_start:field_end]
            item = {
                "field": field_number,
                "number": field_number,
                "wire_type": wire_type,
                "wire": wire_type,
                "value": value,
                "value_kind": value_kind,
                "offset": base_offset + field_start,
                "end": base_offset + field_end,
                "raw": raw,
                "known": known,
            }
            if map_key is not None:
                item["map_key"] = map_key
                item["map_value"] = map_value
            fields.append(item)

            if not known:
                unknown.append(item)
            elif map_key is not None:
                field_maps = maps.setdefault(field_number, {})
                if map_key in field_maps:
                    map_conflicts += 1
                field_maps[map_key] = map_value

        return {
            "fields": fields,
            "unknown": unknown,
            "unknown_fields": unknown,
            "maps": maps,
            "map_conflicts": map_conflicts,
            "consumed": size,
            "bytes_consumed": size,
        }

    def _decode_length_delimited(self, payload, field_number, depth, offset):
        text = self._decode_text(payload)
        if text is not None:
            return text, "string", None, None

        try:
            nested = self._parse_message(payload, depth + 1, offset, False)
        except WireError as nested_error:
            if nested_error.code in {"depth_exceeded", "max_bytes_exceeded"}:
                raise
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WireError("invalid_utf8", offset + exc.start) from exc
            if self._looks_like_message_start(payload):
                raise nested_error
            return text, "string", None, None

        entry = None
        if self.map_fields is None or field_number in self.map_fields:
            entry = self._map_entry(nested)
        if entry is not None:
            key, value = entry
            return nested, "map_entry", key, value
        return nested, "message", None, None

    def _looks_like_message_start(self, payload):
        if not payload:
            return False
        if payload[0] == 0:
            return True
        try:
            tag, _ = self._read_varint(payload, 0, 0)
        except WireError:
            return False
        field_number = tag >> 3
        wire_type = tag & 0x07
        return (
            field_number in self.known_fields
            and (
                wire_type in SUPPORTED_WIRE_TYPES
                or wire_type in GROUP_WIRE_TYPES
            )
        )

    def _map_entry(self, nested):
        fields = nested["fields"]
        if len(fields) != 2:
            return None
        if {item["field"] for item in fields} != {1, 2}:
            return None
        key_items = [item for item in fields if item["field"] == 1]
        value_items = [item for item in fields if item["field"] == 2]
        if len(key_items) != 1 or len(value_items) != 1:
            return None
        key = key_items[0]["value"]
        try:
            hash(key)
        except TypeError:
            return None
        return key, value_items[0]["value"]

    @staticmethod
    def _decode_text(payload):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if not text:
            return text
        for character in text:
            if character in "\t\n\r":
                continue
            if unicodedata.category(character).startswith("C"):
                return None
        return text

    @staticmethod
    def _read_varint(buffer, position, base_offset):
        value = 0
        size = len(buffer)
        for index in range(10):
            if position >= size:
                raise WireError(
                    "truncated_varint", base_offset + position
                )
            byte = buffer[position]
            position += 1
            if index == 9:
                if byte & 0xFE:
                    raise WireError(
                        "varint_overflow", base_offset + position - 1
                    )
                return value | (byte << 63), position
            value |= (byte & 0x7F) << (index * 7)
            if not byte & 0x80:
                return value, position
        raise WireError("varint_overflow", base_offset + position - 1)
