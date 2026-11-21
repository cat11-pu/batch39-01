import ipaddress
import re
from dataclasses import dataclass


class CidrError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_ASCII_DIGITS = re.compile(r"[0-9]+\Z")
_DECIMAL = re.compile(r"[0-9]+\Z")
_HEX = re.compile(r"0[xX][0-9A-Fa-f]+\Z")
_BARE_HEX = re.compile(r"[0-9A-Fa-f]+\Z")
_ZONE_ID = re.compile(r"[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class _Rule:
    scope: str
    index: int
    version: int
    start: int
    end: int
    prefix: int
    network: str


def _clean(value, code):
    if not isinstance(value, str):
        raise CidrError(code)
    cleaned = "".join(value.split())
    if not cleaned:
        raise CidrError(code)
    return cleaned


def _validate_port(port, code):
    if not _ASCII_DIGITS.fullmatch(port):
        raise CidrError(code)
    try:
        number = int(port, 10)
    except ValueError:
        raise CidrError(code) from None
    if number > 65535:
        raise CidrError(code)


def _split_host_and_port(token, code):
    if token.startswith("["):
        close = token.find("]")
        if close < 0:
            raise CidrError(code)
        host = token[1:close]
        rest = token[close + 1 :]
        if rest:
            if not rest.startswith(":"):
                raise CidrError(code)
            _validate_port(rest[1:], code)
        if "[" in host or "]" in host:
            raise CidrError(code)
        return host

    if "[" in token or "]" in token:
        raise CidrError(code)

    if token.count(":") == 1:
        host, port = token.rsplit(":", 1)
        if not host:
            raise CidrError(code)
        _validate_port(port, code)
        return host

    return token


def _strip_zone_id(host, code):
    if "%" not in host:
        return host, False
    if host.count("%") != 1:
        raise CidrError(code)
    address, zone = host.split("%", 1)
    if not address or not zone or not _ZONE_ID.fullmatch(zone):
        raise CidrError(code)
    return address, True


def _number_from_host(host, version, code):
    try:
        if _HEX.fullmatch(host):
            number = int(host, 16)
        elif _DECIMAL.fullmatch(host):
            number = int(host, 10)
        elif _BARE_HEX.fullmatch(host) and re.search(r"[A-Fa-f]", host):
            number = int(host, 16)
        else:
            raise CidrError(code)
    except ValueError:
        raise CidrError(code) from None

    if number > 0xFFFFFFFF:
        return 6, number
    if version is None:
        return 4, number
    return version, number


def _parse_address_parts(value, code, convert_mapped):
    token = _clean(value, code)
    host = _split_host_and_port(token, code)
    host, had_zone = _strip_zone_id(host, code)
    if not host:
        raise CidrError(code)

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is None:
        if had_zone:
            raise CidrError(code)
        version, number = _number_from_host(host, None, code)
        if number > 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:
            raise CidrError(code)
        if version == 6 and number > 0xFFFFFFFF:
            return 6, number
        return 4, number

    if had_zone and address.version != 6:
        raise CidrError(code)

    if (
        convert_mapped
        and address.version == 6
        and address.ipv4_mapped is not None
    ):
        return 4, int(address.ipv4_mapped)

    return address.version, int(address)


def _max_prefix(version):
    return 32 if version == 4 else 128


def _network_text(version, start, prefix):
    address = (
        ipaddress.IPv4Address(start)
        if version == 4
        else ipaddress.IPv6Address(start)
    )
    return f"{address}/{prefix}"


def _parse_network(value, scope, index, allow_default_route):
    text = _clean(value, "invalid_network")
    if text.count("/") > 1:
        raise CidrError("invalid_network")

    if "/" in text:
        host, prefix_text = text.rsplit("/", 1)
    else:
        host, prefix_text = text, None

    if not host:
        raise CidrError("invalid_network")

    version, address = _parse_address_parts(
        host, "invalid_network", convert_mapped=False
    )
    width = _max_prefix(version)

    if prefix_text is None:
        prefix = width
    else:
        if not _ASCII_DIGITS.fullmatch(prefix_text):
            raise CidrError("invalid_prefix")
        try:
            prefix = int(prefix_text, 10)
        except ValueError:
            raise CidrError("invalid_prefix") from None
        if prefix > width:
            raise CidrError("invalid_prefix")

    host_bits = width - prefix
    start = (address >> host_bits) << host_bits
    end = start | ((1 << host_bits) - 1)

    if version == 6 and prefix >= 96 and (start >> 32) == 0xFFFF:
        version = 4
        prefix -= 96
        start &= 0xFFFFFFFF
        end &= 0xFFFFFFFF

    if prefix == 0 and not allow_default_route:
        raise CidrError("default_route")

    return _Rule(
        scope=scope,
        index=index,
        version=version,
        start=start,
        end=end,
        prefix=prefix,
        network=_network_text(version, start, prefix),
    )


def _as_rule_values(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _best_match(rules, version, address):
    matches = [
        rule
        for rule in rules
        if rule.version == version and rule.start <= address <= rule.end
    ]
    if not matches:
        return None
    return max(matches, key=lambda rule: (rule.prefix, -rule.index))


class CidrScopeResolver:
    def __init__(self, allow=(), deny=(), allow_default_route=False):
        self._allow = [
            _parse_network(value, "allow", index, allow_default_route)
            for index, value in enumerate(_as_rule_values(allow))
        ]
        self._deny = [
            _parse_network(value, "deny", index, allow_default_route)
            for index, value in enumerate(_as_rule_values(deny))
        ]

    def resolve(self, address):
        version, number = _parse_address_parts(
            address, "invalid_address", convert_mapped=True
        )
        canonical = (
            str(ipaddress.IPv4Address(number))
            if version == 4
            else str(ipaddress.IPv6Address(number))
        )

        denied = _best_match(self._deny, version, number)
        if denied is not None:
            return {
                "allowed": False,
                "address": canonical,
                "network": denied.network,
                "rule": denied.index,
                "reason": "denied",
            }

        allowed = _best_match(self._allow, version, number)
        if allowed is not None:
            return {
                "allowed": True,
                "address": canonical,
                "network": allowed.network,
                "rule": allowed.index,
                "reason": "allowed",
            }

        return {
            "allowed": False,
            "address": canonical,
            "network": None,
            "rule": None,
            "reason": "no_match",
        }

    def snapshot(self):
        allow = []
        by_version = {}
        for rule in self._allow:
            by_version.setdefault(rule.version, []).append((rule.start, rule.end))

        for version, intervals in by_version.items():
            intervals.sort()
            merged = []
            for start, end in intervals:
                if merged and start <= merged[-1][1] + 1:
                    if end > merged[-1][1]:
                        merged[-1] = (merged[-1][0], end)
                else:
                    merged.append((start, end))

            address_type = (
                ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
            )
            for start, end in merged:
                for network in ipaddress.summarize_address_range(
                    address_type(start), address_type(end)
                ):
                    allow.append(
                        (
                            version,
                            int(network.network_address),
                            network.prefixlen,
                            f"{network.network_address}/{network.prefixlen}",
                        )
                    )

        allow.sort(key=lambda item: (item[0], item[1], item[2]))

        deny = sorted(
            self._deny,
            key=lambda rule: (
                rule.version,
                rule.start,
                rule.prefix,
                rule.end,
                rule.index,
            ),
        )
        return {
            "allow": [item[3] for item in allow],
            "deny": [rule.network for rule in deny],
        }
