import datetime
import re


class CookieError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# RFC 6265 cookie-name: token characters
TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
DOMAIN_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")

KNOWN_ATTRIBUTES = frozenset(
    ("expires", "max-age", "domain", "path", "secure", "httponly", "samesite")
)


def _split_respecting_quotes(text, delimiter):
    """Split on delimiter, but not while inside double quotes."""
    parts = []
    start = 0
    quoted = False
    for index, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif char == delimiter and not quoted:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _unquote(value):
    """Strip one pair of surrounding double quotes; keep the inner bytes."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


class CookiePrefixRules:
    def __init__(self, public_suffixes=(), max_count=50, max_size=4096):
        self.public_suffixes = frozenset(
            suffix.lower().lstrip(".") for suffix in public_suffixes
        )
        self.max_count = max_count
        self.max_size = max_size
        # Internal cookie jar keyed by (name, path, domain) so the total
        # number of stored cookies can be enforced.
        self._jar = {}

    def parse(self, header_value):
        """Parse a Cookie/Set-Cookie header value into cookie dicts.

        Commas separate cookies except inside quoted values and inside an
        Expires date; semicolons separate name=value from its attributes.
        Cookies sharing the same name and path collapse to a single entry,
        with the later occurrence winning.
        """
        if header_value is None:
            return []

        fragments = _split_respecting_quotes(header_value, ",")
        chunks = []
        for fragment in fragments:
            if not fragment.strip():
                continue
            first_segment = fragment.split(";", 1)[0]
            if "=" not in first_segment:
                # Continuation of the previous cookie, e.g. a comma inside an
                # unquoted value or inside an Expires date.
                if chunks:
                    chunks[-1] = chunks[-1] + "," + fragment
                continue
            if chunks:
                name_token = first_segment.split("=", 1)[0].strip().lower()
                if name_token in KNOWN_ATTRIBUTES:
                    chunks[-1] = chunks[-1] + "," + fragment
                    continue
            chunks.append(fragment)

        cookies = []
        index_by_key = {}
        for chunk in chunks:
            for cookie in self._parse_chunk(chunk):
                key = (cookie["name"], cookie["path"])
                if key in index_by_key:
                    cookies[index_by_key[key]] = cookie
                else:
                    index_by_key[key] = len(cookies)
                    cookies.append(cookie)
        return cookies

    def _parse_chunk(self, chunk):
        segments = _split_respecting_quotes(chunk, ";")
        cookies = []
        head = segments[0].strip()
        if not head or "=" not in head:
            return cookies
        head_name, head_value = head.split("=", 1)
        cookie = self._blank_cookie()
        cookie["name"] = head_name.strip()
        cookie["value"] = _unquote(head_value.strip())
        if not cookie["name"]:
            return cookies
        for segment in segments[1:]:
            segment = segment.strip()
            if not segment:
                continue
            if "=" in segment:
                attr_name, attr_value = segment.split("=", 1)
                attr_name = attr_name.strip().lower()
                attr_value = attr_value.strip()
                if cookie is not None and attr_name not in KNOWN_ATTRIBUTES:
                    # Unknown name=value pairs are further cookies per the
                    # Cookie header syntax (names are case sensitive).
                    cookies.append(cookie)
                    cookie = self._blank_cookie()
                    cookie["name"] = attr_name
                    cookie["value"] = _unquote(attr_value)
                    continue
            else:
                attr_name = segment.strip().lower()
                attr_value = True
            if cookie is None:
                continue
            if attr_name == "path":
                cookie["path"] = attr_value or "/"
            elif attr_name == "domain":
                cookie["domain"] = attr_value.lstrip(".").lower() or None
            elif attr_name == "secure":
                cookie["secure"] = True
            elif attr_name == "httponly":
                cookie["httponly"] = True
            elif attr_name == "samesite":
                cookie["samesite"] = self._normalize_samesite(attr_value)
            elif attr_name == "max-age":
                cookie["max_age"] = self._parse_max_age(attr_value)
            elif attr_name == "expires":
                cookie["expires"] = self._parse_expires(attr_value)
            # Unknown attributes are ignored per RFC 6265.
        if cookie is not None:
            cookies.append(cookie)
        return cookies

    @staticmethod
    def _blank_cookie():
        return {
            "name": "",
            "value": "",
            "path": "/",
            "domain": None,
            "secure": False,
            "httponly": False,
            "samesite": None,
            "max_age": None,
            "expires": None,
        }

    def select(self, header_value, name, request_path="/"):
        """Return the value of the cookie whose path best matches.

        Names are case sensitive. Among matching cookies the longest path
        wins, mirroring RFC 6265 section 5.4 ordering.
        """
        best = None
        for cookie in self.parse(header_value):
            if cookie["name"] != name:
                continue
            if not self._path_matches(cookie["path"], request_path):
                continue
            if best is None or len(cookie["path"]) > len(best["path"]):
                best = cookie
        return best["value"] if best is not None else None

    def set_cookie(self, name, value, path="/", domain=None, secure=False, httponly=False, samesite=None, max_age=None, expires=None):
        if not isinstance(name, str) or not TOKEN_RE.match(name):
            raise CookieError("bad_name")
        if not isinstance(value, str):
            raise CookieError("bad_value")

        normalized_path = path if path else "/"
        normalized_domain = self._validate_domain(domain)
        normalized_samesite = self._normalize_samesite(samesite) if samesite else None
        normalized_max_age = self._parse_max_age(max_age) if max_age is not None else None
        normalized_expires = (
            self._parse_expires(expires) if expires is not None else None
        )

        # __Host- prefix: Secure, path "/", and no Domain attribute.
        if name.startswith("__Host-"):
            if normalized_domain is not None:
                raise CookieError("host_prefix_domain")
            if not secure:
                raise CookieError("host_prefix_transport")
            if normalized_path != "/":
                raise CookieError("host_prefix_path")
        # __Secure- prefix: must be sent over a secure transport.
        if name.startswith("__Secure-") and not secure:
            code = (
                "samesite_secure"
                if normalized_samesite == "None"
                else "secure_prefix_transport"
            )
            raise CookieError(code)

        # SameSite=None is only valid together with Secure.
        if normalized_samesite == "None" and not secure:
            raise CookieError("samesite_secure")

        line = self._serialize(
            name,
            value,
            normalized_path,
            normalized_domain,
            bool(secure),
            bool(httponly),
            normalized_samesite,
            normalized_max_age,
            normalized_expires,
        )
        if len(line.encode("utf-8")) > self.max_size:
            raise CookieError("too_large")

        key = (name, normalized_path, normalized_domain)
        if key not in self._jar and len(self._jar) >= self.max_count:
            raise CookieError("too_many")
        self._jar[key] = line
        return line

    def delete(self, name, path, domain=None):
        if not path:
            raise CookieError("delete_needs_path")
        normalized_domain = self._validate_domain(domain)
        key = (name, path, normalized_domain)
        if key not in self._jar:
            raise CookieError("not_found")
        del self._jar[key]
        parts = [
            "{}=".format(name),
            "Path={}".format(path),
        ]
        if normalized_domain is not None:
            parts.append("Domain={}".format(normalized_domain))
        parts.append("Expires=Thu, 01 Jan 1970 00:00:00 GMT")
        parts.append("Max-Age=0")
        return "; ".join(parts)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _validate_domain(self, domain):
        if domain is None:
            return None
        if not isinstance(domain, str) or not domain:
            raise CookieError("bad_domain")
        candidate = domain.strip().lower()
        if candidate.startswith("."):
            candidate = candidate[1:]
        # Ports, empty labels and embedded dots are not legal in a domain.
        if ":" in candidate or candidate.endswith(".") or ".." in candidate:
            raise CookieError("bad_domain")
        labels = candidate.split(".")
        if any(not label or not DOMAIN_LABEL_RE.match(label) for label in labels):
            raise CookieError("bad_domain")
        if candidate in self.public_suffixes:
            raise CookieError("public_suffix")
        return candidate

    @staticmethod
    def _normalize_samesite(value):
        if value is None or value is True:
            return None
        normalized = str(value).strip().lower()
        mapping = {"strict": "Strict", "lax": "Lax", "none": "None"}
        if normalized not in mapping:
            raise CookieError("bad_samesite")
        return mapping[normalized]

    @staticmethod
    def _parse_max_age(value):
        if isinstance(value, bool):
            raise CookieError("bad_max_age")
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not re.fullmatch(r"-?\d+", text):
            raise CookieError("bad_max_age")
        return int(text)

    def _parse_expires(self, value):
        if isinstance(value, datetime.datetime):
            moment = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            moment = datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
        else:
            text = str(value).strip()
            try:
                moment = datetime.datetime.strptime(
                    text, "%a, %d %b %Y %H:%M:%S %Z"
                )
            except ValueError:
                try:
                    moment = datetime.datetime.strptime(
                        text, "%A, %d-%b-%y %H:%M:%S %Z"
                    )
                except ValueError:
                    try:
                        moment = datetime.datetime.fromisoformat(text)
                    except ValueError:
                        raise CookieError("bad_expires")
        if moment.tzinfo is not None:
            moment = moment.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return moment.strftime("%a, %d %b %Y %H:%M:%S GMT")

    @staticmethod
    def _path_matches(cookie_path, request_path):
        if not request_path:
            request_path = "/"
        if cookie_path == request_path:
            return True
        if not request_path.startswith(cookie_path):
            return False
        if cookie_path.endswith("/"):
            return True
        return request_path[len(cookie_path):].startswith("/")

    @staticmethod
    def _serialize(name, value, path, domain, secure, httponly, samesite,
                   max_age, expires):
        needs_quoting = any(
            char in value for char in '";,\\'
        ) or value != value.strip()
        if needs_quoting:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            rendered_value = '"{}"'.format(escaped)
        else:
            rendered_value = value
        parts = ["{}={}".format(name, rendered_value)]
        parts.append("Path={}".format(path))
        if domain is not None:
            parts.append("Domain={}".format(domain))
        if expires is not None:
            parts.append("Expires={}".format(expires))
        if max_age is not None:
            parts.append("Max-Age={}".format(max_age))
        if secure:
            parts.append("Secure")
        if httponly:
            parts.append("HttpOnly")
        if samesite is not None:
            parts.append("SameSite={}".format(samesite))
        return "; ".join(parts)
