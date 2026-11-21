import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import math
import threading
from datetime import datetime, timezone


class AuditError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class AuditQueryScope:
    DEFAULT_ROLE_RANK = {"agent": 1, "lead": 2, "admin": 3}
    SORT_FIELDS = {"id", "tenant", "actor", "actor_role", "ts", "event", "deleted"}
    SENSITIVE_FIELDS = {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "refresh_token",
        "secret",
        "session",
        "session_id",
        "token",
    }
    IP_FIELDS = {"ip", "source_ip", "client_ip", "remote_addr", "source_address"}
    EMAIL_FIELDS = {"email", "actor_email", "user_email", "contact_email"}
    OUTPUT_FIELDS = ("id", "tenant", "actor", "actor_role", "ts", "event", "ip", "email", "deleted")

    _export_guard = threading.Lock()
    _active_exports = {}

    def __init__(
        self,
        secret,
        tenant,
        role,
        role_rank=None,
        max_days=31,
        page_cap=100,
        export_cap=1000,
        max_concurrent_exports=1,
        actor=None,
        **options,
    ):
        self.secret = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        self.tenant = tenant
        self.role = role
        self.role_rank = dict(role_rank or self.DEFAULT_ROLE_RANK)
        self.max_days = max_days
        self.page_cap = max(1, int(page_cap))
        self.export_cap = max(1, int(export_cap))
        self.max_concurrent_exports = max(1, int(max_concurrent_exports))
        self.actor = actor

        # Optional aliases make the class tolerant of callers using the names
        # from the API description rather than the original constructor.
        if "max_export_rows" in options:
            self.export_cap = max(1, int(options["max_export_rows"]))
        if "export_limit" in options:
            self.export_cap = max(1, int(options["export_limit"]))
        if "page_size_cap" in options:
            self.page_cap = max(1, int(options["page_size_cap"]))

    def query(self, request, records):
        req = self._validate_request(request)
        visible = self._visible_records(req, records)
        total = len(visible)

        page_size = self._page_size(req)
        offset = self._cursor_offset(req, visible)
        page = visible[offset : offset + page_size]

        next_cursor = None
        if offset + page_size < total:
            next_cursor = self._make_cursor(req, offset + page_size)

        return {
            "rows": [self._snapshot(row, req) for row in page],
            "total": total,
            "next_cursor": next_cursor,
        }

    def export(self, request, records):
        req = self._validate_request(request)
        self._require_export_rank()

        key = (self.tenant, self.role)
        with self._export_guard:
            active = self._active_exports.get(key, 0)
            if active >= self.max_concurrent_exports:
                raise AuditError("export_concurrency")
            self._active_exports[key] = active + 1

        try:
            visible = self._visible_records(req, records, apply_time=False)
            truncated = len(visible) > self.export_cap
            rows = visible[: self.export_cap]
            watermark = {
                "actor": self.actor or self.role,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "tenant": self.tenant,
                "query_digest": self._query_digest(req),
                "rows": len(rows),
                "truncated": truncated,
            }
            return {
                "rows": [self._snapshot(row, req) for row in rows],
                "truncated": truncated,
                "watermark": watermark,
            }
        finally:
            with self._export_guard:
                remaining = self._active_exports.get(key, 1) - 1
                if remaining <= 0:
                    self._active_exports.pop(key, None)
                else:
                    self._active_exports[key] = remaining

    def _validate_request(self, request):
        if not isinstance(request, dict):
            raise AuditError("bad_request")

        req_tenant = request.get("tenant")
        if req_tenant is not None and req_tenant != self.tenant:
            raise AuditError("tenant_mismatch")

        start = request.get("start", 0)
        end = request.get("end", start + self.max_days)
        if not self._is_number(start) or not self._is_number(end):
            raise AuditError("time_range")
        if end < start or end - start > self.max_days:
            raise AuditError("time_range")

        self._sort_spec(request.get("sort", "-ts"))

        ids = request.get("ids", [])
        if ids is None:
            ids = []
        if not isinstance(ids, (list, tuple, set)):
            raise AuditError("bad_request")

        req = dict(request)
        req["start"] = start
        req["end"] = end
        req["ids"] = list(ids)
        req["_sort_field"], req["_sort_desc"] = self._sort_spec(req.get("sort", "-ts"))
        return req

    def _visible_records(self, req, records, apply_time=True):
        records = list(records or [])

        requested_ids = {str(item) for item in req["ids"]}
        if requested_ids:
            for item in records:
                if not isinstance(item, dict):
                    continue
                if str(item.get("id")) in requested_ids and item.get("tenant") != self.tenant:
                    raise AuditError("cross_tenant_id")

        caller_rank = self.role_rank.get(self.role)
        if caller_rank is None:
            caller_rank = 0

        keyword = req.get("keyword") or ""
        if keyword is not None and not isinstance(keyword, str):
            keyword = str(keyword)

        include_deleted = bool(req.get("include_deleted", False))
        if include_deleted and caller_rank < max(self.role_rank.values(), default=0):
            include_deleted = False

        visible = []
        for item in records:
            if not isinstance(item, dict):
                continue
            if item.get("tenant") != self.tenant:
                continue
            if requested_ids and str(item.get("id")) not in requested_ids:
                continue
            if item.get("deleted") and not include_deleted:
                continue

            actor_role = item.get("actor_role")
            actor_rank = self.role_rank.get(actor_role)
            if actor_rank is None or actor_rank > caller_rank:
                continue

            if apply_time:
                ts = item.get("ts")
                if not self._is_number(ts) or ts < req["start"] or ts > req["end"]:
                    continue

            if keyword and not self._matches_keyword(item, keyword):
                continue

            visible.append(item)

        # Sort by id first so ties are deterministic regardless of input order.
        visible.sort(key=lambda item: str(item.get("id", "")))
        field = req["_sort_field"]
        visible.sort(
            key=lambda item: self._sort_key(item, field),
            reverse=req["_sort_desc"],
        )
        return visible

    def _page_size(self, req):
        value = req.get("page_size", self.page_cap)
        if value is None:
            value = self.page_cap
        try:
            size = int(value)
        except (TypeError, ValueError):
            raise AuditError("page_size")
        if size < 1:
            raise AuditError("page_size")
        return min(size, self.page_cap)

    def _require_export_rank(self):
        required = max(self.role_rank.values(), default=0)
        if self.role_rank.get(self.role, 0) < required:
            raise AuditError("export_forbidden")

    def _sort_spec(self, sort):
        if sort is None or sort == "":
            sort = "ts"
        if not isinstance(sort, str):
            raise AuditError("sort_not_allowed")
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        if field not in self.SORT_FIELDS:
            raise AuditError("sort_not_allowed")
        return field, descending

    def _sort_key(self, item, field):
        value = item.get(field)
        if value is None:
            return (1, 0.0) if field == "ts" else (1, "")
        if field == "ts":
            if self._is_number(value):
                return (0, value)
            return (2, 0.0)
        return (0, str(value).casefold())

    def _matches_keyword(self, item, keyword):
        needle = keyword.casefold()
        for key, value in item.items():
            if key.casefold() in self.SENSITIVE_FIELDS:
                continue
            if value is not None and needle in str(value).casefold():
                return True
        return False

    def _cursor_offset(self, req, visible):
        cursor = req.get("cursor")
        if cursor is None or cursor == "":
            return 0
        if not isinstance(cursor, str):
            raise AuditError("bad_cursor")

        try:
            payload_part, signature_part = cursor.split(".", 1)
            payload_bytes = self._b64decode(payload_part)
            signature = self._b64decode(signature_part)
        except (ValueError, TypeError, binascii.Error):
            raise AuditError("bad_cursor")

        expected = hmac.new(self.secret, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuditError("bad_cursor")

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise AuditError("bad_cursor")

        if not isinstance(payload, dict):
            raise AuditError("bad_cursor")
        if payload.get("digest") != self._query_digest(req):
            raise AuditError("bad_cursor")

        offset = payload.get("offset")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise AuditError("bad_cursor")
        return offset

    def _make_cursor(self, req, offset):
        payload = {
            "offset": offset,
            "digest": self._query_digest(req),
        }
        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        signature = hmac.new(self.secret, payload_bytes, hashlib.sha256).digest()
        return self._b64encode(payload_bytes) + "." + self._b64encode(signature)

    def _query_digest(self, req):
        conditions = {
            "tenant": self.tenant,
            "role": self.role,
            "start": req.get("start"),
            "end": req.get("end"),
            "sort": [req.get("_sort_field"), bool(req.get("_sort_desc"))],
            "keyword": req.get("keyword") or "",
            "ids": sorted(str(item) for item in req.get("ids", [])),
            "page_size": self._page_size(req),
            "include_deleted": bool(req.get("include_deleted", False)),
        }
        raw = json.dumps(
            conditions, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _snapshot(self, record, req):
        include_sensitive = bool(req.get("include_sensitive", False))
        if include_sensitive and self.role_rank.get(self.role, 0) < max(
            self.role_rank.values(), default=0
        ):
            include_sensitive = False

        cleaned = {}
        for key, value in record.items():
            lower = key.casefold()
            if not include_sensitive and self._is_sensitive_key(lower):
                continue
            cleaned[key] = value

        for key in list(cleaned):
            lower = key.casefold()
            if lower in self.IP_FIELDS:
                cleaned[key] = self._mask_ip(cleaned[key])
            elif lower in self.EMAIL_FIELDS:
                cleaned[key] = self._mask_email(cleaned[key])

        ordered = {}
        for key in self.OUTPUT_FIELDS:
            if key in cleaned:
                ordered[key] = cleaned[key]
        for key in sorted(cleaned):
            if key not in ordered:
                ordered[key] = cleaned[key]
        return ordered

    def _is_sensitive_key(self, key):
        if key in self.SENSITIVE_FIELDS:
            return True
        return any(
            key.endswith(suffix)
            for suffix in ("_token", "_secret", "_password", "_credential", "_api_key")
        )

    def _mask_ip(self, value):
        if value is None:
            return value
        try:
            address = ipaddress.ip_address(str(value))
        except ValueError:
            return "***"
        prefix = 24 if address.version == 4 else 64
        return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address)

    def _mask_email(self, value):
        if value is None:
            return value
        text = str(value)
        if "@" not in text:
            return "***"
        local, domain = text.split("@", 1)
        return (local[:1] or "*") + "***@" + domain

    @staticmethod
    def _is_number(value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if isinstance(value, float) and not math.isfinite(value):
            return False
        return True

    @staticmethod
    def _b64encode(raw):
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _b64decode(text):
        padding = "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(text + padding)
