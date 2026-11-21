import math
import struct
from collections import namedtuple

Timestamp = namedtuple("Timestamp", ["seconds", "nanoseconds"])
ExtValue = namedtuple("ExtValue", ["type", "data"])

_TIMESTAMP_TYPE = -1
_TIMESTAMP_LENGTHS = (4, 8, 12)


class MsgpackError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


class MsgpackNestedCheck:
    def __init__(self, max_depth=16, max_elements=10000, max_bytes=4096):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.max_bytes = max_bytes
        self._data = b""
        self._pos = 0
        self._elements = 0
        self._warnings = []

    def unpack(self, data):
        self._data = bytes(data)
        self._pos = 0
        self._elements = 0
        self._warnings = []
        obj = self._read_value(1)
        if self._pos != len(self._data):
            raise MsgpackError("trailing", offset=self._pos)
        return {
            "object": obj,
            "consumed": self._pos,
            "warnings": list(self._warnings),
        }

    def _remaining(self):
        return len(self._data) - self._pos

    def _take(self, size, offset):
        if size > self._remaining():
            raise MsgpackError("truncated", offset=offset)
        chunk = self._data[self._pos:self._pos + size]
        self._pos += size
        return chunk

    def _read_byte(self):
        if self._remaining() < 1:
            raise MsgpackError("truncated", offset=self._pos)
        byte = self._data[self._pos]
        self._pos += 1
        return byte

    def _read_int(self, fmt, size):
        offset = self._pos
        return struct.unpack(fmt, self._take(size, offset))[0]

    def _count_elements(self, count, offset):
        if count > self.max_elements - self._elements:
            raise MsgpackError("too_many_elements", offset=offset)
        self._elements += count

    def _check_declared_length(self, count, offset):
        if count > self._remaining():
            raise MsgpackError("length_overflow", offset=offset)

    def _read_value(self, depth):
        if self._remaining() < 1:
            raise MsgpackError("truncated", offset=self._pos)
        offset = self._pos
        tag = self._data[self._pos]
        self._pos += 1

        if tag <= 0x7F:
            return tag
        if tag >= 0xE0:
            return tag - 0x100
        if 0xA0 <= tag <= 0xBF:
            return self._read_str(tag & 0x1F, offset)
        if 0x90 <= tag <= 0x9F:
            return self._read_array(tag & 0x0F, offset, depth)
        if 0x80 <= tag <= 0x8F:
            return self._read_map(tag & 0x0F, offset, depth)

        if tag == 0xC0:
            return None
        if tag == 0xC1:
            raise MsgpackError("reserved_tag", offset=offset)
        if tag == 0xC2:
            return False
        if tag == 0xC3:
            return True
        if tag == 0xC4:
            return self._read_bin(self._read_int(">B", 1), offset)
        if tag == 0xC5:
            return self._read_bin(self._read_int(">H", 2), offset)
        if tag == 0xC6:
            return self._read_bin(self._read_int(">I", 4), offset)
        if tag == 0xC7:
            return self._read_ext(self._read_int(">B", 1), offset)
        if tag == 0xC8:
            return self._read_ext(self._read_int(">H", 2), offset)
        if tag == 0xC9:
            return self._read_ext(self._read_int(">I", 4), offset)
        if tag == 0xCA:
            return self._read_float(">f", 4, offset)
        if tag == 0xCB:
            return self._read_float(">d", 8, offset)
        if tag == 0xCC:
            return self._read_int(">B", 1)
        if tag == 0xCD:
            return self._read_int(">H", 2)
        if tag == 0xCE:
            return self._read_int(">I", 4)
        if tag == 0xCF:
            return self._read_int(">Q", 8)
        if tag == 0xD0:
            return self._read_int(">b", 1)
        if tag == 0xD1:
            return self._read_int(">h", 2)
        if tag == 0xD2:
            return self._read_int(">i", 4)
        if tag == 0xD3:
            return self._read_int(">q", 8)
        if tag == 0xD4:
            return self._read_ext(1, offset)
        if tag == 0xD5:
            return self._read_ext(2, offset)
        if tag == 0xD6:
            return self._read_ext(4, offset)
        if tag == 0xD7:
            return self._read_ext(8, offset)
        if tag == 0xD8:
            return self._read_ext(16, offset)
        if tag == 0xD9:
            return self._read_str(self._read_int(">B", 1), offset)
        if tag == 0xDA:
            return self._read_str(self._read_int(">H", 2), offset)
        if tag == 0xDB:
            return self._read_str(self._read_int(">I", 4), offset)
        if tag == 0xDC:
            return self._read_array(self._read_int(">H", 2), offset, depth)
        if tag == 0xDD:
            return self._read_array(self._read_int(">I", 4), offset, depth)
        if tag == 0xDE:
            return self._read_map(self._read_int(">H", 2), offset, depth)
        if tag == 0xDF:
            return self._read_map(self._read_int(">I", 4), offset, depth)
        raise MsgpackError("reserved_tag", offset=offset)

    def _read_array(self, count, offset, depth):
        if depth > self.max_depth:
            raise MsgpackError("depth_exceeded", offset=offset)
        self._check_declared_length(count, offset)
        self._count_elements(count, offset)
        return [self._read_value(depth + 1) for _ in range(count)]

    def _read_map(self, count, offset, depth):
        if depth > self.max_depth:
            raise MsgpackError("depth_exceeded", offset=offset)
        self._check_declared_length(count * 2, offset)
        self._count_elements(count * 2, offset)
        result = {}
        for _ in range(count):
            key_offset = self._pos
            key = self._read_value(depth + 1)
            if not isinstance(key, str):
                raise MsgpackError("invalid_key", offset=key_offset)
            if key in result:
                raise MsgpackError("duplicate_key", offset=key_offset)
            result[key] = self._read_value(depth + 1)
        return result

    def _read_str(self, length, offset):
        if length > self.max_bytes:
            raise MsgpackError("length_overflow", offset=offset)
        self._check_declared_length(length, offset)
        raw = self._take(length, offset)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise MsgpackError("invalid_utf8", offset=offset)

    def _read_bin(self, length, offset):
        if length > self.max_bytes:
            raise MsgpackError("length_overflow", offset=offset)
        self._check_declared_length(length, offset)
        return self._take(length, offset)

    def _read_ext(self, length, offset):
        self._check_declared_length(length, offset)
        ext_type = self._read_int(">b", 1)
        if ext_type == _TIMESTAMP_TYPE and length not in _TIMESTAMP_LENGTHS:
            raise MsgpackError("invalid_ext_length", offset=offset)
        payload = self._take(length, offset)
        if ext_type == _TIMESTAMP_TYPE:
            return self._decode_timestamp(payload)
        return ExtValue(ext_type, payload)

    def _decode_timestamp(self, payload):
        if len(payload) == 4:
            return Timestamp(struct.unpack(">I", payload)[0], 0)
        if len(payload) == 8:
            packed = struct.unpack(">Q", payload)[0]
            return Timestamp(packed & 0x00000003FFFFFFFF, packed >> 34)
        nanoseconds, seconds = struct.unpack(">Iq", payload)
        return Timestamp(seconds, nanoseconds)

    def _read_float(self, fmt, size, offset):
        value = struct.unpack(fmt, self._take(size, offset))[0]
        if math.isnan(value) or math.isinf(value):
            self._warnings.append({
                "code": "special_float",
                "offset": offset,
                "value": repr(value),
            })
        return value
