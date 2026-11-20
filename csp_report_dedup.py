import re
from urllib.parse import urlsplit, urlunsplit


class CspError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


OTHER_DIRECTIVE = "other"
ENFORCE = "enforce"
REPORT_ONLY = "report-only"
REDACTED = "REDACTED"

KNOWN_DIRECTIVES = frozenset(
    [
        "default-src",
        "child-src",
        "connect-src",
        "font-src",
        "frame-src",
        "img-src",
        "manifest-src",
        "media-src",
        "object-src",
        "prefetch-src",
        "script-src",
        "script-src-elem",
        "script-src-attr",
        "style-src",
        "style-src-elem",
        "style-src-attr",
        "worker-src",
        "base-uri",
        "form-action",
        "frame-ancestors",
        "navigate-to",
        "report-to",
        "report-uri",
        "sandbox",
        "upgrade-insecure-requests",
        "require-trusted-types-for",
        "trusted-types",
        "require-sri-for",
        "plugin-types",
        "mixed-content",
    ]
)

SENSITIVE_PATH_RE = re.compile(
    r"(token|secret|password|passwd|credential|auth|session|jwt|apikey|api[_-]?key)",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RAW_SECRET_RE = re.compile(
    r"((?:token|access_token|refresh_token|id_token|secret|password|passwd|"
    r"api[_-]?key|apikey|signature|session|sid|jwt|code)=)[^&\s]+",
    re.IGNORECASE,
)


def _mask_secrets(text):
    text = EMAIL_RE.sub(REDACTED, text)
    return RAW_SECRET_RE.sub(lambda match: match.group(1) + REDACTED, text)


class CspReportDedup:
    def __init__(self, window=120, per_site_limit=100, detail_days=30):
        self.window = int(window)
        self.per_site_limit = int(per_site_limit)
        self.detail_days = int(detail_days)
        self._now = 0
        self._details = {}
        self._quarantine = []
        self._site_minutes = {}
        self._site_stats = {}
        self._counts = {
            "accepted": 0,
            "merged": 0,
            "quarantined": 0,
            "sampled": 0,
            "enforce": 0,
            "report_only": 0,
            "other": 0,
        }

    def ingest(self, reports, now=0):
        self._now = max(self._now, int(now))
        if not isinstance(reports, (list, tuple)):
            reports = [reports]
        for record in reports:
            try:
                normalized = self._normalize_record(record)
            except CspError as error:
                self._quarantine.append(
                    {"record": self._sanitize_raw(record), "reason": error.code}
                )
                self._counts["quarantined"] += 1
                continue
            self._store(normalized, int(now))
        self._purge_expired(self._now)
        return self.snapshot()

    def snapshot(self):
        self._purge_expired(self._now)
        details = sorted(
            self._details.values(),
            key=lambda item: (
                item["site"],
                item["directive"],
                -item["count"],
                item["blocked"],
                item["source"],
            ),
        )
        sites = {}
        for site in sorted(self._site_stats):
            stats = self._site_stats[site]
            sites[site] = {
                "sampled": stats["sampled"],
                "accepted": stats["accepted"],
                "merged": stats["merged"],
                "sampled_count": stats["sampled_count"],
            }
        return {
            "counts": dict(self._counts),
            "sites": sites,
            "details": details,
            "quarantine": list(self._quarantine),
        }

    def _normalize_record(self, record):
        if not isinstance(record, dict):
            raise CspError("invalid_record")

        site = record.get("site")
        if not isinstance(site, str) or not site.strip():
            raise CspError("invalid_site")
        site = site.strip().lower().rstrip("/")
        if not site:
            raise CspError("invalid_site")

        directive = self._normalize_directive(record.get("directive"))

        blocked = record.get("blocked")
        if not isinstance(blocked, str) or not blocked.strip():
            raise CspError("invalid_blocked")
        blocked = self._normalize_blocked(blocked.strip())

        source = record.get("source")
        if source is not None and not isinstance(source, str):
            raise CspError("invalid_source")
        source_path = self._normalize_source(source)

        disposition = record.get("disposition")
        if isinstance(disposition, str) and disposition.strip().lower() == ENFORCE:
            disposition = ENFORCE
        else:
            disposition = REPORT_ONLY

        return {
            "site": site,
            "directive": directive,
            "blocked": blocked,
            "source": source_path,
            "line": self._as_int(record.get("line")),
            "column": self._as_int(record.get("column")),
            "disposition": disposition,
        }

    def _normalize_directive(self, directive):
        if isinstance(directive, str) and directive.strip():
            name = directive.strip().lower().split()[0]
            if name in KNOWN_DIRECTIVES:
                return name
        self._counts["other"] += 1
        return OTHER_DIRECTIVE

    def _normalize_blocked(self, raw):
        parts = urlsplit(raw)
        if parts.scheme and parts.netloc:
            host = parts.hostname or ""
            port = parts.port
            netloc = ("%s:%d" % (host, port)) if port else host
            if parts.username is not None or parts.password is not None:
                netloc = "%s@%s" % (REDACTED, netloc)
            path = self._mask_path(parts.path)
            return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))
        if parts.scheme:
            return "%s:%s" % (parts.scheme.lower(), self._mask_path(parts.path))
        return self._mask_path(parts.path or raw)

    def _normalize_source(self, source):
        if not source or not source.strip():
            return ""
        parts = urlsplit(source.strip())
        if parts.scheme or parts.netloc:
            path = parts.path
        else:
            path = parts.path or source.strip()
        return self._mask_path(path)

    def _mask_path(self, path):
        segments = []
        for segment in path.split("/"):
            if SENSITIVE_PATH_RE.search(segment):
                segments.append(REDACTED)
            else:
                segments.append(EMAIL_RE.sub(REDACTED, segment))
        return "/".join(segments)

    def _as_int(self, value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def _sanitize_raw(self, record):
        if not isinstance(record, dict):
            return {"value": _mask_secrets(str(record))}
        clean = {}
        for key, value in record.items():
            if isinstance(value, str):
                clean[key] = _mask_secrets(value)
            else:
                clean[key] = value
        return clean

    def _store(self, normalized, now):
        site = normalized["site"]
        stats = self._site_stats.setdefault(
            site,
            {"sampled": False, "accepted": 0, "merged": 0, "sampled_count": 0},
        )

        minute_key = (site, now // 60)
        minute_count = self._site_minutes.get(minute_key, 0) + 1
        self._site_minutes[minute_key] = minute_count
        if minute_count > self.per_site_limit:
            stats["sampled"] = True
            stats["sampled_count"] += 1
            self._counts["sampled"] += 1
            return

        disposition = normalized["disposition"]
        count_key = "report_only" if disposition == REPORT_ONLY else ENFORCE
        self._counts[count_key] += 1

        fingerprint = (
            normalized["site"],
            normalized["directive"],
            normalized["blocked"],
            normalized["source"],
        )
        key = (fingerprint, now // self.window)
        detail = self._details.get(key)
        if detail is not None:
            detail["count"] += 1
            detail["last_seen"] = now
            stats["merged"] += 1
            self._counts["merged"] += 1
            return

        self._details[key] = {
            "site": normalized["site"],
            "directive": normalized["directive"],
            "blocked": normalized["blocked"],
            "source": normalized["source"],
            "line": normalized["line"],
            "column": normalized["column"],
            "disposition": disposition,
            "count": 1,
            "first_seen": now,
            "last_seen": now,
        }
        stats["accepted"] += 1
        self._counts["accepted"] += 1

    def _purge_expired(self, now):
        cutoff = now - self.detail_days * 86400
        expired = [
            key
            for key, detail in self._details.items()
            if detail["last_seen"] < cutoff
        ]
        for key in expired:
            del self._details[key]
