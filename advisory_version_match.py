import re


class VersionError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_PRE_SPLIT = re.compile(r"[.\-_]")
_PRE_TOKEN = re.compile(r"\d+|[a-zA-Z]+")

_SEVERITY_ORDER = {
    "none": 0,
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "moderate": 2,
    "high": 3,
    "critical": 4,
}


def _severity_rank(severity):
    if not isinstance(severity, str):
        return -1
    return _SEVERITY_ORDER.get(severity.strip().lower(), -1)


def _parse_prerelease(text):
    if not text:
        raise VersionError("empty_prerelease")
    segments = []
    for part in _PRE_SPLIT.split(text):
        tokens = _PRE_TOKEN.findall(part)
        if not tokens or "".join(tokens) != part:
            raise VersionError("bad_prerelease")
        for token in tokens:
            if token.isdigit():
                segments.append((0, int(token)))
            else:
                segments.append((1, token.lower()))
    return tuple(segments)


class Version:
    __slots__ = ("epoch", "release", "prerelease")

    def __init__(self, epoch, release, prerelease):
        self.epoch = epoch
        self.release = tuple(release)
        self.prerelease = prerelease

    def _cmp(self, other):
        if self.epoch != other.epoch:
            return -1 if self.epoch < other.epoch else 1
        left = self.release
        right = other.release
        width = max(len(left), len(right))
        left = left + (0,) * (width - len(left))
        right = right + (0,) * (width - len(right))
        if left != right:
            return -1 if left < right else 1
        if self.prerelease is None and other.prerelease is None:
            return 0
        if self.prerelease is None:
            return 1
        if other.prerelease is None:
            return -1
        if self.prerelease == other.prerelease:
            return 0
        return -1 if self.prerelease < other.prerelease else 1

    def __eq__(self, other):
        return isinstance(other, Version) and self._cmp(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self._cmp(other) < 0

    def __le__(self, other):
        return self._cmp(other) <= 0

    def __gt__(self, other):
        return self._cmp(other) > 0

    def __ge__(self, other):
        return self._cmp(other) >= 0

    def __hash__(self):
        return hash((self.epoch, self.release, self.prerelease))

    def __repr__(self):
        return "Version(epoch={!r}, release={!r}, prerelease={!r})".format(
            self.epoch, self.release, self.prerelease
        )


def parse_version(text):
    if not isinstance(text, str):
        raise VersionError("not_a_string")
    s = text.strip()
    if not s:
        raise VersionError("empty")
    if "+" in s:
        s = s.split("+", 1)[0]
    epoch = 0
    if "!" in s:
        epoch_text, s = s.split("!", 1)
        if not epoch_text.isdigit():
            raise VersionError("bad_epoch")
        epoch = int(epoch_text)
    if not s:
        raise VersionError("empty")
    prerelease = None
    if "-" in s:
        s, pre_text = s.split("-", 1)
        prerelease = _parse_prerelease(pre_text)
    release = []
    for part in s.split("."):
        if not part.isdigit():
            raise VersionError("non_numeric")
        if len(part) > 1 and part.startswith("0"):
            raise VersionError("leading_zero")
        release.append(int(part))
    return Version(epoch, release, prerelease)


def _wildcard_bounds(text):
    s = text.strip()
    if "+" in s:
        s = s.split("+", 1)[0]
    epoch = 0
    if "!" in s:
        epoch_text, s = s.split("!", 1)
        if not epoch_text.isdigit():
            raise VersionError("bad_epoch")
        epoch = int(epoch_text)
    parts = s.split(".")
    if "*" not in parts:
        raise VersionError("bad_wildcard")
    star = parts.index("*")
    if any(part != "*" for part in parts[star:]):
        raise VersionError("bad_wildcard")
    prefix = []
    for part in parts[:star]:
        if not part.isdigit():
            raise VersionError("non_numeric")
        if len(part) > 1 and part.startswith("0"):
            raise VersionError("leading_zero")
        prefix.append(int(part))
    if not prefix:
        return None, None
    low = Version(epoch, prefix, None)
    high = Version(epoch, prefix[:-1] + [prefix[-1] + 1], None)
    return low, high


def _compile_ranges(ranges):
    intervals = []
    exclusions = []
    pending_low = None
    pending_inclusive = True
    has_pending = False
    for item in ranges or []:
        try:
            op, bound = item
        except (TypeError, ValueError):
            continue
        try:
            if op in (">=", ">"):
                if has_pending:
                    intervals.append([pending_low, pending_inclusive, None, True])
                pending_low = parse_version(bound)
                pending_inclusive = op == ">="
                has_pending = True
            elif op in ("<", "<="):
                upper = parse_version(bound)
                if has_pending:
                    low, low_inc = pending_low, pending_inclusive
                else:
                    low, low_inc = None, True
                intervals.append([low, low_inc, upper, op == "<="])
                has_pending = False
                pending_low = None
            elif op in ("=", "=="):
                if isinstance(bound, str) and "*" in bound:
                    low, high = _wildcard_bounds(bound)
                    intervals.append([low, True, high, False])
                else:
                    point = parse_version(bound)
                    intervals.append([point, True, point, True])
            elif op == "!=":
                if isinstance(bound, str) and "*" in bound:
                    low, high = _wildcard_bounds(bound)
                    exclusions.append([low, True, high, False])
                else:
                    point = parse_version(bound)
                    exclusions.append([point, True, point, True])
        except VersionError:
            continue
    if has_pending:
        intervals.append([pending_low, pending_inclusive, None, True])
    return _merge_intervals(intervals), exclusions


def _interval_sort_key(interval):
    low, low_inc = interval[0], interval[1]
    return (low is not None, low if low is not None else Version(0, (), None), not low_inc)


def _overlaps(first, second):
    if second[0] is None or first[2] is None:
        return True
    order = second[0]._cmp(first[2])
    if order < 0:
        return True
    if order == 0:
        return first[3] or second[1]
    return False


def _merge_intervals(intervals):
    merged = []
    for interval in sorted(intervals, key=_interval_sort_key):
        if merged and _overlaps(merged[-1], interval):
            current = merged[-1]
            if interval[2] is None:
                current[2], current[3] = None, True
            elif current[2] is not None:
                order = interval[2]._cmp(current[2])
                if order > 0 or (order == 0 and interval[3]):
                    current[2], current[3] = interval[2], interval[3]
        else:
            merged.append(list(interval))
    return merged


def _interval_contains(interval, version):
    low, low_inc, high, high_inc = interval
    if low is not None:
        order = version._cmp(low)
        if order < 0 or (order == 0 and not low_inc):
            return False
    if high is not None:
        order = version._cmp(high)
        if order > 0 or (order == 0 and not high_inc):
            return False
    return True


def _is_affected(intervals, exclusions, version):
    if any(_interval_contains(exclusion, version) for exclusion in exclusions):
        return False
    return any(_interval_contains(interval, version) for interval in intervals)


class AdvisoryVersionMatch:
    def __init__(self, rename=None):
        self._rename = {}
        for old, new in (rename or {}).items():
            self._rename[str(old).strip().lower()] = str(new).strip().lower()

    def _normalize_name(self, name):
        if not isinstance(name, str):
            return ""
        name = name.strip().lower()
        seen = set()
        while name in self._rename and name not in seen:
            seen.add(name)
            name = self._rename[name]
        return name

    def match(self, package, version, advisories):
        result = {
            "affected": False,
            "advisories": [],
            "severity": None,
            "isolated": False,
        }
        try:
            target = parse_version(version)
        except VersionError:
            result["isolated"] = True
            return result
        canonical = self._normalize_name(package)
        matched = {}
        for advisory in advisories or []:
            if not isinstance(advisory, dict):
                continue
            if self._normalize_name(advisory.get("package")) != canonical:
                continue
            ranges = advisory.get("ranges")
            fixed = advisory.get("fixed")
            if ranges is None and fixed is not None:
                ranges = [("<", fixed)]
            intervals, exclusions = _compile_ranges(ranges)
            if not _is_affected(intervals, exclusions, target):
                continue
            advisory_id = advisory.get("id")
            severity = advisory.get("severity")
            if advisory_id in matched:
                if _severity_rank(severity) > _severity_rank(matched[advisory_id]):
                    matched[advisory_id] = severity
            else:
                matched[advisory_id] = severity
        if matched:
            result["affected"] = True
            result["advisories"] = sorted(matched, key=str)
            result["severity"] = max(
                matched.values(), key=lambda item: _severity_rank(item)
            )
        return result
