import pytest

import redirect_hop_ledger as rl

HOST = "shop.example.com"
START = "https://shop.example.com/start"


def make_fetch(routes, calls=None):
    calls = calls if calls is not None else []

    def fetch(url, method):
        calls.append((url, method))
        item = routes.get(url)
        if item is None:
            return {"status": 200}
        return dict(item)

    return fetch, calls


def ledger(**over):
    kwargs = {"allowed_hosts": {HOST}, "allowed_ports": (443,)}
    kwargs.update(over)
    return rl.RedirectHopLedger(**kwargs)


def test_suffix_confusion_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "https://shop.example.com.evil.net/x"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "unsafe_redirect"


def test_userinfo_in_location_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "https://user:pass@shop.example.com/x"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "unsafe_redirect"


def test_protocol_relative_location_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "//evil.net/x"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "unsafe_redirect"


def test_backslash_in_location_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "https://shop.example.com\\@evil.net/x"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "unsafe_redirect"


def test_encoded_host_variants_are_blocked():
    for location in (
        "https://shop%2Eexample%2Ecom.evil.net/x",
        "https://shop.example.com%2eevil.net/x",
    ):
        fetch, _ = make_fetch({START: {"status": 302, "location": location}})
        with pytest.raises(rl.RedirectHopError) as exc:
            ledger().resolve(START, fetch)
        assert exc.value.code == "unsafe_redirect"


def test_foreign_host_at_fifth_hop_is_blocked():
    routes = {
        START: {"status": 302, "location": "https://shop.example.com/1"},
        "https://shop.example.com/1": {"status": 302, "location": "https://shop.example.com/2"},
        "https://shop.example.com/2": {"status": 302, "location": "https://shop.example.com/3"},
        "https://shop.example.com/3": {"status": 302, "location": "https://shop.example.com/4"},
        "https://shop.example.com/4": {"status": 302, "location": "https://evil.net/5"},
    }
    fetch, _ = make_fetch(routes)
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "unsafe_redirect"


def test_hop_limit_stops_with_reason():
    routes = {}
    for index in range(1, 10):
        routes["https://shop.example.com/%d" % index] = {
            "status": 302,
            "location": "https://shop.example.com/%d" % (index + 1),
        }
    routes[START] = {"status": 302, "location": "https://shop.example.com/1"}
    fetch, _ = make_fetch(routes)
    result = ledger(max_hops=8).resolve(START, fetch)
    assert result["reason"] == "max_hops"
    assert len(result["hops"]) == 8


def test_loop_is_detected():
    routes = {
        START: {"status": 302, "location": "https://shop.example.com/a"},
        "https://shop.example.com/a": {"status": 302, "location": START},
    }
    fetch, _ = make_fetch(routes)
    result = ledger().resolve(START, fetch)
    assert result["reason"] == "loop"
    assert len(result["hops"]) == 2


def test_307_preserves_method():
    routes = {
        START: {"status": 307, "location": "https://shop.example.com/next"},
        "https://shop.example.com/next": {"status": 200},
    }
    fetch, calls = make_fetch(routes)
    result = ledger().resolve(START, fetch, method="POST")
    assert [hop["method"] for hop in result["hops"]] == ["POST", "POST"]
    assert result["final_url"] == "https://shop.example.com/next"
    assert calls == [(START, "POST"), ("https://shop.example.com/next", "POST")]


def test_https_to_http_downgrade_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "http://shop.example.com/x"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "downgrade"


def test_newline_in_location_is_blocked():
    fetch, _ = make_fetch({START: {"status": 302, "location": "https://shop.example.com/x\r\nSet-Cookie: a=b"}})
    with pytest.raises(rl.RedirectHopError) as exc:
        ledger().resolve(START, fetch)
    assert exc.value.code == "invalid_location"


def test_relative_location_is_resolved_against_current_url():
    routes = {
        START: {"status": 302, "location": "/next?a=1"},
        "https://shop.example.com/next?a=1": {"status": 200},
    }
    fetch, _ = make_fetch(routes)
    result = ledger().resolve(START, fetch)
    assert result["final_url"] == "https://shop.example.com/next?a=1"
    assert result["reason"] == "ok"


def test_port_must_be_allowed():
    routes = {
        START: {"status": 302, "location": "https://shop.example.com:8443/x"},
        "https://shop.example.com:8443/x": {"status": 200},
    }
    fetch, _ = make_fetch(routes)
    assert ledger(allowed_ports=(443, 8443)).resolve(START, fetch)["final_url"] == "https://shop.example.com:8443/x"
    fetch2, _ = make_fetch({START: {"status": 302, "location": "https://shop.example.com:4443/x"}})
    with pytest.raises(rl.RedirectHopError):
        ledger(allowed_ports=(443, 8443)).resolve(START, fetch2)


def test_returned_hops_are_detached_from_later_runs():
    routes = {START: {"status": 302, "location": "https://shop.example.com/next"}}
    fetch, _ = make_fetch(routes)
    first = ledger().resolve(START, fetch)
    first["hops"][0]["url"] = "https://evil.net/"
    second = ledger().resolve(START, fetch)
    assert second["hops"][0]["url"] == START


def test_repeated_resolution_is_identical_and_non_redirect_stops():
    fetch, _ = make_fetch({})
    first = ledger().resolve(START, fetch)
    second = ledger().resolve(START, fetch)
    assert first == second
    assert first["reason"] == "not_redirect"
    assert first["final_url"] == START
    assert len(first["hops"]) == 1
