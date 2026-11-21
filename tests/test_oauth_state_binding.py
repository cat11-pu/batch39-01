import json
import threading

import pytest

import oauth_state_binding as ob

PROVIDERS = {"alpha", "beta"}
REDIRECT = "https://app.example.com/callback"


def binding(**over):
    kwargs = {"providers": PROVIDERS, "ttl": 600}
    kwargs.update(over)
    return ob.OAuthStateBinding(**kwargs)


def start(b, provider="alpha", action="login", session="s-1", now=0, tenant="t-1"):
    return b.issue(provider, REDIRECT, action, session, tenant=tenant, now=now)


def test_state_can_only_be_consumed_once():
    b = binding()
    item = start(b)
    b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=2)
    assert exc.value.code == "state_reused"


def test_state_is_bound_to_browser_session():
    b = binding()
    item = start(b, session="s-1")
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code", "alpha", REDIRECT, "login", "s-2", now=1)
    assert exc.value.code == "session_mismatch"


def test_redirect_uri_must_match_exactly():
    b = binding()
    item = start(b)
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code", "alpha", REDIRECT + ".evil.net", "login", "s-1", now=1)
    assert exc.value.code == "redirect_mismatch"


def test_authorization_code_cannot_be_exchanged_twice():
    b = binding()
    item = start(b)
    b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
    b.exchange("code-1", item["verifier"], "alpha", REDIRECT)
    with pytest.raises(ob.OAuthError) as exc:
        b.exchange("code-1", item["verifier"], "alpha", REDIRECT)
    assert exc.value.code == "code_reused"


def test_plain_verifier_is_rejected():
    b = binding()
    item = start(b)
    b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
    with pytest.raises(ob.OAuthError):
        b.exchange("code-1", "plain", "alpha", REDIRECT)


def test_empty_verifier_is_rejected():
    b = binding()
    item = start(b)
    b.callback(item["state"], "code-2", "alpha", REDIRECT, "login", "s-1", now=1)
    with pytest.raises(ob.OAuthError):
        b.exchange("code-2", "", "alpha", REDIRECT)


def test_two_tabs_do_not_overwrite_each_other():
    b = binding()
    first = start(b, action="login", session="s-1")
    second = start(b, action="link", session="s-1")
    assert b.callback(first["state"], "c1", "alpha", REDIRECT, "login", "s-1", now=1)["action"] == "login"
    assert b.callback(second["state"], "c2", "alpha", REDIRECT, "link", "s-1", now=1)["action"] == "link"


def test_snapshot_only_shows_state_digest():
    b = binding()
    item = start(b)
    blob = json.dumps(b.snapshot())
    assert item["state"] not in blob
    assert len(b.snapshot()["states"]) == 1


def test_error_callback_with_unknown_state_is_rejected():
    b = binding()
    with pytest.raises(ob.OAuthError):
        b.callback("forged", "", "alpha", REDIRECT, "login", "s-1", now=1)


def test_provider_mixup_is_rejected():
    b = binding()
    item = start(b, provider="alpha")
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code", "beta", REDIRECT, "login", "s-1", now=1)
    assert exc.value.code == "provider_mismatch"


def test_expired_state_is_rejected():
    b = binding(ttl=10)
    item = start(b, now=0)
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code", "alpha", REDIRECT, "login", "s-1", now=11)
    assert exc.value.code == "state_expired"


def test_cross_tenant_callback_is_rejected():
    b = binding()
    item = start(b, tenant="t-1")
    with pytest.raises(ob.OAuthError) as exc:
        b.callback(item["state"], "code", "alpha", REDIRECT, "login", "s-1", tenant="t-2", now=1)
    assert exc.value.code == "tenant_mismatch"


def test_exchange_rechecks_redirect_uri():
    b = binding()
    item = start(b)
    b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
    with pytest.raises(ob.OAuthError) as exc:
        b.exchange("code-1", item["verifier"], "alpha", "https://evil.net/cb")
    assert exc.value.code == "redirect_mismatch"


def test_successful_flow_returns_token():
    b = binding()
    item = start(b)
    result = b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
    assert result["code"] == "code-1"
    assert b.exchange("code-1", item["verifier"], "alpha", REDIRECT)["access_token"]


def test_concurrent_callback_allows_only_one_consumer():
    b = binding()
    item = start(b)
    results = []

    def worker():
        try:
            b.callback(item["state"], "code-1", "alpha", REDIRECT, "login", "s-1", now=1)
            results.append("ok")
        except Exception:
            results.append("fail")

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
