"""A small, deterministic sudoers parser and matcher.

The module intentionally implements only the policy features needed by the
approval service. Parsing is separated from matching so aliases may refer to
aliases declared later in the configuration or in an included fragment.
"""

from __future__ import annotations

import copy
import fnmatch
import re
import shlex
from dataclasses import dataclass
from typing import Iterable, Sequence


class SudoersError(ValueError):
    def __init__(self, code, line=None):
        super().__init__(code)
        self.code = code
        self.line = line


_ALIAS_KINDS = ("user", "host", "runas", "cmnd")

_ALIAS_DECL_RE = re.compile(
    r"^(User|Host|Runas|Cmnd)_Alias\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$",
    re.IGNORECASE,
)

# Alias names in sudoers are conventionally upper-case. The same convention
# lets us distinguish an unresolved alias reference from a literal account.
_ALIAS_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DIGEST_RE = re.compile(
    r"^(?P<alg>sha224|sha256|sha384|sha512|md5):(?P<hex>[0-9A-Fa-f]+)$",
    re.IGNORECASE,
)
_TAG_NAMES = {
    "nopasswd",
    "passwd",
    "noexec",
    "exec",
    "setenv",
    "nosetenv",
    "log_input",
    "nolog_input",
    "log_output",
    "nolog_output",
    "mail",
    "nomail",
    "follow",
    "nofollow",
    "intercept",
    "nointercept",
}


@dataclass(frozen=True)
class _Pattern:
    value: str
    negated: bool = False


@dataclass(frozen=True)
class _CommandSpec:
    command: str
    args: tuple[str, ...] = ()
    digests: tuple[str, ...] = ()
    negated: bool = False
    password_required: bool = True
    tags: tuple[str, ...] = ()


@dataclass
class _AliasDef:
    kind: str
    name: str
    raw: object
    line: int


@dataclass
class _Rule:
    index: int
    line: int
    raw: str
    users: list[_Pattern]
    hosts: list[_Pattern]
    runas: list[_Pattern] | None
    groups: tuple[str, ...]
    commands: list[_CommandSpec]

    @property
    def user_display(self):
        return _display_pattern(self.users)

    @property
    def host_display(self):
        return _display_pattern(self.hosts)


def _display_pattern(items: Sequence[_Pattern]):
    for item in items:
        if not item.negated:
            return item.value
    return items[0].value if items else ""


def _error(code, line=None):
    raise SudoersError(code, line=line)


def _ends_with_continuation(line: str):
    stripped = line.rstrip()
    count = 0
    for char in reversed(stripped):
        if char != "\\":
            break
        count += 1
    return count % 2 == 1


def _logical_lines(text: str):
    """Yield (first physical line number, logical line)."""

    lines = text.splitlines()
    pos = 0
    while pos < len(lines):
        start = pos + 1
        current = lines[pos]
        while _ends_with_continuation(current) and pos + 1 < len(lines):
            current = current.rstrip()[:-1]
            pos += 1
            current += " " + lines[pos].strip()
        yield start, current
        pos += 1


def _strip_comment(line: str):
    out = []
    quote = None
    escaped = False
    for char in line:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            continue
        if quote is not None:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
    return "".join(out).strip()


def _find_unquoted(text: str, needle: str):
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == needle:
            return index
    return -1


