"""Player-local reset boundaries with UTC storage.

The class deliberately keeps all persisted instants as integer UTC epoch
seconds. Human-readable values in snapshots are ISO-8601 strings in UTC, so a
snapshot can be compared safely between regions without knowing the machine's
local timezone.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Mapping
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
DAY = 86400
_PERIOD_ALIASES = {
    "daily": "daily",
    "day": "daily",
    "weekly": "weekly",
    "week": "weekly",
    "monthly": "monthly",
    "month": "monthly",
}
_UTC_NAMES = {"UTC", "Z", "GMT", "ETC/UTC", "ETC/GMT"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OFFSET_RE = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.I)


class _RewardStates(dict):
    """Backfill state mapping with small compatibility aliases."""

    def __contains__(self, key):
        if key == "pending":
            return True
        if super().__contains__(key):
            return True
        return any(key in values for values in self.values())

    def __getitem__(self, key):
        if key == "pending":
            key = "unclaimed"
        return super().__getitem__(key)


class DailyResetBoundary:
    """Calculate and apply daily, weekly and monthly reset boundaries.

    Parameters
    ----------
    reset_hour:
        Default local hour at which a player's reset happens.
    tzdb:
        Optional injected timezone database. It may be a mapping of timezone
        name to ``tzinfo`` (or another name), a callable, or an object exposing
        ``get``. When omitted, :mod:`zoneinfo` is used.
    """

    def __init__(self, reset_hour=5, tzdb=None, **config):
        self.reset_hour = self._validate_hour(reset_hour)
        self.tzdb = tzdb
        self.default_timezone = config.pop(
            "timezone", config.pop("tz_name", config.pop("default_timezone", "UTC"))
        )
        self.reward_ttl_days = max(0, int(config.pop("reward_ttl_days", 7)))
        self.max_future_skew = max(0, int(config.pop("max_future_skew", 300)))
        self.max_forward_jump = max(
            0, int(config.pop("max_forward_jump", 31 * DAY))
        )
        self.initial_boundary = int(config.pop("initial_boundary", 0))

        self._users = {}
        self._anomalies = []
        self._lock = threading.RLock()

        for user, binding in config.pop("users", {}).items():
            if isinstance(binding, Mapping):
                self.bind_user(
                    user,
                    binding.get("timezone", binding.get("tz_name")),
                    binding.get("reset_hour"),
                )
            else:
                self.bind_user(user, binding)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def anomalies(self):
        """Return a copy of recorded clock/boundary anomalies."""
        with self._lock:
            return [dict(item) for item in self._anomalies]

    def bind_user(self, user, tz_name=None, reset_hour=None, timezone=None):
        """Bind (or explicitly rebind) a player's timezone and reset hour.

        Rebinding only affects future boundaries. The last applied boundary is
        retained as a UTC instant, so a device timezone change cannot rewrite
        already processed history.
        """
        tz_arg = timezone if timezone is not None else tz_name
        with self._lock:
            key = self._user_key(user)
            state = self._users.get(key)
            if state is None:
                tz_name_resolved = tz_arg or self.default_timezone
                tz, canonical = self._resolve_timezone(tz_name_resolved)
                state = {
                    "user": user,
                    "timezone": canonical,
                    "tz": tz,
                    "reset_hour": self._validate_hour(
                        self.reset_hour if reset_hour is None else reset_hour
                    ),
                    "request_seen": None,
                    "periods": {},
                }
                self._users[key] = state
            else:
                if tz_arg is not None:
                    tz, canonical = self._resolve_timezone(tz_arg)
                    state["timezone"] = canonical
                    state["tz"] = tz
                if reset_hour is not None:
                    state["reset_hour"] = self._validate_hour(reset_hour)
            return self._public_user_state(key, state)

    # Common aliases used by game services.
    bind = bind_user
    set_user_timezone = bind_user

    def boundaries(
        self,
        last_utc,
        now_utc,
        tz_name="UTC",
        period="daily",
        reset_hour=None,
        kind=None,
        **kwargs,
    ):
        """Return every reset boundary in ``(last_utc, now_utc]`` as UTC epochs.

        Dates are advanced in the player's local calendar, then each local
        wall-clock reset is converted back to UTC. This makes DST changes
        correct: a 23/25 hour local day still yields exactly one boundary, and
        a nonexistent local time is moved to the first valid instant after the
        gap instead of being skipped.
        """
        if kind is not None and period == "daily":
            period = kind
        if "granularity" in kwargs and period == "daily":
            period = kwargs.pop("granularity")
        period = self._normalise_period(period)

        last = self._as_epoch(last_utc, name="last_utc")
        now = self._as_epoch(now_utc, name="now_utc")
        with self._lock:
            if now < last:
                self._record_anomaly(
                    "clock_rollback",
                    requested=now,
                    reference=last,
                    message="now_utc precedes last_utc",
                )
                raise ValueError("clock rollback: now_utc is before last_utc")

            tz, _ = self._resolve_timezone(tz_name)
            hour = self._validate_hour(
                self.reset_hour if reset_hour is None else reset_hour
            )
            return self._boundaries_between(last, now, tz, hour, period)

    def daily_boundaries(self, last_utc, now_utc, tz_name="UTC", reset_hour=None):
        return self.boundaries(
            last_utc, now_utc, tz_name, period="daily", reset_hour=reset_hour
        )

    def weekly_boundaries(self, last_utc, now_utc, tz_name="UTC", reset_hour=None):
        return self.boundaries(
            last_utc, now_utc, tz_name, period="weekly", reset_hour=reset_hour
        )

    def monthly_boundaries(self, last_utc, now_utc, tz_name="UTC", reset_hour=None):
        return self.boundaries(
            last_utc, now_utc, tz_name, period="monthly", reset_hour=reset_hour
        )

    week_boundaries = weekly_boundaries
    month_boundaries = monthly_boundaries

    def claim(
        self,
        user,
        now_utc,
        claimed=(),
        tz_name=None,
        timezone=None,
        reset_hour=None,
        period="daily",
        **kwargs,
    ):
        """Apply one player's pending resets and return a backfill summary.

        ``claimed`` may be a mapping or iterable of already claimed reward
        identifiers. Identifiers may be UTC epochs, ISO timestamps, local dates
        (``YYYY-MM-DD``), or opaque historical ids. A backfill entry is
        classified as ``claimed``, ``unclaimed`` or ``expired``; only
        unclaimed entries should be granted by the caller.

        The operation is serialized per class instance. Two requests for the
        same player at the same instant therefore produce one reset; the second
        observes the new state and returns ``claimed=False``.
        """
        if "granularity" in kwargs:
            period = kwargs.pop("granularity")
        if "kind" in kwargs:
            period = kwargs.pop("kind")
        period = self._normalise_period(period)
        now = self._as_epoch(now_utc, name="now_utc")

        with self._lock:
            key = self._user_key(user)
            state = self._users.get(key)
            if state is None:
                state = self._create_user_state(
                    user, key, timezone if timezone is not None else tz_name, reset_hour
                )

            self._guard_clock(key, state, now, period)

            tz = state["tz"]
            hour = self._validate_hour(state["reset_hour"])
            period_state = state["periods"].setdefault(
                period, {"last_boundary": None}
            )
            previous = period_state["last_boundary"]
            base = self.initial_boundary if previous is None else previous

            new_boundaries = self._boundaries_between(base, now, tz, hour, period)
            classification = self._classify_rewards(
                new_boundaries, claimed, now, tz
            )

            if new_boundaries:
                period_state["last_boundary"] = new_boundaries[-1]
            state["request_seen"] = now

            last_boundary = period_state["last_boundary"]
            next_boundary = self._next_boundary(
                now if last_boundary is None else max(now, last_boundary),
                tz,
                hour,
                period,
            )
            user_snapshot = self._public_user_state(key, state)
            user_snapshot["period"] = period
            user_snapshot["last_boundary"] = last_boundary
            user_snapshot["last_boundary_utc"] = self._iso_utc(last_boundary)
            user_snapshot["next_boundary"] = next_boundary
            user_snapshot["next_boundary_utc"] = self._iso_utc(next_boundary)

            backfill = classification["items"]
            return {
                "claimed": bool(new_boundaries),
                "reset": bool(new_boundaries),
                "user": user,
                "timezone": state["timezone"],
                "period": period,
                "reset_hour": hour,
                "boundaries": list(new_boundaries),
                "backfill": backfill,
                "rewards": [dict(item) for item in backfill],
                "states": classification["states"],
                "claimed_rewards": classification["states"]["claimed"],
                "unclaimed_rewards": classification["states"]["unclaimed"],
                "expired_rewards": classification["states"]["expired"],
                "pending_rewards": classification["states"]["unclaimed"],
                "reward_states": [dict(item) for item in backfill],
                "awarded": [
                    dict(item)
                    for item in backfill
                    if item["state"] == "unclaimed"
                ],
                "granted": [
                    item["boundary"]
                    for item in backfill
                    if item["state"] == "unclaimed"
                ],
                "last_boundary": last_boundary,
                "next_boundary": next_boundary,
                "last_boundary_utc": self._iso_utc(last_boundary),
                "next_boundary_utc": self._iso_utc(next_boundary),
                "state": user_snapshot,
            }

    def snapshot(self, user=None):
        """Return a UTC-stamped snapshot of every (or one) player's state."""
        wall_now = int(time.time())
        with self._lock:
            if user is not None:
                state = self._users.get(self._user_key(user))
                if state is None:
                    return None
                return self._snapshot_user(state, wall_now)

            users = {}
            for key, state in self._users.items():
                item = self._snapshot_user(state, wall_now)
                snapshot_key = self._snapshot_user_key(state["user"], key)
                users[snapshot_key] = item

            if len(users) == 1:
                only = next(iter(users.values()))
                top_timezone = only["timezone"]
                top_last = only["last_boundary"]
                top_next = only["next_boundary"]
            else:
                top_timezone = self.default_timezone
                top_last = top_next = None

            return {
                "timezone": top_timezone,
                "users": users,
                "last_boundary": top_last,
                "last_boundary_utc": self._iso_utc(top_last),
                "next_boundary": top_next,
                "next_boundary_utc": self._iso_utc(top_next),
                "last_utc": top_last,
                "next_utc": top_next,
                "timestamp": self._iso_utc(wall_now),
                "utc_timestamp": wall_now,
                "anomalies": [dict(item) for item in self._anomalies],
            }

    def _snapshot_user(self, state, wall_now):
        item = self._public_user_state(None, state)
        reference = state["request_seen"]
        if reference is None:
            reference = wall_now
        daily = state["periods"].get("daily", {})
        last_boundary = daily.get("last_boundary")
        next_boundary = self._next_boundary(
            max(reference, last_boundary or self.initial_boundary),
            state["tz"],
            state["reset_hour"],
            "daily",
        )
        item["last_boundary"] = last_boundary
        item["last_boundary_utc"] = self._iso_utc(last_boundary)
        item["next_boundary"] = next_boundary
        item["next_boundary_utc"] = self._iso_utc(next_boundary)
        item["last_utc"] = last_boundary
        item["next_utc"] = next_boundary
        item["timestamp"] = self._iso_utc(wall_now)
        item["utc_timestamp"] = wall_now
        return item

    # ------------------------------------------------------------------
    # Boundary calculation
    # ------------------------------------------------------------------
    def _boundaries_between(self, last, now, tz, reset_hour, period):
        if now < last:
            raise ValueError("now_utc is before last_utc")

        local_last = datetime.fromtimestamp(last, UTC).astimezone(tz)
        local_now = datetime.fromtimestamp(now, UTC).astimezone(tz)

        result = []
        seen = set()
        for local_date in self._date_range(local_last.date(), local_now.date()):
            if not self._date_matches_period(local_date, period):
                continue
            boundary = self._local_boundary(local_date, tz, reset_hour)
            if last < boundary <= now and boundary not in seen:
                seen.add(boundary)
                result.append(boundary)
        return sorted(result)

    def _next_boundary(self, after, tz, reset_hour, period):
        horizon_days = {"daily": 3, "weekly": 9, "monthly": 34}[period]
        local_after = datetime.fromtimestamp(after, UTC).astimezone(tz)
        end = after + horizon_days * DAY + 3600
        local_end = datetime.fromtimestamp(end, UTC).astimezone(tz)
        for local_date in self._date_range(local_after.date(), local_end.date()):
            if not self._date_matches_period(local_date, period):
                continue
            boundary = self._local_boundary(local_date, tz, reset_hour)
            if boundary > after:
                return boundary
        return None

    def _local_boundary(self, local_date, tz, reset_hour):
        """Convert a local wall-clock reset to a UTC epoch.

        ``fold=0`` provides one deterministic choice for an ambiguous
        (fall-back) wall time. For a nonexistent (spring-forward) wall time,
        the round-trip through UTC lands on the first valid local instant after
        the gap, which avoids skipping that day's reset.
        """
        naive = datetime.combine(local_date, datetime_time(hour=reset_hour))
        aware = naive.replace(tzinfo=tz, fold=0)
        instant = aware.astimezone(UTC)
        return int(instant.timestamp())

    @staticmethod
    def _date_range(start, end):
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)

    @staticmethod
    def _date_matches_period(local_date, period):
        if period == "daily":
            return True
        if period == "weekly":
            return local_date.weekday() == 0
        if period == "monthly":
            return local_date.day == 1
        raise ValueError("unsupported period")

    # ------------------------------------------------------------------
    # Reward classification
    # ------------------------------------------------------------------
    def _classify_rewards(self, boundaries, claimed, now, tz):
        index = self._normalise_claimed(claimed)
        states = _RewardStates({"claimed": [], "unclaimed": [], "expired": []})
        items = []
        matched_keys = set()
        expiry_cutoff = now - self.reward_ttl_days * DAY

        for boundary in boundaries:
            local_date = (
                datetime.fromtimestamp(boundary, UTC).astimezone(tz).date().isoformat()
            )
            match = None
            if ("epoch", boundary) in index:
                match = ("epoch", boundary)
            elif ("date", local_date) in index:
                match = ("date", local_date)

            if match is not None:
                matched_keys.add(match)
                status = index[match]
            elif boundary <= expiry_cutoff:
                status = "expired"
            else:
                status = "unclaimed"

            if status not in states:
                status = "claimed" if status == "already_claimed" else "unclaimed"
            states[status].append(boundary)
            items.append(
                {
                    "boundary": boundary,
                    "boundary_utc": self._iso_utc(boundary),
                    "local_date": local_date,
                    "state": status,
                }
            )

        # Historical/already-claimed identifiers that were supplied but not
        # part of this backfill still need to be visible. Opaque ids cannot be
        # aged, so they are conservatively reported as expired rather than
        # being silently granted again.
        for key, status in index.items():
            if key in matched_keys:
                continue
            key_value = key[1]
            if status == "expired" or key[0] == "opaque":
                states["expired"].append(key_value)
                continue
            if key[0] == "epoch":
                if key_value <= expiry_cutoff:
                    states["expired"].append(key_value)
                else:
                    states["claimed"].append(key_value)
            elif key[0] == "date":
                try:
                    key_epoch = int(
                        datetime.fromisoformat(key_value)
                        .replace(tzinfo=tz)
                        .astimezone(UTC)
                        .timestamp()
                    )
                except ValueError:
                    states["expired"].append(key_value)
                else:
                    if key_epoch <= expiry_cutoff:
                        states["expired"].append(key_value)
                    else:
                        states["claimed"].append(key_value)
            else:
                states["expired"].append(key_value)

        return {"states": states, "items": items}

    def _normalise_claimed(self, claimed):
        index = {}
        if claimed is None:
            return index

        if isinstance(claimed, Mapping):
            iterator = claimed.items()
        elif isinstance(claimed, (str, bytes)):
            iterator = [(claimed, "claimed")]
        else:
            try:
                iterator = [(item, "claimed") for item in claimed]
            except TypeError:
                iterator = [(claimed, "claimed")]

        for key, value in iterator:
            status = self._claim_value_status(value)
            parsed = self._parse_claim_key(key)
            index[parsed] = status
        return index

    @staticmethod
    def _claim_value_status(value):
        if isinstance(value, Mapping):
            for field in ("state", "status", "claimed"):
                if field in value:
                    value = value[field]
                    break
        if isinstance(value, bool):
            return "claimed" if value else "unclaimed"
        text = str(value).strip().lower()
        if text in {"claimed", "already_claimed", "received", "true", "1"}:
            return "claimed"
        if text in {"unclaimed", "pending", "false", "0", "available"}:
            return "unclaimed"
        if text in {"expired", "missed", "void"}:
            return "expired"
        return "claimed"

    def _parse_claim_key(self, key):
        if isinstance(key, datetime):
            return ("epoch", self._as_epoch(key, name="claimed"))
        if isinstance(key, bool):
            return ("opaque", str(key))
        if isinstance(key, (int, float)):
            return ("epoch", self._as_epoch(key, name="claimed"))
        if isinstance(key, date):
            return ("date", key.isoformat())
        if isinstance(key, str):
            value = key.strip()
            if _DATE_RE.match(value):
                return ("date", value)
            try:
                return ("epoch", self._as_epoch(value, name="claimed"))
            except (TypeError, ValueError):
                return ("opaque", key)
        return ("opaque", str(key))

    # ------------------------------------------------------------------
    # Clock / state helpers
    # ------------------------------------------------------------------
    def _guard_clock(self, key, state, now, period="daily"):
        if now < 0:
            self._record_anomaly(
                "invalid_time",
                user=state["user"],
                requested=now,
                message="negative UTC timestamp",
            )
            raise ValueError("invalid time: now_utc cannot be negative")

        wall_now = int(time.time())
        if now > wall_now + self.max_future_skew:
            self._record_anomaly(
                "future_clock",
                user=state["user"],
                requested=now,
                reference=wall_now,
                message="now_utc is ahead of the server clock",
            )
            raise ValueError("future clock detected; refusing early reset")

        seen = state["request_seen"]
        if seen is not None:
            if now < seen:
                self._record_anomaly(
                    "clock_rollback",
                    user=state["user"],
                    requested=now,
                    reference=seen,
                    message="now_utc is before the last observed request",
                )
                raise ValueError("clock rollback detected; refusing reset")
            forward_limit = self.max_forward_jump
            if period == "weekly":
                forward_limit = max(forward_limit, 56 * DAY)
            elif period == "monthly":
                forward_limit = max(forward_limit, 400 * DAY)
            if forward_limit and now - seen > forward_limit:
                self._record_anomaly(
                    "clock_jump",
                    user=state["user"],
                    requested=now,
                    reference=seen,
                    message="now_utc jumped too far forward",
                )
                raise ValueError("future clock jump detected; refusing reset")

    def _create_user_state(self, user, key, tz_name, reset_hour):
        user_binding = self._binding_from_user(user)
        tz_name = tz_name or user_binding.get("timezone") or self.default_timezone
        hour = reset_hour if reset_hour is not None else user_binding.get("reset_hour")
        tz, canonical = self._resolve_timezone(tz_name)
        state = {
            "user": user,
            "timezone": canonical,
            "tz": tz,
            "reset_hour": self._validate_hour(
                self.reset_hour if hour is None else hour
            ),
            "request_seen": None,
            "periods": {},
        }
        self._users[key] = state
        return state

    def _binding_from_user(self, user):
        binding = {}
        if isinstance(user, Mapping):
            for name in ("timezone", "tz_name", "tz"):
                if name in user:
                    binding["timezone"] = user[name]
                    break
            if "reset_hour" in user:
                binding["reset_hour"] = user["reset_hour"]
        else:
            for attr in ("timezone", "tz_name", "reset_hour"):
                if hasattr(user, attr):
                    binding[attr] = getattr(user, attr)
            if "tz_name" in binding:
                binding["timezone"] = binding.pop("tz_name")
        return binding

    def _public_user_state(self, key, state):
        return {
            "user": state["user"],
            "timezone": state["timezone"],
            "timezone_name": state["timezone"],
            "reset_hour": state["reset_hour"],
            "request_seen": state["request_seen"],
            "request_seen_utc": self._iso_utc(state["request_seen"]),
            "periods": {
                period: {
                    "last_boundary": period_state.get("last_boundary"),
                    "last_boundary_utc": self._iso_utc(
                        period_state.get("last_boundary")
                    ),
                }
                for period, period_state in state["periods"].items()
            },
        }

    def _record_anomaly(
        self, kind, user=None, requested=None, reference=None, message=""
    ):
        wall_now = int(time.time())
        self._anomalies.append(
            {
                "kind": kind,
                "user": user,
                "requested_utc": requested,
                "requested": self._iso_utc(requested),
                "reference_utc": reference,
                "reference": self._iso_utc(reference),
                "timestamp": self._iso_utc(wall_now),
                "utc_timestamp": wall_now,
                "message": message,
            }
        )

    # ------------------------------------------------------------------
    # Conversion / validation
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_period(period):
        if period is None:
            return "daily"
        try:
            return _PERIOD_ALIASES[str(period).strip().lower()]
        except KeyError as exc:
            raise ValueError(f"unsupported reset period: {period!r}") from exc

    @staticmethod
    def _validate_hour(hour):
        if isinstance(hour, bool):
            raise ValueError("reset_hour must be an integer hour")
        try:
            value = int(hour)
        except (TypeError, ValueError) as exc:
            raise ValueError("reset_hour must be an integer hour") from exc
        if not 0 <= value <= 23:
            raise ValueError("reset_hour must be between 0 and 23")
        return value

    @staticmethod
    def _as_epoch(value, name="time"):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return int(value.timestamp())
        if isinstance(value, date) and not isinstance(value, datetime):
            midnight = datetime.combine(value, datetime_time()).replace(tzinfo=UTC)
            return int(midnight.timestamp())
        if isinstance(value, str):
            text = value.strip()
            try:
                return int(text)
            except ValueError:
                pass
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    f"{name} must be a UTC epoch or ISO timestamp"
                ) from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return int(parsed.timestamp())
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a UTC epoch")
        try:
            return int(math.floor(float(value)))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a UTC epoch") from exc

    def _resolve_timezone(self, tz_name):
        if isinstance(tz_name, str):
            name = tz_name.strip()
        else:
            name = tz_name

        requested_name = name if isinstance(name, str) else None
        candidate = self._lookup_tzdb(name)
        if candidate is None:
            candidate = name

        if hasattr(candidate, "utcoffset") and hasattr(candidate, "tzname"):
            canonical = getattr(candidate, "key", None) or getattr(
                candidate, "zone", None
            )
            if canonical is None and requested_name is not None:
                canonical = requested_name
            if canonical is None:
                canonical = (
                    "UTC" if candidate is UTC or candidate == UTC else str(candidate)
                )
            if isinstance(candidate, timezone) and candidate is UTC:
                canonical = "UTC"
            return candidate, canonical

        if isinstance(candidate, str):
            text = candidate.strip()
            if text.upper() in _UTC_NAMES:
                return UTC, "UTC"
            try:
                return ZoneInfo(text), text
            except (ZoneInfoNotFoundError, ValueError):
                offset = self._parse_offset_timezone(text)
                if offset is not None:
                    return offset, text

        raise ValueError(f"unknown timezone: {tz_name!r}")

    def _lookup_tzdb(self, name):
        if self.tzdb is None or name is None:
            return None
        if isinstance(self.tzdb, Mapping):
            return self.tzdb.get(name)
        if callable(self.tzdb):
            try:
                return self.tzdb(name)
            except (KeyError, ZoneInfoNotFoundError, ValueError):
                return None
        if hasattr(self.tzdb, "get"):
            try:
                return self.tzdb.get(name)
            except (KeyError, ZoneInfoNotFoundError, ValueError):
                return None
        return None

    @staticmethod
    def _parse_offset_timezone(text):
        match = _OFFSET_RE.match(text)
        if not match:
            return None
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
        if sign == "-":
            delta = -delta
        try:
            return timezone(delta)
        except ValueError:
            return None

    @staticmethod
    def _iso_utc(value):
        if value is None:
            return None
        return (
            datetime.fromtimestamp(int(value), UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _is_scalar(value):
        return isinstance(value, (str, int, float, bool, type(None)))

    @classmethod
    def _snapshot_user_key(cls, user, fallback):
        if cls._is_scalar(user):
            return user
        if isinstance(user, Mapping):
            for field in ("id", "user_id", "uid", "user", "player_id"):
                if field in user and cls._is_scalar(user[field]):
                    return user[field]
        for field in ("id", "user_id", "uid", "player_id"):
            if hasattr(user, field):
                value = getattr(user, field)
                if cls._is_scalar(value):
                    return value
        return repr(fallback)

    def _user_key(self, user):
        if isinstance(user, Mapping):
            for field in ("id", "user_id", "uid", "user", "player_id"):
                if field in user:
                    try:
                        hash(user[field])
                    except TypeError:
                        continue
                    return user[field]
        else:
            for field in ("id", "user_id", "uid", "player_id"):
                if hasattr(user, field):
                    value = getattr(user, field)
                    try:
                        hash(value)
                    except TypeError:
                        continue
                    return value
        try:
            hash(user)
        except TypeError:
            if isinstance(user, Mapping):
                return tuple(
                    sorted((str(key), repr(value)) for key, value in user.items())
                )
            return repr(user)
        return user
