import base64
import binascii
import hashlib
import ipaddress
import struct


class AuthorizedKeysError(ValueError):
    def __init__(self, code, line=None):
        super().__init__(code)
        self.code = code
        self.line = line


class AuthorizedKeysFence:
    KNOWN_TYPES = frozenset(
        {
            "ssh-rsa",
            "ssh-dss",
            "ssh-ed25519",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
            "sk-ssh-ed25519@openssh.com",
            "sk-ecdsa-sha2-nistp256@openssh.com",
        }
    )

    VALUE_OPTIONS = frozenset(
        {
            "command",
            "from",
            "environment",
            "permitopen",
            "permitlisten",
            "principals",
            "tunnel",
            "expiry-time",
        }
    )

    FLAG_OPTIONS = frozenset(
        {
            "no-port-forwarding",
            "no-X11-forwarding",
            "no-agent-forwarding",
            "no-pty",
            "no-user-rc",
            "no-touch-required",
            "verify-required",
            "restrict",
        }
    )

    MIN_KEY_BITS = {
        "ssh-rsa": 2048,
        "ssh-dss": 1024,
        "ecdsa-sha2-nistp256": 256,
        "ecdsa-sha2-nistp384": 384,
        "ecdsa-sha2-nistp521": 521,
        "ssh-ed25519": 256,
        "sk-ssh-ed25519@openssh.com": 256,
        "sk-ecdsa-sha2-nistp256@openssh.com": 256,
    }

    FALLBACK_MIN_BITS = 1024

    def __init__(self, max_comment=256):
        self.max_comment = max_comment

    def parse(self, text):
        counts = {
            "empty": 0,
            "invalid": 0,
            "unknown_type": 0,
            "unknown_option": 0,
            "weak": 0,
            "duplicate": 0,
        }
        entries = []
        seen = {}

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                counts["empty"] += 1
                continue
            try:
                entry = self._parse_line(stripped, line_number, counts)
            except AuthorizedKeysError as error:
                counts["invalid"] += 1
                entry = {
                    "line": line_number,
                    "options": {},
                    "key_type": None,
                    "fingerprint": None,
                    "length": None,
                    "comment": "",
                    "alerts": [error.code],
                }
            except Exception:
                counts["invalid"] += 1
                continue

            if entry is None:
                continue

            fingerprint = entry.get("fingerprint")
            dedup_key = (entry["key_type"], fingerprint) if fingerprint else None
            if dedup_key is not None and dedup_key in seen:
                counts["duplicate"] += 1
                continue
            if dedup_key is not None:
                seen[dedup_key] = entry
            entries.append(entry)

        entries.sort(key=lambda item: item["line"])
        return {"entries": entries, "counts": counts}

    def _parse_line(self, stripped, line_number, counts):
        tokens = self._split_tokens(stripped)
        if len(tokens) < 2:
            raise AuthorizedKeysError("malformed_line", line=line_number)

        options_raw, key_tokens = self._extract_options(tokens)
        if len(key_tokens) < 2:
            raise AuthorizedKeysError("malformed_line", line=line_number)

        options, alerts = self._parse_options(options_raw)
        if any(alert.startswith("unknown_option") for alert in alerts):
            counts["unknown_option"] += sum(
                1 for alert in alerts if alert.startswith("unknown_option")
            )

        key_type = key_tokens[0]
        blob = key_tokens[1]
        comment = self._clean_comment(" ".join(key_tokens[2:]))

        if key_type not in self.KNOWN_TYPES:
            counts["unknown_type"] += 1
            alerts.append("unknown_type")

        decoded = self._decode_blob(blob, line_number)
        if decoded is None:
            counts["invalid"] += 1
            alerts.append("invalid_encoding")
            return {
                "line": line_number,
                "options": options,
                "key_type": key_type,
                "fingerprint": None,
                "length": None,
                "comment": comment,
                "alerts": alerts,
            }

        fingerprint = self._fingerprint(decoded)
        length = self._key_length(key_type, decoded)
        minimum = self.MIN_KEY_BITS.get(key_type, self.FALLBACK_MIN_BITS)
        if length < minimum:
            counts["weak"] += 1
            alerts.append("weak_key")

        return {
            "line": line_number,
            "options": options,
            "key_type": key_type,
            "fingerprint": fingerprint,
            "length": length,
            "comment": comment,
            "alerts": alerts,
        }

    @staticmethod
    def _split_tokens(text):
        tokens = []
        current = []
        quote = None
        escaped = False
        for char in text:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                current.append(char)
                escaped = True
            elif quote is not None:
                current.append(char)
                if char == quote:
                    quote = None
            elif char in ('"', "'"):
                current.append(char)
                quote = char
            elif char.isspace():
                if current:
                    tokens.append("".join(current))
                    current = []
            else:
                current.append(char)
        if current:
            tokens.append("".join(current))
        return tokens

    def _extract_options(self, tokens):
        first = tokens[0]
        if first in self.KNOWN_TYPES:
            return None, tokens
        if "=" in first or "," in first:
            return first, tokens[1:]
        if len(tokens) >= 3 and tokens[1] in self.KNOWN_TYPES:
            return first, tokens[1:]
        return None, tokens

    def _parse_options(self, options_raw):
        options = {}
        alerts = []
        if not options_raw:
            return options, alerts

        for part in self._split_option_parts(options_raw):
            if not part:
                continue
            if "=" in part:
                name, value = part.split("=", 1)
                name = name.strip()
                if name == "from":
                    options[name], bad_networks = self._parse_from(value)
                    alerts.extend(
                        "invalid_from:" + item for item in bad_networks
                    )
                elif name in self.VALUE_OPTIONS:
                    options[name] = value
                else:
                    alerts.append("unknown_option:" + name)
            elif part in self.FLAG_OPTIONS:
                options[part] = True
            else:
                alerts.append("unknown_option:" + part)
        return options, alerts

    @staticmethod
    def _split_option_parts(text):
        parts = []
        current = []
        quote = None
        escaped = False
        for char in text:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote is not None:
                if char == quote:
                    quote = None
                else:
                    current.append(char)
            elif char in ('"', "'"):
                quote = char
            elif char == ",":
                parts.append("".join(current))
                current = []
            else:
                current.append(char)
        parts.append("".join(current))
        return parts

    @staticmethod
    def _parse_from(value):
        networks = []
        invalid = []
        for item in value.split(","):
            candidate = item.strip()
            if not candidate:
                continue
            probe = candidate[1:] if candidate.startswith("!") else candidate
            try:
                ipaddress.ip_network(probe, strict=False)
            except ValueError:
                invalid.append(candidate)
            networks.append(candidate)
        return networks, invalid

    def _clean_comment(self, comment):
        cleaned = comment.replace("\r", " ").replace("\n", " ")
        if len(cleaned) > self.max_comment:
            cleaned = cleaned[: self.max_comment]
        return cleaned

    @staticmethod
    def _decode_blob(blob, line_number):
        try:
            decoded = base64.b64decode(blob, validate=True)
        except (ValueError, binascii.Error):
            return None
        if not decoded:
            return None
        return decoded

    @staticmethod
    def _fingerprint(decoded):
        digest = hashlib.sha256(decoded).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")

    @staticmethod
    def _read_string(data, offset):
        if offset + 4 > len(data):
            raise ValueError("truncated key blob")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        if offset + length > len(data):
            raise ValueError("truncated key blob")
        return data[offset : offset + length], offset + length

    def _key_length(self, key_type, decoded):
        try:
            type_name, offset = self._read_string(decoded, 0)
            if key_type == "ssh-rsa" and type_name == b"ssh-rsa":
                _, offset = self._read_string(decoded, offset)
                modulus, _ = self._read_string(decoded, offset)
                return int.from_bytes(modulus, "big").bit_length()
            if key_type == "ssh-dss" and type_name == b"ssh-dss":
                for _ in range(3):
                    _, offset = self._read_string(decoded, offset)
                public, _ = self._read_string(decoded, offset)
                return int.from_bytes(public, "big").bit_length()
            if key_type.startswith("ecdsa-sha2-"):
                curve, offset = self._read_string(decoded, offset)
                point, _ = self._read_string(decoded, offset)
                return {b"nistp256": 256, b"nistp384": 384, b"nistp521": 521}.get(
                    curve, len(point) * 8
                )
            if key_type in ("ssh-ed25519", "sk-ssh-ed25519@openssh.com"):
                public, _ = self._read_string(decoded, offset)
                return len(public) * 8
        except (ValueError, struct.error, IndexError):
            pass
        return len(decoded) * 8
