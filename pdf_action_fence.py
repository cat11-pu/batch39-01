"""A small, defensive PDF action scanner.

The scanner deliberately does not render or execute a PDF.  It only parses the
file structure far enough to inventory actions that can affect the reader or
the host system.  Objects are resolved through the cross-reference data (both
classic tables and cross-reference streams), including older incremental
revisions, so an action cannot be hidden by publishing a clean newer revision.
"""

from __future__ import annotations

import base64
import binascii
import re
import zlib
from dataclasses import dataclass, field
from typing import Any, Iterable


PDF_WHITESPACE = b"\x00\t\n\f\r "
PDF_DELIMITERS = b"()<>[]{}/%"
_NUMBER_RE = re.compile(rb"[+-]?(?:\d+\.\d*|\.\d+|\d+)")
_INTEGER_RE = re.compile(rb"\d+")


class PDFSyntaxError(ValueError):
    """Raised when the parser encounters malformed PDF syntax."""


class Name(str):
    """A PDF name object (the leading slash is removed and #xx is decoded)."""


@dataclass(frozen=True)
class Ref:
    num: int
    gen: int = 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.num} {self.gen} R"


@dataclass
class Stream:
    dictionary: dict[str, Any]
    data: bytes


@dataclass
class ObjectRecord:
    number: int
    value: Any
    revision: int
    source: str


@dataclass
class _XrefEntry:
    kind: str
    offset: int = 0
    generation: int = 0
    objstm: int = 0
    index: int = 0


@dataclass
class _XrefSection:
    entries: dict[int, _XrefEntry] = field(default_factory=dict)
    trailer: dict[str, Any] = field(default_factory=dict)
    offset: int = 0


