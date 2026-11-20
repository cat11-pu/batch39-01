import threading

import pytest

import quota_token_window as qw


def window(**over):
    kwargs = {"window": 10, "limit": 10, "max_cost": 20, "burst": 0.2, "tenants": ("t-1",)}
    kwargs.update(over)
    return qw.QuotaTokenWindow(**kwargs)


def test_window_boundary_does_not_double_count():
    w = window(window=10, limit=10)
    assert w.consume("t-1", 10, 0)["allowed"] is True
    assert w.consume("t-1", 1, 1)["allowed"] is False
    assert w.consume("t-1", 1, 10)["allowed"] is True


def test_cost_is_weighted_not_per_request():
    w = window()
    result = w.consume("t-1", 4, 0)
    assert result["allowed"] is True
    assert result["remaining"] == 6


def test_burst_allows_up_to_twenty_percent():
    w = window(limit=10, burst=0.2)
    assert w.consume("t-1", 12, 0)["allowed"] is True
    assert w.consume("t-1", 1, 1)["allowed"] is False


def test_clock_rollback_does_not_reset_window():
    w = window()
    w.consume("t-1", 9, 100)
    assert w.consume("t-1", 5, 50)["allowed"] is False


def test_failed_call_refunds_quota_by_idempotency_key():
    w = window()
    w.consume("t-1", 7, 0, idem="req-1")
    assert w.refund("t-1", "req-1") is True
    assert w.consume("t-1", 7, 1)["allowed"] is True


def test_same_idempotency_key_refunds_only_once():
    w = window()
    w.consume("t-1", 5, 0, idem="req-1")
    assert w.refund("t-1", "req-1") is True
    assert w.refund("t-1", "req-1") is False


def test_zero_quota_denies_every_request():
    w = window(limit=0)
    with pytest.raises(qw.QuotaError) as exc:
        w.consume("t-1", 0, 0)
    assert exc.value.code == "zero_quota"


def test_negative_cost_is_rejected():
    with pytest.raises(qw.QuotaError) as exc:
        window().consume("t-1", -1, 0)
    assert exc.value.code == "invalid_cost"


def test_unknown_tenant_is_rejected():
    with pytest.raises(qw.QuotaError) as exc:
        window().consume("t-x", 1, 0)
    assert exc.value.code == "unknown_tenant"


def test_snapshot_and_restore_keep_usage():
    w = window()
    w.consume("t-1", 6, 0)
    snap = w.snapshot()
    other = window()
    other.restore(snap)
    assert other.consume("t-1", 5, 0)["allowed"] is False


def test_concurrent_consumers_cannot_oversell():
    w = window(limit=5, burst=0)
    results = []

    def worker():
        try:
            results.append(w.consume("t-1", 1, 0)["allowed"])
        except Exception:
            results.append(False)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 5


def test_retry_after_is_never_negative():
    w = window(limit=1)
    w.consume("t-1", 1, 0)
    result = w.consume("t-1", 1, 1)
    assert result["allowed"] is False
    assert result["retry_after_ms"] >= 0


def test_snapshot_is_detached_from_internal_state():
    w = window()
    w.consume("t-1", 1, 0)
    snap = w.snapshot()
    snap["tenants"].clear()
    assert w.snapshot()["tenants"]


def test_duplicate_idempotency_key_does_not_charge_twice():
    w = window()
    first = w.consume("t-1", 3, 0, idem="req-1")
    second = w.consume("t-1", 3, 1, idem="req-1")
    assert first["allowed"] is True
    assert second.get("duplicate") is True
    assert second["remaining"] == first["remaining"]


def test_restore_is_repeatable_and_startup_is_consistent():
    w = window()
    w.consume("t-1", 2, 0)
    snap = w.snapshot()
    a = window()
    b = window()
    a.restore(snap)
    b.restore(snap)
    assert a.consume("t-1", 1, 1) == b.consume("t-1", 1, 1)
