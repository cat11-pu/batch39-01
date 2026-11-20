import hashlib
import re


class FormSegmentError(ValueError):
    def __init__(self, code, field=None):
        super().__init__(code)
        self.code = code
        self.field = field


class FormSegmentFence:
    def __init__(self, max_segments=100, max_segment_bytes=1024 * 1024, max_header_lines=20, max_total_bytes=8 * 1024 * 1024, max_nesting=1):
        self.max_segments = max_segments
        self.max_segment_bytes = max_segment_bytes
        self.max_header_lines = max_header_lines
        self.max_total_bytes = max_total_bytes
        self.max_nesting = max_nesting

    def parse(self, body, content_type):
        body = bytes(body)

        if len(body) > self.max_total_bytes:
            raise FormSegmentError("request_too_large")

        boundary = self._boundary_from_content_type(content_type)
        delimiter = b"--" + boundary
        if not body.startswith(delimiter):
            raise FormSegmentError("invalid_boundary")

        manifest = []
        seen_names = set()
        opening_tail = body[len(delimiter):]
        if opening_tail.startswith(b"--"):
            remainder = opening_tail[2:]
            if remainder not in (b"", b"\r\n", b"\n"):
                raise FormSegmentError("invalid_boundary")
            return manifest
        if not opening_tail.startswith(b"\r\n"):
            raise FormSegmentError("invalid_boundary")
        position = len(delimiter) + 2

        while True:
            end = body.find(delimiter, position)
            if end < 0:
                raise FormSegmentError("truncated")

            part_bytes = body[position:end]
            tail = body[end + len(delimiter):]
            if not part_bytes.endswith(b"\r\n"):
                raise FormSegmentError("invalid_boundary")
            part_bytes = part_bytes[:-2]

            if len(manifest) >= self.max_segments:
                raise FormSegmentError("too_many_segments")

            header_end = part_bytes.find(b"\r\n\r\n")
            if header_end < 0:
                raise FormSegmentError("invalid_header")

            raw_headers = part_bytes[:header_end]
            content = part_bytes[header_end + 4:]

            if len(content) > self.max_segment_bytes:
                raise FormSegmentError("segment_too_large")

            header_lines, has_bare_newline = self._unfold_headers(raw_headers)
            if len(header_lines) > self.max_header_lines:
                raise FormSegmentError("too_many_headers")

            try:
                decoded_lines = [line.decode("utf-8", errors="strict") for line in header_lines]
            except UnicodeDecodeError:
                raise FormSegmentError("invalid_encoding")

            headers = self._parse_header_lines(decoded_lines)
            disposition = None
            for key, value in headers:
                if key.lower() == "content-disposition":
                    disposition = value
                    break
            if disposition is None:
                raise FormSegmentError("invalid_header")

            parameters = self._parse_disposition(disposition)
            name = parameters.get("name")
            if name is None:
                raise FormSegmentError("invalid_header")

            filename = parameters.get("filename")
            if filename is not None:
                self._validate_filename(filename)

            if name in seen_names:
                raise FormSegmentError("duplicate_field", field=name)

            if has_bare_newline:
                raise FormSegmentError("invalid_header")

            seen_names.add(name)
            manifest.append({
                "name": name,
                "filename": filename if filename is not None else "",
                "size": len(content),
                "digest": hashlib.sha256(content).hexdigest(),
            })

            if tail.startswith(b"--"):
                remainder = tail[2:]
                if remainder not in (b"", b"\r\n", b"\n"):
                    raise FormSegmentError("invalid_boundary")
                break
            if not tail.startswith(b"\r\n"):
                raise FormSegmentError("invalid_boundary")
            position = end + len(delimiter) + 2

        return manifest

    @staticmethod
    def _boundary_from_content_type(content_type):
        if isinstance(content_type, bytes):
            content_type = content_type.decode("ascii", errors="strict")
        if not isinstance(content_type, str):
            raise FormSegmentError("invalid_boundary")

        for chunk in content_type.split(";")[1:]:
            chunk = chunk.strip()
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            if key.strip().lower() != "boundary":
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1].replace("\\\\", "\\").replace('\\"', '"')
            value = value.strip()
            if not value:
                raise FormSegmentError("invalid_boundary")
            return value.encode("ascii", errors="strict")

        raise FormSegmentError("invalid_boundary")

    @staticmethod
    def _unfold_headers(raw_headers):
        has_bare_newline = b"\n" in raw_headers.replace(b"\r\n", b"")
        unfolded = re.sub(rb"\r\n[ \t]+", b" ", raw_headers)
        lines = [line for line in unfolded.split(b"\r\n") if line != b""]
        return lines, has_bare_newline

    @staticmethod
    def _parse_header_lines(lines):
        headers = []
        for line in lines:
            if ":" not in line:
                raise FormSegmentError("invalid_header")
            key, value = line.split(":", 1)
            key = key.strip()
            if not key:
                raise FormSegmentError("invalid_header")
            headers.append((key, value.strip()))
        return headers

    @staticmethod
    def _split_disposition(value):
        pieces = []
        current = []
        in_quotes = False
        escaped = False
        for char in value:
            if escaped:
                current.append(char)
                escaped = False
                continue
            if char == "\\":
                current.append(char)
                escaped = True
                continue
            if char == '"':
                in_quotes = not in_quotes
                current.append(char)
                continue
            if char == ";" and not in_quotes:
                pieces.append("".join(current))
                current = []
                continue
            current.append(char)
        if in_quotes:
            raise FormSegmentError("invalid_header")
        pieces.append("".join(current))
        return pieces

    def _parse_disposition(self, value):
        pieces = self._split_disposition(value)
        if not pieces or pieces[0].strip().lower() != "form-data":
            raise FormSegmentError("invalid_header")

        parameters = {}
        for piece in pieces[1:]:
            if "=" not in piece:
                if piece.strip():
                    raise FormSegmentError("invalid_header")
                continue
            key, raw_value = piece.split("=", 1)
            key = key.strip().lower()
            raw_value = raw_value.strip()
            if len(raw_value) >= 2 and raw_value[0] == '"' and raw_value[-1] == '"':
                parsed_value = self._unquote(raw_value[1:-1])
            else:
                parsed_value = raw_value
            parameters[key] = parsed_value
        return parameters

    @staticmethod
    def _unquote(value):
        result = []
        escaped = False
        for char in value:
            if escaped:
                if char not in ('"', "\\"):
                    result.append("\\")
                result.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            else:
                result.append(char)
        if escaped:
            raise FormSegmentError("invalid_header")
        return "".join(result)

    @staticmethod
    def _validate_filename(filename):
        if "/" in filename or "\\" in filename:
            raise FormSegmentError("invalid_filename")
        for char in filename:
            code = ord(char)
            if code < 0x20 or code == 0x7f:
                raise FormSegmentError("invalid_filename")
