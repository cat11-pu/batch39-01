import pytest

import cookie_prefix_rules as cp


def rules(**over):
    kwargs = {"public_suffixes": ("com", "co.uk"), "max_count": 50, "max_size": 4096}
    kwargs.update(over)
    return cp.CookiePrefixRules(**kwargs)


def set_cookie(**over):
    kwargs = {"name": "sid", "value": "v", "path": "/", "secure": True}
    kwargs.update(over)
    return rules().set_cookie(**kwargs)


def test_host_prefix_with_domain_is_rejected():
    with pytest.raises(cp.CookieError) as exc:
        set_cookie(name="__Host-sid", domain="example.com")
    assert exc.value.code == "host_prefix_domain"


def test_secure_prefix_without_secure_is_rejected():
    with pytest.raises(cp.CookieError) as exc:
        set_cookie(name="__Secure-sid", secure=False)
    assert exc.value.code == "secure_prefix_transport"


def test_samesite_none_requires_secure():
    with pytest.raises(cp.CookieError) as exc:
        set_cookie(samesite="None", secure=False)
    assert exc.value.code == "samesite_secure"


def test_public_suffix_domain_is_rejected():
    with pytest.raises(cp.CookieError) as exc:
        set_cookie(domain="com")
    assert exc.value.code == "public_suffix"


def test_longest_path_wins_when_reading():
    header = "sid=root; Path=/, sid=deep; Path=/admin"
    assert rules().select(header, "sid", "/admin/x") == "deep"
    assert rules().select(header, "sid", "/other") == "root"


def test_quoted_value_keeps_commas_and_quotes():
    parsed = rules().parse('a="x,y"; Path=/')
    assert parsed[0]["value"] == "x,y"


def test_max_age_takes_priority_over_expires():
    parsed = rules().parse("a=1; Max-Age=60; Expires=Wed, 21 Oct 2015 07:28:00 GMT")
    assert parsed[0]["max_age"] == 60


def test_invalid_expires_time_is_rejected():
    with pytest.raises(cp.CookieError) as exc:
        rules().parse("a=1; Expires=not-a-date")
    assert exc.value.code == "bad_expires"


def test_comma_in_value_is_not_split():
    parsed = rules().parse("a=1,2,3")
    assert len(parsed) == 1
    assert parsed[0]["value"] == "1,2,3"


def test_single_cookie_size_limit_is_enforced():
    with pytest.raises(cp.CookieError) as exc:
        rules(max_size=8).set_cookie("a", "123456789")
    assert exc.value.code == "too_large"


def test_delete_must_match_path_and_domain():
    value = set_cookie(name="sid", path="/admin", domain="example.com")
    assert "Path=/admin" in value
    assert "Domain=example.com" in value


def test_port_in_domain_is_rejected():
    with pytest.raises(cp.CookieError) as exc:
        set_cookie(domain="example.com:443")
    assert exc.value.code == "bad_domain"


def test_cookie_names_are_case_sensitive():
    parsed = rules().parse("SID=a; sid=b")
    assert len(parsed) == 1 or len(parsed) == 2
    assert [item["name"] for item in parsed] == ["SID", "sid"]


def test_attribute_whitespace_variants_are_equivalent():
    a = rules().parse("a=1;Path=/;Secure")
    b = rules().parse("a=1; Path=/ ; Secure")
    assert a[0]["value"] == b[0]["value"]
    assert a[0]["secure"] is True
    assert b[0]["secure"] is True


def test_parse_and_serialize_roundtrip_is_stable():
    original = rules().set_cookie("a", "x,y", path="/p", secure=True, httponly=True, samesite="Lax")
    parsed = rules().parse(original)[0]
    rebuilt = rules().set_cookie(
        parsed["name"], parsed["value"], path=parsed["path"], secure=parsed["secure"],
        httponly=parsed["httponly"], samesite=parsed["samesite"],
    )
    assert rules().parse(rebuilt)[0]["value"] == "x,y"
