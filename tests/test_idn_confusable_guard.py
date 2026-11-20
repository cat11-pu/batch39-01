import idn_confusable_guard as ig

BRANDS = ["paypal"]


def guard(**over):
    kwargs = {"protected_brands": BRANDS, "blacklist": (), "max_length": 253}
    kwargs.update(over)
    return ig.IdnConfusableGuard(**kwargs)


def test_cyrillic_latin_mix_is_high_risk():
    result = guard().evaluate("p\u0430ypal.com")
    assert result["risk"] == "high"
    assert "mixed_script" in result["rules"]


def test_confusable_skeleton_matches_protected_brand():
    result = guard().evaluate("p\u0430ypal.com")
    assert "confusable_brand" in result["rules"]
    assert result["normalized"].endswith("paypal.com")


def test_punycode_is_decoded_and_reported():
    unicode_domain = "p\u0430ypal.com"
    ascii_domain = unicode_domain.encode("idna").decode("ascii")
    result = guard().evaluate(ascii_domain)
    assert result["ascii"] == ascii_domain
    assert "punycode" in result["rules"]
    assert "\u0430" in result["normalized"]


def test_ideographic_full_stop_is_a_dot_variant():
    result = guard().evaluate("paypal\u3002com")
    assert result["normalized"] == "paypal.com"
    assert "dot_variant" in result["rules"]


def test_trailing_dot_is_ignored_but_flagged():
    result = guard().evaluate("paypal.com.")
    assert result["normalized"] == "paypal.com"
    assert "trailing_dot" in result["rules"]


def test_ascii_case_is_folded():
    result = guard().evaluate("PAYPAL.COM")
    assert result["normalized"] == "paypal.com"
    assert result["risk"] == "low"


def test_zero_width_character_is_suspicious():
    result = guard().evaluate("pay\u200bpal.com")
    assert result["risk"] == "high"
    assert "invisible_char" in result["rules"]


def test_bidi_control_is_suspicious():
    result = guard().evaluate("pay\u202epal.com")
    assert result["risk"] == "high"
    assert "bidi_control" in result["rules"]


def test_digit_letter_confusable_is_detected():
    result = guard().evaluate("paypa1.com")
    assert "confusable_brand" in result["rules"]


def test_brand_in_subdomain_is_flagged():
    result = guard().evaluate("paypal.com.evil.net")
    assert result["risk"] == "high"
    assert "brand_in_subdomain" in result["rules"]


def test_email_domain_is_extracted():
    result = guard().evaluate("user@paypal.com")
    assert result["normalized"] == "paypal.com"
    assert result["risk"] == "low"


def test_blacklist_hit_is_high_risk():
    result = guard(blacklist=["evil.com"]).evaluate("EVIL.COM.")
    assert result["risk"] == "high"
    assert "blacklisted" in result["rules"]


def test_overlong_domain_is_rejected_by_rule():
    result = guard().evaluate("a" * 260 + ".com")
    assert "length_limit" in result["rules"]


def test_reserved_hyphen_positions_are_flagged():
    result = guard().evaluate("ab--cd.com")
    assert "reserved_hyphen" in result["rules"]


def test_report_keeps_both_normalized_and_ascii_forms():
    result = guard().evaluate("p\u0430ypal.com.")
    assert result["normalized"] == "p\u0430ypal.com"
    assert result["ascii"].startswith("xn--")
    assert "punycode" in result["rules"]
    assert "trailing_dot" in result["rules"]
