import json
import threading

import pytest

import reset_ticket_ledger as rl


def vault(**over):
    kwargs = {"ttl": 600, "max_token_len": 128}
    kwargs.update(over)
    return rl.ResetTicketVault(**kwargs)


def issue(v, user="u-1", device="d-1", now=0):
    return v.issue(user, device, now)


def test_token_cannot_be_redeemed_twice():
    v = vault()
    token = issue(v)["token"]
    v.redeem(token, "u-1", "d-1", now=1)
    with pytest.raises(rl.ResetTicketError) as exc:
        v.redeem(token, "u-1", "d-1", now=2)
    assert exc.value.code == "invalid_ticket"


def test_revoke_all_invalidates_old_token():
    v = vault()
    token = issue(v)["token"]
    v.revoke_all("u-1")
    with pytest.raises(rl.ResetTicketError):
        v.redeem(token, "u-1", "d-1", now=1)


def test_snapshot_never_contains_the_plain_token():
    v = vault()
    token = issue(v)["token"]
    blob = json.dumps(v.snapshot())
    assert token not in blob


def test_wrong_token_and_wrong_length_share_one_code():
    v = vault()
    issue(v)
    codes = []
    for token in ("not-the-token", "x" * 200):
        with pytest.raises(rl.ResetTicketError) as exc:
            v.redeem(token, "u-1", "d-1", now=1)
        codes.append(exc.value.code)
    assert codes[0] == codes[1] == "invalid_ticket"


def test_expired_token_is_rejected():
    v = vault(ttl=10)
    token = issue(v, now=0)["token"]
    with pytest.raises(rl.ResetTicketError):
        v.redeem(token, "u-1", "d-1", now=11)


def test_token_is_bound_to_device():
    v = vault()
    token = issue(v, device="d-1")["token"]
    with pytest.raises(rl.ResetTicketError):
        v.redeem(token, "u-1", "d-2", now=1)


def test_new_issue_invalidates_every_previous_token():
    v = vault()
    tokens = [issue(v, now=index)["token"] for index in range(5)]
    for token in tokens[:-1]:
        with pytest.raises(rl.ResetTicketError):
            v.redeem(token, "u-1", "d-1", now=10)
    assert v.redeem(tokens[-1], "u-1", "d-1", now=10)["user_id"] == "u-1"


def test_concurrent_redeem_allows_exactly_one_success():
    v = vault()
    token = issue(v)["token"]
    results = []

    def worker():
        try:
            v.redeem(token, "u-1", "d-1", now=1)
            results.append("ok")
        except Exception as exc:
            results.append(getattr(exc, "code", type(exc).__name__))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("ok") == 1
    assert len(results) == 6


def test_unknown_and_expired_tokens_are_indistinguishable():
    v = vault(ttl=5)
    token = issue(v, now=0)["token"]
    codes = []
    for candidate, now in ((token, 99), ("unknown-token", 1)):
        with pytest.raises(rl.ResetTicketError) as exc:
            v.redeem(candidate, "u-1", "d-1", now=now)
        codes.append((exc.value.code, str(exc.value)))
    assert codes[0] == codes[1]


def test_revoke_all_marks_tickets_revoked_in_snapshot():
    v = vault()
    issue(v)
    v.revoke_all("u-1")
    statuses = [item["status"] for item in v.snapshot()["tickets"].values()]
    assert statuses and all(status == "revoked" for status in statuses)


def test_failed_redeem_is_written_to_audit():
    v = vault()
    issue(v)
    with pytest.raises(rl.ResetTicketError):
        v.redeem("bad-token", "u-1", "d-1", now=1)
    audit = v.snapshot()["audit"]
    assert any(entry["success"] is False and entry["code"] == "invalid_ticket" for entry in audit)


def test_snapshot_contains_only_ticket_ids_and_status_fields():
    v = vault()
    issue(v)
    snap = v.snapshot()
    assert set(snap) == {"tickets", "audit"}
    for ticket in snap["tickets"].values():
        assert set(ticket) == {"user_id", "device_id", "status", "expires_at"}


def test_empty_token_is_rejected():
    with pytest.raises(rl.ResetTicketError):
        vault().redeem("", "u-1", "d-1", now=1)


def test_overlong_token_is_rejected_before_lookup():
    v = vault(max_token_len=8)
    with pytest.raises(rl.ResetTicketError):
        v.redeem("x" * 9, "u-1", "d-1", now=1)


def test_token_cannot_be_redeemed_by_another_user():
    v = vault()
    token = issue(v, user="u-1")["token"]
    with pytest.raises(rl.ResetTicketError):
        v.redeem(token, "u-2", "d-1", now=1)
