import copy
import math
import threading


class QuotaError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class QuotaTokenWindow:
    """Sliding-window quota judge keyed by tenant.

    Time is supplied by the caller as a monotonically increasing clock in
    seconds (e.g. ``time.monotonic()``); ``retry_after_ms`` is returned in
    milliseconds. All judging happens under one lock so concurrent consumers
    can never oversell the same quota.
    """

    def __init__(self, window=60, limit=100, max_cost=50, burst=0.2, tenants=()):
        if not isinstance(window, (int, float)) or isinstance(window, bool) or window <= 0:
            raise QuotaError("invalid_window")
        if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit < 0:
            raise QuotaError("invalid_limit")
        if not isinstance(max_cost, (int, float)) or isinstance(max_cost, bool) or max_cost < 0:
            raise QuotaError("invalid_max_cost")
        if not isinstance(burst, (int, float)) or isinstance(burst, bool) or not 0 <= burst <= 1:
            raise QuotaError("invalid_burst")

        self.window = window
        self.limit = limit
        self.max_cost = max_cost
        self.burst = burst
        self.tenants = frozenset(tenants)
        self._lock = threading.RLock()
        self._anomalies = []
        self._state = {tenant: {"entries": [], "last_now": None} for tenant in self.tenants}

    @staticmethod
    def _is_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _tick(self, tenant_state, now):
        """Clamp the caller clock so rollbacks never reset the window."""
        previous = tenant_state["last_now"]
        if previous is None:
            effective = now
            if now > self.window:
                self._anomalies.append(
                    {"type": "jump", "from": None, "to": now, "effective": now}
                )
        elif now < previous:
            self._anomalies.append(
                {"type": "rollback", "from": previous, "to": now, "effective": previous}
            )
            effective = previous
        else:
            effective = now
            if now - previous > self.window:
                self._anomalies.append(
                    {"type": "jump", "from": previous, "to": now, "effective": now}
                )
        tenant_state["last_now"] = effective
        return effective

    def _expire(self, tenant_state, now):
        cutoff = now - self.window
        tenant_state["entries"] = [
            entry for entry in tenant_state["entries"] if entry["ts"] > cutoff
        ]

    @staticmethod
    def _used(tenant_state):
        return sum(
            entry["cost"] for entry in tenant_state["entries"] if not entry["refunded"]
        )

    def _retry_after_ms(self, tenant_state, now):
        active = [entry for entry in tenant_state["entries"] if not entry["refunded"]]
        if not active:
            return 0
        wait_seconds = min(entry["ts"] for entry in active) + self.window - now
        return max(0, int(math.ceil(wait_seconds * 1000)))

    def consume(self, tenant, cost, now, idem=None):
        with self._lock:
            if tenant not in self.tenants:
                raise QuotaError("unknown_tenant")
            if not self._is_number(cost) or cost < 0:
                raise QuotaError("invalid_cost")
            if self.limit == 0:
                raise QuotaError("zero_quota")
            if cost > self.max_cost:
                raise QuotaError("cost_too_large")
            if not self._is_number(now) or now < 0:
                raise QuotaError("invalid_time")

            tenant_state = self._state[tenant]
            effective_now = self._tick(tenant_state, now)
            self._expire(tenant_state, effective_now)

            if idem is not None:
                for entry in tenant_state["entries"]:
                    if entry["idem"] == idem and not entry["refunded"]:
                        return {
                            "allowed": True,
                            "duplicate": True,
                            "cost": entry["cost"],
                            "remaining": max(0, self.limit - self._used(tenant_state)),
                            "retry_after_ms": 0,
                        }

            used = self._used(tenant_state)
            if used == 0 and self.burst > 0:
                capacity = self.limit * (1 + self.burst)
            else:
                capacity = self.limit

            if used + cost > capacity:
                return {
                    "allowed": False,
                    "cost": cost,
                    "remaining": max(0, self.limit - used),
                    "retry_after_ms": self._retry_after_ms(tenant_state, effective_now),
                }

            tenant_state["entries"].append(
                {"ts": effective_now, "cost": cost, "idem": idem, "refunded": False}
            )
            return {
                "allowed": True,
                "cost": cost,
                "remaining": max(0, self.limit - self._used(tenant_state)),
                "retry_after_ms": 0,
            }

    def refund(self, tenant, idem):
        with self._lock:
            if tenant not in self.tenants or idem is None:
                return False
            tenant_state = self._state[tenant]
            for entry in tenant_state["entries"]:
                if entry["idem"] == idem and not entry["refunded"]:
                    entry["refunded"] = True
                    return True
            return False

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(
                {
                    "version": 1,
                    "window": self.window,
                    "limit": self.limit,
                    "max_cost": self.max_cost,
                    "burst": self.burst,
                    "tenants": copy.deepcopy(self._state),
                    "anomalies": copy.deepcopy(self._anomalies),
                }
            )

    def restore(self, snapshot):
        with self._lock:
            if not isinstance(snapshot, dict) or snapshot.get("version") != 1:
                raise QuotaError("bad_snapshot")
            tenants = snapshot.get("tenants")
            if not isinstance(tenants, dict):
                raise QuotaError("bad_snapshot")

            restored = {}
            for tenant, tenant_state in tenants.items():
                if not isinstance(tenant, str) or not isinstance(tenant_state, dict):
                    raise QuotaError("bad_snapshot")
                entries = tenant_state.get("entries")
                last_now = tenant_state.get("last_now")
                if not isinstance(entries, list) or (
                    last_now is not None and not self._is_number(last_now)
                ):
                    raise QuotaError("bad_snapshot")
                clean_entries = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise QuotaError("bad_snapshot")
                    ts = entry.get("ts")
                    cost = entry.get("cost")
                    refunded = entry.get("refunded", False)
                    if not self._is_number(ts) or not self._is_number(cost) or cost < 0:
                        raise QuotaError("bad_snapshot")
                    if not isinstance(refunded, bool):
                        raise QuotaError("bad_snapshot")
                    clean_entries.append(
                        {
                            "ts": ts,
                            "cost": cost,
                            "idem": entry.get("idem"),
                            "refunded": refunded,
                        }
                    )
                restored[tenant] = {"entries": clean_entries, "last_now": last_now}

            anomalies = snapshot.get("anomalies", [])
            if not isinstance(anomalies, list):
                raise QuotaError("bad_snapshot")

            self._state = copy.deepcopy(restored)
            self._anomalies = copy.deepcopy(anomalies)
            return True
