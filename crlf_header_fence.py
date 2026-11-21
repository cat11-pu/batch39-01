class HeaderError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CrlfHeaderFence:
    def __init__(self, allowed_hosts=(), max_headers=50, max_value=4096, max_total=16384):
        pass

    def build(self, headers, filename=None, location=None):
        raise NotImplementedError

    def render(self, headers):
        raise NotImplementedError
import re
from urllib.parse import urlsplit


class HeaderError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# RFC 7230 section 6.1 hop-by-hop headers, plus proxy authentication headers.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# Internal debugging headers that must never leave the edge node.
DEBUG_PREFIXES = ("x-debug-", "x-internal-")

# Carriage return, line feed, NUL and the Unicode line/paragraph separators.
FORBIDDEN_VALUE_CHARS = frozenset(("\r", "\n", "\x00", "\u2028", "\u2029"))

# Token characters allowed in a canonical (lower-cased) header name.
HEADER_NAME_RE = re.compile(r"^[a-z0-9-]+$")

# Obsolete line folding: CRLF (or bare LF) followed by one or more spaces/tabs.
FOLD_RE = re.compile(r"\r?\n[ \t]+")

# RFC 5987 attr-char characters that do not need percent encoding.
ATTR_CHAR_RE = re.compile(rb"[A-Za-z0-9!#$&+\-.^_`|~]")


def _percent_encode(text):
    """Encode a string into an ASCII token using RFC 5987 percent encoding."""
    out = []
    for byte in text.encode("utf-8"):
        char = bytes((byte,))
        if ATTR_CHAR_RE.fullmatch(char):
            out.append(chr(byte))
        else:
            out.append("%{:02X}".format(byte))
    return "".join(out)


class CrlfHeaderFence:
    def __init__(self, allowed_hosts=(), max_headers=50, max_value=4096, max_total=16384):
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self.max_headers = max_headers
        self.max_value = max_value
        self.max_total = max_total

    def _validate_name(self, name):
        if not isinstance(name, str):
            raise HeaderError("invalid_name")
        normalized = name.lower()
        if not HEADER_NAME_RE.fullmatch(normalized):
            raise HeaderError("invalid_name")
        return normalized

    def _is_forbidden(self, name):
        if name in HOP_BY_HOP_HEADERS:
            return True
        return any(name.startswith(prefix) for prefix in DEBUG_PREFIXES)

    def _sanitize_value(self, value):
        """Unfold folded lines, reject line separators, then trim whitespace."""
        if not isinstance(value, str):
            raise HeaderError("invalid_value")
        unfolded = FOLD_RE.sub(" ", value)
        if any(ch in FORBIDDEN_VALUE_CHARS for ch in unfolded):
            raise HeaderError("invalid_value")
        return unfolded.strip(" \t")

    def _encode_value(self, value):
        """Keep ASCII verbatim and percent encode any non-ASCII content."""
        if value.isascii():
            return value
        return _percent_encode(value)

    def _validate_location(self, location):
        location = self._sanitize_value(location)
        parsed = urlsplit(location)
        if parsed.scheme:
            if parsed.scheme not in ("http", "https"):
                raise HeaderError("unsafe_location")
            if (parsed.hostname or "").lower() not in self.allowed_hosts:
                raise HeaderError("unsafe_location")
            return self._encode_value(location)
        if parsed.netloc:
            # Protocol-relative URL such as //host/path.
            if (parsed.hostname or "").lower() not in self.allowed_hosts:
                raise HeaderError("unsafe_location")
            return self._encode_value(location)
        if not location.startswith("/") or "\\" in location or ":" in location.split("/", 1)[0]:
            raise HeaderError("unsafe_location")
        if "//" in location:
            raise HeaderError("unsafe_location")
        if any(segment in (".", "..") for segment in parsed.path.split("/")):
            raise HeaderError("unsafe_location")
        return self._encode_value(location)

    def _build_content_disposition(self, filename):
        filename = self._sanitize_value(filename)
        if not filename or "/" in filename or "\\" in filename:
            raise HeaderError("invalid_value")
        if any(ch in FORBIDDEN_VALUE_CHARS for ch in filename):
            raise HeaderError("invalid_value")
        fallback = filename.encode("ascii", "replace").decode("ascii")
        fallback = fallback.replace("?", "_").replace('"', "_").replace("\\", "_")
        encoded = _percent_encode(filename)
        return "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(fallback, encoded)

    def build(self, headers, filename=None, location=None):
        # name -> merged string, or list of strings for set-cookie.
        merged = {}
        order = []
        connection_tokens = set()

        for raw_name, raw_value in headers:
            name = self._validate_name(raw_name)
            value = self._sanitize_value(raw_value)
            value = self._encode_value(value)

            if name == "connection":
                connection_tokens.update(
                    token.strip(" \t").lower() for token in value.split(",") if token.strip(" \t")
                )

            if self._is_forbidden(name):
                continue

            if name == "set-cookie":
                if name not in merged:
                    merged[name] = []
                    order.append(name)
                merged[name].append(value)
                continue

            if name not in merged:
                merged[name] = value
                order.append(name)
            elif value:
                merged[name] = "{}, {}".format(merged[name], value) if merged[name] else value

        if filename is not None:
            disposition = self._build_content_disposition(filename)
            name = "content-disposition"
            if name not in merged:
                order.append(name)
            merged[name] = disposition

        if location is not None:
            name = "location"
            if name not in merged:
                order.append(name)
            merged[name] = self._validate_location(location)

        emitted = []
        for name in order:
            if name in connection_tokens or self._is_forbidden(name):
                continue
            value = merged[name]
            if isinstance(value, list):
                emitted.extend((name, item) for item in value)
            else:
                emitted.append((name, value))

        if len(emitted) > self.max_headers:
            raise HeaderError("too_many_headers")

        for name, value in emitted:
            if len(value) > self.max_value:
                raise HeaderError("value_too_long")

        total = sum(len(name) + len(value) + 4 for name, value in emitted)
        if total > self.max_total:
            raise HeaderError("total_too_long")

        return emitted

    def render(self, headers):
        lines = []
        for name, value in headers:
            normalized = self._validate_name(name)
            if any(ch in FORBIDDEN_VALUE_CHARS for ch in value):
                raise HeaderError("invalid_value")
            lines.append("{}: {}".format(normalized, value))
        return "\r\n".join(lines) + ("\r\n" if lines else "")