def _split_top_level(text: str):
    parts = []
    start = 0
    quote = None
    escaped = False
    depth = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            part = text[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _tokenize_words(text: str, line=None):
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        _error("syntax_error", line)


def _parse_patterns(text: str, line=None):
    patterns = []
    for part in _split_top_level(text):
        for token in _tokenize_words(part, line):
            if not token:
                continue
            negated = False
            while token.startswith("!"):
                negated = not negated
                token = token[1:]
            if not token:
                _error("syntax_error", line)
            patterns.append(_Pattern(token, negated))
    return patterns


def _is_tag(token: str):
    if not token.endswith(":"):
        return False
    return token[:-1].lower() in _TAG_NAMES


def _parse_command_specs(text: str, line=None):
    specs = []
    password_required = True
    for part in _split_top_level(text):
        tokens = _tokenize_words(part, line)
        if not tokens:
            continue

        command = None
        args = []
        digests = []
        tags = []
        pending_negations = 0

        for token in tokens:
            if _is_tag(token):
                name = token[:-1].lower()
                tags.append(name)
                if name == "nopasswd":
                    password_required = False
                elif name == "passwd":
                    password_required = True
                continue

            if command is None and token and set(token) == {"!"}:
                pending_negations += len(token)
                continue

            if command is None:
                digest_match = _DIGEST_RE.match(token)
                if digest_match:
                    digests.append(
                        digest_match.group("alg").lower()
                        + ":"
                        + digest_match.group("hex").lower()
                    )
                    continue

                while token.startswith("!"):
                    pending_negations += 1
                    token = token[1:]
                if not token:
                    _error("syntax_error", line)
                command = token
            else:
                args.append(token)

        if command is None:
            if digests:
                _error("syntax_error", line)
            continue

        specs.append(
            _CommandSpec(
                command=command,
                args=tuple(args),
                digests=tuple(digests),
                negated=bool(pending_negations % 2),
                password_required=password_required,
                tags=tuple(tags),
            )
        )
    return specs


def _parse_runas(text: str, line=None):
    if not text.startswith("("):
        return None, (), text

    escaped = False
    quote = None
    closing = None
    for index, char in enumerate(text[1:], start=1):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == ")":
            closing = index
            break
    if closing is None:
        _error("syntax_error", line)

    content = text[1:closing]
    rest = text[closing + 1 :].strip()

    if ":" in content:
        user_part, group_part = content.split(":", 1)
    else:
        user_part, group_part = content, ""
    patterns = _parse_patterns(user_part, line)
    groups = tuple(_tokenize_words(group_part, line))
    return patterns, groups, rest


def _split_user_host_fields(text: str, line=None):
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char.isspace():
            previous = text[index - 1] if index else ""
            if previous == ",":
                continue
            users_text = text[:index].strip()
            hosts_text = text[index:].strip()
            if not users_text:
                continue
            if not hosts_text:
                break
            return users_text, hosts_text
    _error("syntax_error", line)


def _parse_rule(text: str, line: int, index: int):
    cleaned = _strip_comment(text)
    if not cleaned:
        return None

    equals = _find_unquoted(cleaned, "=")
    if equals < 0:
        _error("syntax_error", line)

    left = cleaned[:equals].strip()
    right = cleaned[equals + 1 :].strip()
    if not left or not right:
        _error("syntax_error", line)

    users_text, hosts_text = _split_user_host_fields(left, line)
    users = _parse_patterns(users_text, line)
    hosts = _parse_patterns(hosts_text, line)
    if not users or not hosts:
        _error("syntax_error", line)

    runas, groups, command_text = _parse_runas(right, line)
    commands = _parse_command_specs(command_text, line)
    if not commands:
        _error("syntax_error", line)

    return _Rule(
        index=index,
        line=line,
        raw=cleaned,
        users=users,
        hosts=hosts,
        runas=runas,
        groups=groups,
        commands=commands,
    )


def _alias_name_candidate(value: str, kind: str):
    if value.upper() == "ALL":
        return False
    if kind == "cmnd":
        if "/" in value:
            return False
        return _ALIAS_NAME_RE.match(value) is not None
    if kind == "host" and "." in value:
        return False
    return _ALIAS_NAME_RE.match(value) is not None


def _casefold(value: str):
    return value.casefold()


def _glob_regex(pattern: str):
    """Translate a sudoers-style glob with bounded path traversal.

    A single wildcard may cover a directory entry and its immediate child
    (as required by command-argument matching), but it may not descend
    through several path separators.
    """

    out = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            out.append("(?:[^/]*/)?[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            closing = pattern.find("]", index + 1)
            if closing < 0:
                out.append(r"\[")
            else:
                content = pattern[index + 1 : closing]
                if content.startswith("!"):
                    content = "^" + content[1:]
                elif content.startswith("^"):
                    content = "\\" + content
                content = content.replace("\\", "\\\\")
                out.append("[" + content + "]")
                index = closing
        else:
            out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


def _match_path(pattern: str, value: str):
    if pattern == "ALL":
        return True
    return _glob_regex(pattern).match(value) is not None


def _host_label_match(pattern: str, host: str):
    if pattern.upper() == "ALL":
        return True
    if pattern == "*":
        return True
    pattern_labels = pattern.casefold().split(".")
    host_labels = host.casefold().split(".")
    if len(pattern_labels) != len(host_labels):
        return False
    return all(
        fnmatch.fnmatchcase(host_label, pattern_label)
        for pattern_label, host_label in zip(pattern_labels, host_labels)
    )


def _match_pattern_value(kind: str, pattern: str, value: str):
    if pattern.upper() == "ALL":
        return True
    if kind == "host":
        return _host_label_match(pattern, value)
    return fnmatch.fnmatchcase(value.casefold(), pattern.casefold())


def _match_pattern_list(kind: str, patterns: Iterable[_Pattern], value: str):
    positive = False
    for item in patterns:
        if not _match_pattern_value(kind, item.value, value):
            continue
        if item.negated:
            return False
        positive = True
    return positive


def _normalize_digest(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        normalized = {_normalize_digest(item) for item in value if item}
        normalized.discard(None)
        return normalized
    text = str(value).strip().lower()
    if not text:
        return None
    match = _DIGEST_RE.match(text)
    if match:
        return match.group("alg").lower() + ":" + match.group("hex").lower()
    return text


def _digest_matches(required: Sequence[str], supplied):
    if not required:
        return True
    if not supplied:
        return False
    supplied_values = supplied if isinstance(supplied, set) else {supplied}
    supplied_hashes = {
        item.partition(":")[2] for item in supplied_values if ":" in item
    }
    bare_supplied = set()
    for item in supplied_values:
        if ":" not in item:
            bare_supplied.add(item)
    for wanted in required:
        _, _, digest = wanted.partition(":")
        if digest in bare_supplied:
            return True
    for wanted in required:
        _, _, digest = wanted.partition(":")
        if wanted in supplied_values:
            return True
        if digest in supplied_hashes:
            return True
    return False


class SudoersMatch:
    def __init__(self, text, aliases=None):
        self._text = text if isinstance(text, str) else str(text)
        self._includes = {}
        if aliases:
            for name, value in aliases.items():
                if isinstance(value, (list, tuple)):
                    value = "\n".join(str(line) for line in value)
                self._includes[str(name)] = "" if value is None else str(value)

        self._include_order = []
        self._alias_defs = {kind: {} for kind in _ALIAS_KINDS}
        self._alias_order = []
        self._resolved_aliases = {kind: {} for kind in _ALIAS_KINDS}
        self._rules = []

        expanded = self._expand_text(self._text, ())
        self._collect(expanded)
        self._resolve_aliases()
        self._resolve_rules()

    def _expand_text(self, text, stack):
        expanded = []
        for line_number, logical in _logical_lines(text):
            stripped = logical.strip()
            includedir_match = re.match(
                r"^(?:@includedir|#includedir)\s+(.+?)\s*$",
                stripped,
                re.IGNORECASE,
            )
            if includedir_match:
                name = _strip_comment(includedir_match.group(1)).strip()
                if (
                    len(name) >= 2
                    and name[0] == name[-1]
                    and name[0] in ("'", '"')
                ):
                    name = name[1:-1]
                prefix = name.rstrip("/") + "/"
                keys = sorted(
                    key
                    for key in self._includes
                    if key.startswith(prefix)
                    and not key[len(prefix) :].startswith(".")
                    and not key.endswith("~")
                )
                if not keys and name in self._includes:
                    keys = [name]
                if not keys:
                    _error("include_not_found", line_number)
                for key in keys:
                    if key in stack:
                        _error("include_cycle", line_number)
                    self._include_order.append(key)
                    expanded.extend(
                        self._expand_text(
                            self._includes[key], stack + (key,)
                        )
                    )
                continue

            include_match = re.match(
                r"^(?:@include|#include)\s+(.+?)\s*$", stripped, re.IGNORECASE
            )
            if include_match:
                name = _strip_comment(include_match.group(1)).strip()
                if (
                    len(name) >= 2
                    and name[0] == name[-1]
                    and name[0] in ("'", '"')
                ):
                    name = name[1:-1]
                if name in stack:
                    _error("include_cycle", line_number)
                if name not in self._includes:
                    _error("include_not_found", line_number)
                self._include_order.append(name)
                expanded.extend(
                    self._expand_text(self._includes[name], stack + (name,))
                )
                continue
            expanded.append((line_number, logical))
        return expanded

    def _collect(self, lines):
        rule_index = 0
        for line_number, logical in lines:
            cleaned = _strip_comment(logical)
            if not cleaned:
                continue

            alias_match = _ALIAS_DECL_RE.match(cleaned)
            if alias_match:
                kind = alias_match.group(1).lower()
                name = alias_match.group(2)
                value = alias_match.group(3).strip()
                if not value:
                    _error("syntax_error", line_number)
                if kind == "cmnd":
                    raw = _parse_command_specs(value, line_number)
                else:
                    raw = _parse_patterns(value, line_number)
                definition = _AliasDef(
                    kind=kind,
                    name=name,
                    raw=raw,
                    line=line_number,
                )
                key = _casefold(name)
                if key not in self._alias_defs[kind]:
                    self._alias_order.append((kind, key))
                self._alias_defs[kind][key] = definition
                continue

            if cleaned.lower().startswith("defaults"):
                continue

            rule = _parse_rule(logical, line_number, rule_index)
            if rule is not None:
                self._rules.append(rule)
                rule_index += 1

    def _resolve_aliases(self):
        for kind, key in self._alias_order:
            self._resolve_alias(kind, key, ())

    def _resolve_alias(self, kind, key, stack):
        if key in self._resolved_aliases[kind]:
            return self._resolved_aliases[kind][key]
        if key in stack:
            _error("alias_cycle", self._alias_defs[kind][key].line)

        definition = self._alias_defs[kind][key]
        stack = stack + (key,)
        if kind == "cmnd":
            resolved = self._resolve_command_entries(
                definition.raw, kind, stack, definition.line
            )
        else:
            resolved = self._resolve_pattern_entries(
                definition.raw, kind, stack, definition.line
            )
        self._resolved_aliases[kind][key] = resolved
        return resolved

    def _resolve_pattern_entries(self, entries, kind, stack, line):
        resolved = []
        for item in entries:
            key = _casefold(item.value)
            if key in self._alias_defs[kind]:
                nested = self._resolve_alias(kind, key, stack)
                for nested_item in nested:
                    resolved.append(
                        _Pattern(
                            nested_item.value,
                            bool(nested_item.negated) ^ bool(item.negated),
                        )
                    )
            elif _alias_name_candidate(item.value, kind):
                _error("undefined_alias", line)
            else:
                resolved.append(item)
        return resolved

    def _resolve_command_entries(self, entries, kind, stack, line):
        resolved = []
        for item in entries:
            key = _casefold(item.command)
            if key in self._alias_defs["cmnd"]:
                nested = self._resolve_alias("cmnd", key, stack)
                for nested_item in nested:
                    resolved.append(
                        _CommandSpec(
                            command=nested_item.command,
                            args=nested_item.args or item.args,
                            digests=nested_item.digests + item.digests,
                            negated=bool(nested_item.negated) ^ bool(item.negated),
                            password_required=(
                                nested_item.password_required
                                if nested_item.tags
                                else item.password_required
                            ),
                            tags=nested_item.tags or item.tags,
                        )
                    )
            elif _alias_name_candidate(item.command, kind):
                _error("undefined_alias", line)
            else:
                resolved.append(item)
        return resolved

    def _resolve_rules(self):
        for rule in self._rules:
            users = self._resolve_pattern_entries(
                rule.users, "user", (), rule.line
            )
            hosts = self._resolve_pattern_entries(
                rule.hosts, "host", (), rule.line
            )
            runas = None
            if rule.runas is not None:
                runas = self._resolve_pattern_entries(
                    rule.runas, "runas", (), rule.line
                )
            commands = self._resolve_command_entries(
                rule.commands, "cmnd", (), rule.line
            )
            rule.users = users
            rule.hosts = hosts
            rule.runas = runas
            rule.commands = commands

    def _match_runas(self, rule, user, runas):
        if rule.runas is None:
            # As in sudoers, an omitted runas specification means root.
            effective = runas if runas is not None else "root"
            if runas is None:
                return True, effective, False
            return (
                _match_pattern_list("runas", [_Pattern("root")], runas),
                effective,
                False,
            )

        if not rule.runas:
            effective = user
            if runas is None:
                return True, effective, True
            return _casefold(runas) == _casefold(user), effective, True

        if runas is None:
            effective = _display_pattern(rule.runas) or user
            if rule.runas and all(item.negated for item in rule.runas):
                effective = user
            return True, effective, False

        matched = _match_pattern_list("runas", rule.runas, runas)
        return matched, runas, False

    def _match_command(self, spec, command, args, digest):
        if spec.command.upper() != "ALL":
            if not _match_path(spec.command, command):
                return "no_match"
            if len(spec.args) != len(args):
                return "no_match"
            for expected, actual in zip(spec.args, args):
                if not _match_path(expected, actual):
                    return "no_match"

        if spec.digests and not _digest_matches(spec.digests, digest):
            return "digest_missing"
        return "match"

    def check(
        self,
        user,
        host,
        command,
        args=(),
        runas=None,
        digest=None,
    ):
        user = "" if user is None else str(user)
        host = "" if host is None else str(host)
        command = "" if command is None else str(command)
        if isinstance(args, str):
            args = tuple(_tokenize_words(args))
        else:
            args = tuple("" if item is None else str(item) for item in args)
        supplied_digest = _normalize_digest(digest)

        winner = None
        for rule in self._rules:
            if not _match_pattern_list("user", rule.users, user):
                continue
            if not _match_pattern_list("host", rule.hosts, host):
                continue

            runas_ok, effective_runas, runas_defaulted = self._match_runas(
                rule, user, runas
            )
            if not runas_ok:
                continue

            for spec in rule.commands:
                status = self._match_command(spec, command, args, supplied_digest)
                if status == "no_match":
                    continue
                winner = (
                    rule,
                    spec,
                    status,
                    effective_runas,
                    runas_defaulted,
                )

        if winner is None:
            return {
                "allowed": False,
                "password_required": True,
                "runas": user if runas is None else str(runas),
                "runas_defaulted": False,
                "needs_digest": False,
                "negated": False,
                "user": user,
                "host": host,
                "command": command,
                "args": list(args),
                "rule": None,
                "matched_rule": None,
                "rule_index": None,
                "line": None,
                "reason": "no matching rule",
            }

        rule, spec, status, effective_runas, runas_defaulted = winner
        digest_missing = status == "digest_missing"
        allowed = not spec.negated and not digest_missing
        if spec.negated:
            reason = (
                f"last matching rule {rule.index} is negated for "
                f"{command}"
            )
        elif digest_missing:
            reason = (
                f"last matching rule {rule.index} requires a matching "
                f"command digest for {command}"
            )
        else:
            reason = (
                f"last matching rule {rule.index} allows {user} on {host} "
                f"as {effective_runas}"
            )

        result = {
            "allowed": allowed,
            "password_required": bool(spec.password_required),
            "runas": effective_runas,
            "runas_defaulted": bool(runas_defaulted),
            "needs_digest": bool(digest_missing and not spec.negated),
            "negated": bool(spec.negated),
            "user": rule.user_display,
            "host": rule.host_display,
            "command": spec.command,
            "args": list(spec.args),
            "request_user": user,
            "request_host": host,
            "request_command": command,
            "request_args": list(args),
            "rule": rule.raw,
            "matched_rule": rule.raw,
            "rule_index": rule.index,
            "line": rule.line,
            "reason": reason,
        }
        if spec.digests:
            result["digests"] = list(spec.digests)
        return result

    def snapshot(self):
        rules = []
        for rule in self._rules:
            rules.append(
                {
                    "index": rule.index,
                    "line": rule.line,
                    "raw": rule.raw,
                    "users": [
                        {"value": item.value, "negated": item.negated}
                        for item in rule.users
                    ],
                    "hosts": [
                        {"value": item.value, "negated": item.negated}
                        for item in rule.hosts
                    ],
                    "runas": None
                    if rule.runas is None
                    else [
                        {"value": item.value, "negated": item.negated}
                        for item in rule.runas
                    ],
                    "groups": list(rule.groups),
                    "commands": [
                        {
                            "command": item.command,
                            "args": list(item.args),
                            "digests": list(item.digests),
                            "negated": item.negated,
                            "password_required": item.password_required,
                            "tags": list(item.tags),
                        }
                        for item in rule.commands
                    ],
                }
            )

        aliases = {}
        for kind in _ALIAS_KINDS:
            entries = []
            for key, definition in self._alias_defs[kind].items():
                resolved = self._resolved_aliases[kind].get(key, [])
                if kind == "cmnd":
                    value = [
                        {
                            "command": item.command,
                            "args": list(item.args),
                            "digests": list(item.digests),
                            "negated": item.negated,
                        }
                        for item in resolved
                    ]
                else:
                    value = [
                        {"value": item.value, "negated": item.negated}
                        for item in resolved
                    ]
                entries.append(
                    {
                        "name": definition.name,
                        "line": definition.line,
                        "value": value,
                    }
                )
            aliases[kind] = entries

        return copy.deepcopy(
            {
                "rules": rules,
                "aliases": aliases,
                "includes": list(self._include_order),
            }
        )