class _Lexer:
    """A byte-oriented parser for PDF object syntax."""

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.size = len(data)

    def _skip_ws(self) -> None:
        data = self.data
        size = self.size
        while self.pos < size:
            char = data[self.pos]
            if char in PDF_WHITESPACE:
                self.pos += 1
            elif char == 0x25:  # '%' comment
                self.pos += 1
                while self.pos < size and data[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                break

    def _starts_keyword(self, keyword: bytes) -> bool:
        end = self.pos + len(keyword)
        if self.data[self.pos:end] != keyword:
            return False
        return end >= self.size or self.data[end] in PDF_WHITESPACE + PDF_DELIMITERS

    def _token(self) -> bytes:
        start = self.pos
        data = self.data
        size = self.size
        while self.pos < size:
            char = data[self.pos]
            if char in PDF_WHITESPACE or char in PDF_DELIMITERS:
                break
            self.pos += 1
        return data[start:self.pos]

    def _parse_name(self) -> Name:
        # self.data[self.pos] == '/'
        self.pos += 1
        raw = bytearray()
        data = self.data
        size = self.size
        while self.pos < size:
            char = data[self.pos]
            if char in PDF_WHITESPACE or char in PDF_DELIMITERS:
                break
            if char == 0x23 and self.pos + 2 < size:  # #xx escape
                pair = data[self.pos + 1:self.pos + 3]
                try:
                    raw.append(int(pair, 16))
                    self.pos += 3
                    continue
                except ValueError:
                    pass
            raw.append(char)
            self.pos += 1
        return Name(_decode_text(bytes(raw)))

    def _parse_literal_string(self) -> bytes:
        # self.data[self.pos] == '('
        self.pos += 1
        out = bytearray()
        depth = 1
        data = self.data
        size = self.size
        while self.pos < size:
            char = data[self.pos]
            self.pos += 1
            if char == 0x5C:  # backslash
                if self.pos >= size:
                    break
                escaped = data[self.pos]
                self.pos += 1
                if escaped == 0x6E:
                    out.append(0x0A)
                elif escaped == 0x72:
                    out.append(0x0D)
                elif escaped == 0x74:
                    out.append(0x09)
                elif escaped == 0x62:
                    out.append(0x08)
                elif escaped == 0x66:
                    out.append(0x0C)
                elif escaped in b"()\\":
                    out.append(escaped)
                elif escaped in b"\r\n":
                    if escaped == 0x0D and self.pos < size and data[self.pos] == 0x0A:
                        self.pos += 1
                elif 0x30 <= escaped <= 0x37:
                    digits = bytearray([escaped])
                    while self.pos < size and len(digits) < 3 and 0x30 <= data[self.pos] <= 0x37:
                        digits.append(data[self.pos])
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                else:
                    # Preserve the backslash for unknown escapes.  PDF drops
                    # it, but JavaScript strings frequently use \xNN and
                    # \uNNNN and the fence needs to decode those sequences.
                    out.append(0x5C)
                    out.append(escaped)
            elif char == 0x28:  # '('
                depth += 1
                out.append(char)
            elif char == 0x29:  # ')'
                depth -= 1
                if depth == 0:
                    break
                out.append(char)
            elif char == 0x0D:
                if self.pos < size and data[self.pos] == 0x0A:
                    self.pos += 1
                out.append(0x0A)
            else:
                out.append(char)
        return bytes(out)

    def _parse_hex_string(self) -> bytes:
        # self.data[self.pos] == '<' and the next byte is not '<'
        self.pos += 1
        start = self.pos
        while self.pos < self.size and self.data[self.pos] != 0x3E:
            self.pos += 1
        raw = bytes(c for c in self.data[start:self.pos] if c not in PDF_WHITESPACE)
        if self.pos < self.size:
            self.pos += 1
        if len(raw) % 2:
            raw += b"0"
        try:
            return bytes.fromhex(raw.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            return b""

    def parse_value(self) -> Any:
        self._skip_ws()
        if self.pos >= self.size:
            raise PDFSyntaxError("unexpected end of file")

        data = self.data
        char = data[self.pos]

        if char == 0x2F:  # '/'
            return self._parse_name()
        if char == 0x28:  # '('
            return self._parse_literal_string()
        if char == 0x3C:  # '<'
            if self.pos + 1 < self.size and data[self.pos + 1] == 0x3C:
                return self._parse_dictionary()
            return self._parse_hex_string()
        if char == 0x5B:  # '['
            self.pos += 1
            values = []
            while True:
                self._skip_ws()
                if self.pos >= self.size:
                    raise PDFSyntaxError("unterminated array")
                if data[self.pos] == 0x5D:  # ']'
                    self.pos += 1
                    return values
                values.append(self.parse_value())

        match = _NUMBER_RE.match(data, self.pos)
        if match:
            token = match.group(0)
            self.pos = match.end()
            if b"." in token:
                try:
                    return float(token)
                except ValueError:
                    return 0.0
            try:
                number = int(token)
            except ValueError:
                return 0

            # An integer can be the first part of "N G R".
            save = self.pos
            self._skip_ws()
            gen_match = _INTEGER_RE.match(data, self.pos)
            if gen_match:
                gen_end = gen_match.end()
                p = gen_end
                while p < self.size and data[p] in PDF_WHITESPACE:
                    p += 1
                if p < self.size and data[p] == 0x52:  # 'R'
                    end = p + 1
                    if end >= self.size or data[end] in PDF_WHITESPACE + PDF_DELIMITERS:
                        self.pos = end
                        return Ref(number, int(gen_match.group(0)))
            self.pos = save
            return number

        token = self._token()
        if token == b"true":
            return True
        if token == b"false":
            return False
        if token == b"null":
            return None
        if not token:
            # Make progress on an unexpected delimiter instead of looping.
            self.pos += 1
        return token.decode("latin-1", "replace")

    def _parse_dictionary(self) -> dict[str, Any]:
        # self.data[self.pos:self.pos + 2] == '<<'
        self.pos += 2
        result: dict[str, Any] = {}
        while True:
            self._skip_ws()
            if self.pos >= self.size:
                raise PDFSyntaxError("unterminated dictionary")
            if self.data.startswith(b">>", self.pos):
                self.pos += 2
                return result
            if self.data[self.pos] != 0x2F:
                # Recover from a malformed key by skipping one token.
                self.parse_value()
                continue
            key = str(self._parse_name())
            value = self.parse_value()
            result[key] = value


def _normalise_name(value: Any) -> str:
    if isinstance(value, Name):
        text = str(value)
    elif isinstance(value, bytes):
        text = _decode_text(value)
    else:
        text = str(value)
    return "".join(c.lower() for c in text if c.isalnum())


def _decode_text(value: bytes) -> str:
    if not value:
        return ""
    if value.startswith(b"\xef\xbb\xbf"):
        return value[3:].decode("utf-8", "replace")
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", "replace")
    if value.startswith(b"\xff\xfe"):
        return value[2:].decode("utf-16-le", "replace")

    # PDF strings are often UTF-16BE without a BOM.  A lot of NULs is a
    # reliable enough hint for the defensive inventory done here.  Check it
    # before UTF-8 because NUL bytes are technically valid UTF-8.
    if len(value) >= 2:
        even_nuls = value[0::2].count(0)
        odd_nuls = value[1::2].count(0)
        if odd_nuls > len(value) // 4 and even_nuls == 0:
            return value.decode("utf-16-le", "replace")
        if even_nuls > len(value) // 4 and odd_nuls == 0:
            return value.decode("utf-16-be", "replace")

    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return value.decode("latin-1", "replace")


_JS_ESCAPE_RE = re.compile(
    r"\\(?:"
    r"x([0-9a-fA-F]{2})|"
    r"u\{([0-9a-fA-F]{1,6})\}|"
    r"u([0-9a-fA-F]{4})|"
    r"([0-7]{1,3})|"
    r"(\r\n|\r|\n)|"
    r"(.))",
    re.S,
)


def _decode_script_escapes(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hex_byte, hex_braced, hex_utf16, octal, newline, other = match.groups()
        try:
            if hex_byte is not None:
                return chr(int(hex_byte, 16))
            if hex_braced is not None:
                return chr(int(hex_braced, 16))
            if hex_utf16 is not None:
                return chr(int(hex_utf16, 16))
            if octal is not None:
                return chr(int(octal, 8))
        except (ValueError, OverflowError):
            return match.group(0)
        if newline is not None:
            return ""
        mapping = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "v": "\v",
            "0": "\0",
        }
        return mapping.get(other, other)

    # Decode repeatedly to handle a second layer such as \\x61.
    for _ in range(4):
        decoded = _JS_ESCAPE_RE.sub(replace, text)
        if decoded == text:
            break
        text = decoded
    return text


def _decode_bytes(value: bytes) -> str:
    return _decode_script_escapes(_decode_text(value))


def _apply_predictor(data: bytes, parameters: Any) -> bytes:
    if not isinstance(parameters, dict):
        return data
    try:
        predictor = int(parameters.get("Predictor", 1))
    except (TypeError, ValueError):
        return data
    if predictor <= 1:
        return data

    try:
        columns = int(parameters.get("Columns", 1))
        colors = int(parameters.get("Colors", 1))
        bits = int(parameters.get("BitsPerComponent", 8))
    except (TypeError, ValueError):
        return data
    if columns <= 0 or colors <= 0 or bits <= 0:
        return data
    row_length = (columns * colors * bits + 7) // 8
    bytes_per_pixel = max(1, (colors * bits + 7) // 8)

    if predictor == 2:
        out = bytearray(data)
        for row_start in range(0, len(out), row_length):
            row_end = min(row_start + row_length, len(out))
            for index in range(row_start + bytes_per_pixel, row_end):
                out[index] = (out[index] + out[index - bytes_per_pixel]) & 0xFF
        return bytes(out)

    if not 10 <= predictor <= 15:
        return data

    out = bytearray()
    previous = bytearray(row_length)
    cursor = 0
    while cursor < len(data):
        filter_type = data[cursor]
        cursor += 1
        row = bytearray(data[cursor:cursor + row_length])
        cursor += row_length
        if len(row) < row_length:
            row.extend(b"\x00" * (row_length - len(row)))
        for index in range(row_length):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - upper_left
                dist_left = abs(estimate - left)
                dist_up = abs(estimate - up)
                dist_upper_left = abs(estimate - upper_left)
                if dist_left <= dist_up and dist_left <= dist_upper_left:
                    value = left
                elif dist_up <= dist_upper_left:
                    value = up
                else:
                    value = upper_left
                row[index] = (row[index] + value) & 0xFF
        out.extend(row)
        previous = row
    return bytes(out)


def _decode_stream(stream: Stream) -> bytes:
    data = stream.data
    filters = stream.dictionary.get("Filter")
    if filters is None:
        return data
    if isinstance(filters, (Name, str)):
        filters = [filters]
    if not isinstance(filters, list):
        return data

    decode_parameters = stream.dictionary.get("DecodeParms")
    if decode_parameters is None:
        decode_parameters = stream.dictionary.get("DP")
    if isinstance(decode_parameters, dict):
        parameter_list = [decode_parameters] * len(filters)
    elif isinstance(decode_parameters, list):
        parameter_list = list(decode_parameters)
    else:
        parameter_list = []

    for filter_index, filter_name in enumerate(filters):
        name = _normalise_name(filter_name)
        parameters = (
            parameter_list[filter_index]
            if filter_index < len(parameter_list)
            else None
        )
        try:
            if name in {"flate", "flatedecode"}:
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    data = zlib.decompress(data.lstrip(), -15)
                data = _apply_predictor(data, parameters)
            elif name in {"asciihex", "asciihexdecode"}:
                raw = bytes(c for c in data if c not in PDF_WHITESPACE)
                raw = raw.split(b">", 1)[0]
                if len(raw) % 2:
                    raw += b"0"
                data = binascii.unhexlify(raw)
            elif name in {"ascii85", "ascii85decode"}:
                cleaned = bytes(c for c in data if c not in PDF_WHITESPACE)
                data = base64.a85decode(cleaned, adobe=True)
            elif name in {"runlength", "runlengthdecode"}:
                out = bytearray()
                index = 0
                while index < len(data):
                    length = data[index]
                    index += 1
                    if length == 128:
                        break
                    if length < 128:
                        out.extend(data[index:index + length + 1])
                        index += length + 1
                    else:
                        if index < len(data):
                            out.extend(data[index:index + 1] * (257 - length))
                        index += 1
                data = bytes(out)
            else:
                break
        except (ValueError, zlib.error, binascii.Error):
            break
    return data


def _iter_direct_refs(value: Any, key: str | None = None) -> Iterable[tuple[Ref, str | None]]:
    """Yield indirect references without resolving them."""
    stack: list[tuple[Any, str | None]] = [(value, key)]
    seen: set[int] = set()
    while stack:
        current, current_key = stack.pop()
        if isinstance(current, Ref):
            yield current, current_key
        elif isinstance(current, Stream):
            stack.append((current.dictionary, current_key))
        elif isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            for item_key, item_value in current.items():
                stack.append((item_value, item_key))
        elif isinstance(current, list):
            for item in current:
                stack.append((item, current_key))


def _iter_inline_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Yield dictionaries nested in one object without following references."""
    stack: list[Any] = [value]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, Stream):
            current = current.dictionary
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


class PdfActionFence:
    """Inventory potentially dangerous PDF actions without executing them."""

    _ACTION_KINDS = {
        "javascript": "javascript",
        "js": "javascript",
        "launch": "launch",
        "submitform": "submit_form",
        "importdata": "import_data",
        "uri": "external_link",
        "gotor": "external_link",
        "gotoe": "external_link",
        "richmedia": "rich_media",
        "rendition": "rich_media",
        "movie": "rich_media",
        "sound": "rich_media",
    }

    _KIND_REASONS = {
        "javascript": "JavaScript action can run code inside the PDF reader",
        "launch": "Launch action can start an external program",
        "submit_form": "SubmitForm action can send form data to an external target",
        "import_data": "ImportData action can import data from an external source",
        "external_link": "URI/GoToR action can send a request to an external or internal address",
        "rich_media": "Rich media can invoke an embedded media player or external resource",
        "embedded_file": "Embedded file can be extracted by the reader",
    }

    _SCRIPT_KEYWORDS = (
        "app.launchurl",
        "app.launch",
        "launchurl",
        "exportdataobject",
        "importdataobject",
        "submitform",
        "geturl",
        "xmlhttprequest",
        "activexobject",
        "eval(",
        "executeglobal",
        "app.alert",
        "this.exportdataobject",
        "this.importdataobject",
        "fetch(",
        "wscript",
        "shell",
    )

    def __init__(self, max_depth: int = 20):
        self.max_depth = max(0, int(max_depth))
        self.data = b""
        self.warnings: list[str] = []
        self._warning_set: set[str] = set()
        self._sections: list[_XrefSection] = []
        self._entries_latest: dict[int, _XrefEntry] = {}
        self._records: list[ObjectRecord] = []
        self._objects_latest: dict[int, Any] = {}
        self._objects_any: dict[int, Any] = {}
        self._records_by_number: dict[int, list[ObjectRecord]] = {}
        self._parsed_offsets: set[tuple[int, int]] = set()
        self._parsed_objstms: set[tuple[int, str]] = set()
        self._extracted_objstm_items: set[tuple[int, str, int]] = set()
        self._incremental = False
        self._encrypted = False
        self._pending_objects: list[tuple[int, int, int, int]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def scan(self, data: bytes | bytearray | memoryview | str) -> dict[str, Any]:
        if isinstance(data, str):
            with open(data, "rb") as handle:
                data = handle.read()
        self.data = bytes(data)
        self.warnings = []
        self._warning_set = set()
        self._sections = []
        self._entries_latest = {}
        self._records = []
        self._objects_latest = {}
        self._objects_any = {}
        self._records_by_number = {}
        self._parsed_offsets = set()
        self._parsed_objstms = set()
        self._extracted_objstm_items = set()
        self._incremental = False
        self._encrypted = False
        self._pending_objects = []

        self._load_xref()
        self._collect_objects()
        self._extract_object_streams()
        self._validate_compressed_objects()
        self._check_encryption()
        self._walk_incrementally_all_versions()

        actions = self._collect_actions()
        actions.sort(key=lambda item: (item["object"], item["kind"], item["detail"]))
        return {
            "actions": actions,
            "warnings": list(self.warnings),
            "needs_review": self._encrypted,
            "encrypted": self._encrypted,
            "clean": not actions,
        }

    # ------------------------------------------------------------------
    # Cross-reference handling
    # ------------------------------------------------------------------
    def _warn(self, code: str) -> None:
        if code not in self._warning_set:
            self._warning_set.add(code)
            self.warnings.append(code)

    def _load_xref(self) -> None:
        matches = list(re.finditer(rb"startxref\s+(\d+)", self.data))
        if not matches:
            self._warn("bad_xref")
            return

        offset = int(matches[-1].group(1))
        visited: set[int] = set()
        while offset is not None:
            if offset in visited:
                self._warn("xref_cycle")
                self._warn("bad_xref")
                break
            visited.add(offset)
            section = self._load_xref_section(offset)
            if section is None:
                self._warn("bad_xref")
                break
            self._sections.append(section)

            # A hybrid file uses /XRefStm as a supplement to the same
            # revision.  Merge its entries before moving to /Prev.
            xref_stm = section.trailer.get("XRefStm")
            if isinstance(xref_stm, int):
                extra = self._load_xref_section(xref_stm)
                if extra is not None:
                    for number, entry in extra.entries.items():
                        section.entries.setdefault(number, entry)

            previous = section.trailer.get("Prev")
            if isinstance(previous, int):
                self._incremental = True
                offset = previous
            else:
                offset = None

        # Newest section first: the first entry seen for an object number is
        # the one that controls normal reference resolution.
        for section in self._sections:
            for number, entry in section.entries.items():
                self._entries_latest.setdefault(number, entry)

        if self._incremental:
            self._warn("incremental_update")

    def _load_xref_section(self, offset: int) -> _XrefSection | None:
        if offset < 0 or offset >= len(self.data):
            return None
        lexer = _Lexer(self.data, offset)
        lexer._skip_ws()
        if lexer._starts_keyword(b"xref"):
            return self._parse_xref_table(lexer.pos)

        parsed = self._parse_indirect_at(offset)
        if parsed is None:
            return None
        _number, _generation, value, _end = parsed
        if not isinstance(value, Stream):
            return None
        if _normalise_name(value.dictionary.get("Type")) != "xref":
            return None
        return self._parse_xref_stream(value, offset)

    def _parse_xref_table(self, offset: int) -> _XrefSection | None:
        section = _XrefSection(offset=offset)
        pos = offset + len(b"xref")
        data = self.data
        size = len(data)
        while pos < size:
            while pos < size and data[pos] in PDF_WHITESPACE:
                pos += 1
            if pos >= size:
                break
            if data.startswith(b"trailer", pos):
                lexer = _Lexer(data, pos + len(b"trailer"))
                try:
                    trailer = lexer.parse_value()
                except (PDFSyntaxError, ValueError):
                    trailer = {}
                if isinstance(trailer, dict):
                    section.trailer = trailer
                return section
            if data.startswith(b"startxref", pos):
                break

            match = re.match(rb"(\d+)\s+(\d+)\s*", data[pos:])
            if not match:
                # Skip a malformed line and keep looking for the trailer.
                newline = data.find(b"\n", pos)
                if newline < 0:
                    break
                pos = newline + 1
                continue

            first = int(match.group(1))
            count = int(match.group(2))
            pos += match.end()
            for index in range(count):
                entry_match = re.match(
                    rb"\s*(\d{1,10})\s+(\d{1,5})\s+([nf])(?:\s|$)",
                    data[pos:],
                )
                if not entry_match:
                    break
                entry_offset = int(entry_match.group(1))
                generation = int(entry_match.group(2))
                entry_type = entry_match.group(3)
                number = first + index
                if entry_type == b"n":
                    section.entries[number] = _XrefEntry(
                        kind="n", offset=entry_offset, generation=generation
                    )
                else:
                    section.entries[number] = _XrefEntry(
                        kind="f", offset=entry_offset, generation=generation
                    )
                pos += entry_match.end()
        if not section.trailer:
            self._warn("bad_xref")
        return section

    def _parse_xref_stream(self, stream: Stream, offset: int) -> _XrefSection | None:
        dictionary = stream.dictionary
        widths = dictionary.get("W")
        if not isinstance(widths, list) or len(widths) < 3:
            return None
        try:
            widths = [int(width) for width in widths[:3]]
        except (TypeError, ValueError):
            return None
        if any(width < 0 for width in widths):
            return None

        index = dictionary.get("Index")
        if not isinstance(index, list):
            size = dictionary.get("Size")
            if not isinstance(size, int):
                return None
            index = [0, size]
        if len(index) % 2:
            return None

        raw = _decode_stream(stream)
        entries: dict[int, _XrefEntry] = {}
        cursor = 0
        for pair_index in range(0, len(index), 2):
            try:
                first = int(index[pair_index])
                count = int(index[pair_index + 1])
            except (TypeError, ValueError):
                continue
            for item in range(count):
                fields: list[int] = []
                for field_index, width in enumerate(widths):
                    if width == 0:
                        fields.append(1 if field_index == 0 else 0)
                    else:
                        chunk = raw[cursor:cursor + width]
                        cursor += width
                        if len(chunk) < width:
                            return _XrefSection(entries=entries, trailer=dictionary, offset=offset)
                        fields.append(int.from_bytes(chunk, "big"))
                number = first + item
                entry_type = fields[0]
                if entry_type == 0:
                    entries[number] = _XrefEntry(
                        kind="f", offset=fields[1], generation=fields[2]
                    )
                elif entry_type == 1:
                    entries[number] = _XrefEntry(
                        kind="n", offset=fields[1], generation=fields[2]
                    )
                elif entry_type == 2:
                    entries[number] = _XrefEntry(
                        kind="c", objstm=fields[1], index=fields[2]
                    )
        return _XrefSection(entries=entries, trailer=dictionary, offset=offset)

    # ------------------------------------------------------------------
    # Object parsing and resolution
    # ------------------------------------------------------------------
    def _parse_indirect_at(self, offset: int) -> tuple[int, int, Any, int] | None:
        data = self.data
        if offset < 0 or offset >= len(data):
            return None
        header = re.match(rb"\s*(\d+)\s+(\d+)\s+obj\b", data[offset:offset + 64])
        if not header:
            return None
        number = int(header.group(1))
        generation = int(header.group(2))
        lexer = _Lexer(data, offset + header.end())
        try:
            value = lexer.parse_value()
        except (PDFSyntaxError, ValueError):
            return None

        if isinstance(value, dict):
            lexer._skip_ws()
            if lexer._starts_keyword(b"stream"):
                lexer.pos += len(b"stream")
                # The stream keyword is followed by a single EOL.
                if lexer.pos < lexer.size and data[lexer.pos] == 0x0D:
                    lexer.pos += 1
                    if lexer.pos < lexer.size and data[lexer.pos] == 0x0A:
                        lexer.pos += 1
                elif lexer.pos < lexer.size and data[lexer.pos] == 0x0A:
                    lexer.pos += 1

                start = lexer.pos
                length = value.get("Length")
                raw = None
                end = None
                if isinstance(length, int) and length >= 0:
                    candidate_end = start + length
                    tail = data[candidate_end:candidate_end + 32]
                    if b"endstream" in tail:
                        raw = data[start:candidate_end]
                        end = data.find(b"endstream", candidate_end)
                        if end >= 0:
                            end += len(b"endstream")
                if raw is None or end is None:
                    match = re.search(rb"endstream\b", data[start:])
                    if match:
                        raw = data[start:start + match.start()]
                        end = start + match.end()
                        # Trim the EOL immediately preceding endstream.
                        if raw.endswith(b"\r\n"):
                            raw = raw[:-2]
                        elif raw.endswith(b"\n") or raw.endswith(b"\r"):
                            raw = raw[:-1]
                    else:
                        return None
                value = Stream(value, raw)
                lexer.pos = end
        return number, generation, value, lexer.pos

    def _add_record(self, number: int, value: Any, revision: int, source: str) -> None:
        record = ObjectRecord(number, value, revision, source)
        self._records.append(record)
        self._records_by_number.setdefault(number, []).append(record)
        self._objects_any.setdefault(number, value)
        if number not in self._objects_latest:
            self._objects_latest[number] = value

    def _collect_objects(self) -> None:
        for revision, section in enumerate(self._sections):
            for number in sorted(section.entries):
                entry = section.entries[number]
                if entry.kind == "n":
                    parsed = self._parse_indirect_at(entry.offset)
                    if parsed is None:
                        self._warn("bad_xref")
                        continue
                    found_number, _generation, value, _end = parsed
                    if found_number != number:
                        self._warn("bad_xref")
                        continue
                    key = (number, entry.offset)
                    if key in self._parsed_offsets:
                        continue
                    self._parsed_offsets.add(key)
                    self._add_record(number, value, revision, f"xref:{entry.offset}")
                elif entry.kind == "c":
                    self._pending_objects.append((number, entry.objstm, entry.index, revision))

        # When no xref section can be used at all, recover a best-effort
        # object list so callers still get an inventory.  With a usable xref
        # we deliberately honour it instead of trusting arbitrary bytes that
        # merely look like object headers; invalid entries are rejected.
        if not self._sections:
            for match in re.finditer(rb"(?m)(?<![0-9])(\d+)\s+(\d+)\s+obj\b", self.data):
                offset = match.start()
                parsed = self._parse_indirect_at(offset)
                if parsed is None:
                    continue
                number, _generation, value, _end = parsed
                key = (number, offset)
                if key in self._parsed_offsets:
                    continue
                self._parsed_offsets.add(key)
                self._add_record(number, value, len(self._sections), f"scan:{offset}")

    def _extract_object_streams(self) -> None:
        # Object streams can theoretically contain references to other object
        # streams, so repeat until no new stream appears.
        for _ in range(8):
            added = False
            candidates = list(self._records)
            for record in candidates:
                stream_key = (record.number, record.source)
                if stream_key in self._parsed_objstms:
                    continue
                value = record.value
                if not isinstance(value, Stream):
                    continue
                if _normalise_name(value.dictionary.get("Type")) != "objstm":
                    continue
                self._parsed_objstms.add(stream_key)
                added = self._extract_one_object_stream(record) or added
            if not added:
                break

    def _validate_compressed_objects(self) -> None:
        for number, objstm, _index, _revision in self._pending_objects:
            if objstm not in self._objects_latest:
                self._warn("bad_xref")
            elif number not in self._objects_latest:
                self._warn("bad_xref")

    def _extract_one_object_stream(self, record: ObjectRecord) -> bool:
        stream = record.value
        assert isinstance(stream, Stream)
        dictionary = stream.dictionary
        count = dictionary.get("N")
        first = dictionary.get("First")
        if not isinstance(count, int) or not isinstance(first, int):
            return False
        if count < 0 or first < 0:
            return False
        payload = _decode_stream(stream)
        header = payload[:first]
        numbers = [int(token) for token in re.findall(rb"\d+", header)]
        pairs = list(zip(numbers[0::2], numbers[1::2]))[:count]
        added = False
        for index, (number, relative_offset) in enumerate(pairs):
            start = first + relative_offset
            if start < 0 or start >= len(payload):
                continue
            lexer = _Lexer(payload, start)
            try:
                value = lexer.parse_value()
            except (PDFSyntaxError, ValueError):
                continue
            key = (number, record.source, index)
            if key in self._extracted_objstm_items:
                continue
            self._extracted_objstm_items.add(key)
            self._add_record(
                number,
                value,
                record.revision,
                f"objstm:{record.number}:{index}",
            )
            added = True
        return added

    def _resolve(self, value: Any) -> Any:
        if not isinstance(value, Ref):
            return value
        return self._objects_latest.get(value.num)

    def _resolve_any(self, value: Any) -> Any:
        if not isinstance(value, Ref):
            return value
        return self._objects_latest.get(value.num, self._objects_any.get(value.num))

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------
    def _check_encryption(self) -> None:
        encrypt_value = None
        for section in self._sections:
            if "Encrypt" in section.trailer:
                encrypt_value = section.trailer["Encrypt"]
                break
        if encrypt_value is None:
            # Be defensive only when the trailer itself could not be parsed;
            # otherwise arbitrary stream bytes could cause a false positive.
            if not self._sections and re.search(rb"/Encrypt\b", self.data):
                self._encrypted = True
                self._warn("encrypted")
            return

        self._encrypted = True
        self._warn("encrypted")
        # This API intentionally has no password parameter: only the empty
        # password is accepted, and every encrypted document needs review.
        encryption = self._resolve_any(encrypt_value)
        if not isinstance(encryption, dict):
            self._warn("encryption_unreadable")
            return
        filter_name = _normalise_name(encryption.get("Filter"))
        if filter_name and filter_name != "standard":
            self._warn("encryption_unsupported")

    # ------------------------------------------------------------------
    # Structural traversal (page tree cycles and object-depth limits)
    # ------------------------------------------------------------------
    def _root_refs(self) -> list[Ref]:
        roots: list[Ref] = []
        seen: set[int] = set()
        for section in self._sections:
            root = section.trailer.get("Root")
            if isinstance(root, Ref) and root.num not in seen:
                seen.add(root.num)
                roots.append(root)
        for record in self._records:
            value = record.value
            if isinstance(value, dict) and _normalise_name(value.get("Type")) == "catalog":
                if record.number not in seen:
                    seen.add(record.number)
                    roots.append(Ref(record.number, 0))
        return roots

    def _walk_incrementally_all_versions(self) -> None:
        roots = self._root_refs()

        # Page tree: follow /Kids only, so the ordinary /Parent back-reference
        # does not look like an attack cycle.
        for root_ref in roots:
            catalog = self._resolve(root_ref)
            if not isinstance(catalog, dict):
                continue
            pages = catalog.get("Pages")
            stack: list[tuple[Any, int, frozenset[int]]] = [(pages, 0, frozenset())]
            steps = 0
            while stack and steps < 100000:
                steps += 1
                node, depth, path = stack.pop()
                if isinstance(node, Ref):
                    number = node.num
                    if number in path:
                        self._warn("page_tree_cycle")
                        continue
                    if depth > self.max_depth:
                        self._warn("object_depth")
                        continue
                    node = self._resolve(node)
                    path = path | {number}
                    depth += 1
                if isinstance(node, Stream):
                    node = node.dictionary
                if not isinstance(node, dict):
                    continue
                if _normalise_name(node.get("Type")) == "pages":
                    kids = node.get("Kids")
                    if isinstance(kids, list):
                        for kid in reversed(kids):
                            stack.append((kid, depth, path))

        # General reference traversal catches action /Next chains and cycles
        # in named trees/forms.  /Parent is intentionally ignored.
        stack: list[tuple[Any, int, frozenset[int], str | None]] = [
            (root, 0, frozenset(), None) for root in roots
        ]
        steps = 0
        while stack and steps < 100000:
            steps += 1
            node, depth, path, key = stack.pop()
            if not isinstance(node, Ref):
                for ref, ref_key in _iter_direct_refs(node):
                    if ref_key in {"Parent", "P"}:
                        continue
                    stack.append((ref, depth + 1, path, ref_key))
                continue
            number = node.num
            if number in path:
                # /Kids cycles are reported by the dedicated page-tree walk.
                if key != "Kids":
                    self._warn("object_cycle")
                continue
            if depth > self.max_depth:
                self._warn("object_depth")
                continue
            value = self._resolve(node)
            if value is None:
                continue
            for ref, ref_key in _iter_direct_refs(value):
                if ref_key in {"Parent", "P"}:
                    continue
                stack.append((ref, depth + 1, path | {number}, ref_key))

    # ------------------------------------------------------------------
    # Action inventory
    # ------------------------------------------------------------------
    def _collect_actions(self) -> list[dict[str, Any]]:
        embedded_targets: set[int] = set()
        richmedia_targets: set[int] = set()
        for record in self._records:
            for dictionary in _iter_inline_dicts(record.value):
                if _normalise_name(dictionary.get("Type")) == "filespec":
                    ef = dictionary.get("EF")
                    if isinstance(ef, dict):
                        for target, _key in _iter_direct_refs(ef):
                            embedded_targets.add(target.num)
                if _normalise_name(dictionary.get("Subtype")) == "richmedia":
                    content = dictionary.get("RichMediaContent")
                    if isinstance(content, Ref):
                        richmedia_targets.add(content.num)

        actions: list[dict[str, Any]] = []
        dedupe: set[tuple[int, str, str]] = set()

        def add(number: int, kind: str, detail: str, extra: str = "") -> None:
            detail = detail.strip()
            if len(detail) > 800:
                detail = detail[:797] + "..."
            key = (number, kind, detail)
            if key in dedupe:
                return
            dedupe.add(key)
            reason = self._KIND_REASONS.get(kind, "Potentially dangerous PDF action")
            if kind == "javascript":
                lowered = detail.lower()
                hits = [word for word in self._SCRIPT_KEYWORDS if word in lowered]
                if hits:
                    reason += "; script references " + ", ".join(sorted(set(hits)))
            if extra:
                reason += f"; {extra}"
            actions.append(
                {
                    "object": number,
                    "kind": kind,
                    "detail": detail,
                    "reason": reason,
                    "prohibited": True,
                }
            )

        for record in self._records:
            number = record.number
            value = record.value
            seen_dictionaries: set[int] = set()
            stack: list[Any] = [value]
            while stack:
                current = stack.pop()
                if isinstance(current, Stream):
                    current = current.dictionary
                if isinstance(current, dict):
                    identity = id(current)
                    if identity in seen_dictionaries:
                        continue
                    seen_dictionaries.add(identity)
                    for item in current.values():
                        stack.append(item)

                    action_type = current.get("S")
                    kind = self._ACTION_KINDS.get(_normalise_name(action_type))
                    if kind:
                        detail = self._action_detail(current, kind)
                        add(number, kind, detail)

                    object_type = _normalise_name(current.get("Type"))
                    if object_type == "filespec" and isinstance(current.get("EF"), dict):
                        add(number, "embedded_file", self._file_detail(current))
                    elif object_type == "embeddedfile" and number not in embedded_targets:
                        add(number, "embedded_file", self._file_detail(current))

                    if _normalise_name(current.get("Subtype")) == "richmedia":
                        add(number, "rich_media", self._file_detail(current))
                    elif object_type == "richmedia" and number not in richmedia_targets:
                        add(number, "rich_media", self._file_detail(current))
                elif isinstance(current, list):
                    stack.extend(current)

        return actions

    def _action_detail(self, dictionary: dict[str, Any], kind: str) -> str:
        if kind == "javascript":
            script = self._resolve_any(dictionary.get("JS"))
            if isinstance(script, Stream):
                script = _decode_stream(script)
            if isinstance(script, bytes):
                return _decode_bytes(script)
            if script is None:
                return "JavaScript action without readable script"
            return _decode_bytes(str(script).encode("utf-8", "replace"))

        if kind == "external_link":
            target = dictionary.get("URI")
            if target is None:
                target = dictionary.get("F")
            if target is None:
                target = dictionary.get("D")
            if isinstance(target, bytes):
                return _decode_bytes(target)
            if isinstance(target, Name):
                return str(target)
            return self._compact_value(target)

        if kind == "launch":
            target = dictionary.get("F")
            if target is None:
                target = dictionary.get("Win")
            if target is None:
                target = dictionary.get("Unix")
            return self._compact_value(target)

        if kind in {"submit_form", "import_data"}:
            target = dictionary.get("F")
            if target is None:
                target = dictionary.get("URL")
            return self._compact_value(target)

        if kind == "rich_media":
            target = dictionary.get("RichMediaContent")
            if target is None:
                target = dictionary.get("Subtype")
            return self._compact_value(target)

        return self._compact_value(dictionary.get("S"))

    def _file_detail(self, dictionary: dict[str, Any]) -> str:
        for key in ("UF", "F", "Unix", "DOS", "Mac"):
            value = dictionary.get(key)
            if isinstance(value, bytes):
                return _decode_bytes(value)
            if isinstance(value, Name):
                return str(value)
        if "EF" in dictionary:
            return "embedded file specification"
        return self._compact_value(dictionary.get("Type"))

    def _compact_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return _decode_bytes(value)
        if isinstance(value, Name):
            return str(value)
        if isinstance(value, Ref):
            return f"{value.num} {value.gen} R"
        if isinstance(value, str):
            return _decode_text(value.encode("latin-1", "replace"))
        if isinstance(value, list):
            return "[" + ", ".join(self._compact_value(item) for item in value) + "]"
        if isinstance(value, dict):
            pieces = []
            for key, item in value.items():
                pieces.append(f"/{key} {self._compact_value(item)}")
            return " ".join(pieces)
        return str(value)
