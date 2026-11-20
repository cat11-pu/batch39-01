import json

import pytest

import session_rotate_chain as sc


def chain(**over):
    kwargs = {"idle_ttl": 900, "absolute_ttl": 3600, "grace": 5}
    kwargs.update(over)
    return sc.SessionRotateChain(**kwargs)


def start(c, draft=None):
    return c.login("u-1", "dev-1", 0, draft)


def test_login_token_authorizes_on_bound_device():
    c = chain()
    first = start(c)
    result = c.authorize(first["token"], 1, "dev-1")
    assert result["user_id"] == "u-1"
    assert result["chain_id"] == first["chain_id"]


def test_privilege_change_rotates_and_old_token_expires_after_grace():
    c = chain(grace=5)
    old = start(c)["token"]
    new = c.rotate(old, "privilege_change", 10, {"cart": 2})["token"]
    assert c.authorize(new, 11, "dev-1")["user_id"] == "u-1"
    assert c.authorize(old, 12, "dev-1")["read_only"] is True
    with pytest.raises(sc.SessionError) as exc:
        c.authorize(old, 16, "dev-1")
    assert exc.value.code == "expired"


def test_write_through_old_token_during_grace_is_rejected():
    c = chain(grace=30)
    old = start(c)["token"]
    c.rotate(old, "password_change", 10)
    with pytest.raises(sc.SessionError) as exc:
        c.authorize(old, 11, "dev-1", write=True)
    assert exc.value.code == "read_only"


def test_draft_data_migrates_with_the_chain():
    c = chain()
    first = c.login("u-1", "dev-1", 0, {"cart": ["a"]})
    second = c.rotate(first["token"], "tenant_switch", 1, {"cart": ["a", "b"]})
    assert c.authorize(second["token"], 2, "dev-1")["draft"] == {"cart": ["a", "b"]}


def test_multiple_tabs_share_chain_id_after_rotation():
    c = chain(grace=30)
    old = start(c)["token"]
    new = c.rotate(old, "login", 1)["token"]
    assert c.authorize(old, 2, "dev-1")["chain_id"] == c.authorize(new, 2, "dev-1")["chain_id"]


def test_logout_invalidates_token_immediately():
    c = chain()
    token = start(c)["token"]
    c.logout(token, now=1)
    with pytest.raises(sc.SessionError):
        c.authorize(token, 2, "dev-1")


def test_idle_timeout_terminates_chain():
    c = chain(idle_ttl=10, absolute_ttl=1000)
    token = start(c)["token"]
    assert c.authorize(token, 9, "dev-1")["user_id"] == "u-1"
    with pytest.raises(sc.SessionError) as exc:
        c.authorize(token, 20, "dev-1")
    assert exc.value.code == "idle_timeout"


def test_absolute_timeout_wins_over_activity():
    c = chain(idle_ttl=10, absolute_ttl=20)
    token = start(c)["token"]
    c.authorize(token, 10, "dev-1")
    with pytest.raises(sc.SessionError) as exc:
        c.authorize(token, 21, "dev-1")
    assert exc.value.code == "absolute_timeout"


def test_token_is_bound_to_device():
    c = chain()
    token = start(c)["token"]
    with pytest.raises(sc.SessionError) as exc:
        c.authorize(token, 1, "dev-2")
    assert exc.value.code == "device_mismatch"


def test_revoke_user_clears_every_chain():
    c = chain()
    token1 = start(c)["token"]
    token2 = c.login("u-1", "dev-2", 0)["token"]
    c.revoke_user("u-1")
    for token in (token1, token2):
        with pytest.raises(sc.SessionError):
            c.authorize(token, 1, "dev-1")


def test_rejected_old_token_replay_is_counted():
    c = chain(grace=1)
    old = start(c)["token"]
    c.rotate(old, "login", 0)
    with pytest.raises(sc.SessionError):
        c.authorize(old, 5, "dev-1")
    assert c.snapshot()["replay_rejected"] >= 1


def test_grace_window_is_configurable_and_exact():
    c = chain(grace=2)
    old = start(c)["token"]
    c.rotate(old, "login", 10)
    assert c.authorize(old, 11, "dev-1")["read_only"] is True
    with pytest.raises(sc.SessionError):
        c.authorize(old, 13, "dev-1")


def test_snapshot_is_detached_from_internal_state():
    c = chain()
    start(c)
    snap = c.snapshot()
    snap["chains"].clear()
    assert c.snapshot()["chains"]


def test_snapshot_does_not_contain_raw_tokens():
    c = chain()
    token = start(c)["token"]
    assert token not in json.dumps(c.snapshot())


def test_each_rotation_replaces_the_previous_chain_head():
    c = chain(grace=30)
    first = start(c)["token"]
    second = c.rotate(first, "login", 1)["token"]
    third = c.rotate(second, "login", 2)["token"]
    assert c.authorize(third, 3, "dev-1")["user_id"] == "u-1"
    assert c.authorize(second, 3, "dev-1")["read_only"] is True
    with pytest.raises(sc.SessionError):
        c.authorize(first, 3, "dev-1")
