import pytest

import password_unicode_policy as pp


def policy(**over):
    kwargs = {"min_len": 8, "max_len": 64, "max_bytes": 128, "common": (), "breached_prefixes": (), "policy_version": "v1"}
    kwargs.update(over)
    return pp.PasswordUnicodePolicy(**kwargs)


def test_fullwidth_and_halfwidth_normalize_to_same_value():
    p = policy()
    assert p.normalize("ＡＢＣ１２３") == p.normalize("ABC123")


def test_byte_length_limit_is_enforced():
    with pytest.raises(pp.PasswordError) as exc:
        policy(max_bytes=10).check("密码密码密码")
    assert exc.value.code == "too_long"


def test_emoji_is_counted_by_grapheme_cluster():
    result = policy(min_len=2, max_len=10).check("\U0001f600\U0001f600")
    assert result["graphemes"] == 2


def test_zero_width_character_is_rejected():
    with pytest.raises(pp.PasswordError) as exc:
        policy().check("pass\u200bword1")
    assert exc.value.code == "invalid"


def test_confusable_username_is_detected_by_skeleton():
    with pytest.raises(pp.PasswordError) as exc:
        policy().check("p\u0430ypal123", username="paypal")
    assert "username_contained" in exc.value.rules


def test_pinyin_weak_password_is_rejected():
    with pytest.raises(pp.PasswordError):
        policy(common={"woaini123"}).check("woaini123")


def test_repeated_characters_are_rejected():
    with pytest.raises(pp.PasswordError):
        policy().check("aaaaaaaa")


def test_username_containment_is_rejected():
    with pytest.raises(pp.PasswordError) as exc:
        policy().check("alice12345", username="alice")
    assert "username_contained" in exc.value.rules


def test_breached_prefix_is_rejected():
    with pytest.raises(pp.PasswordError) as exc:
        policy(breached_prefixes={"abc"}).check("abc12345")
    assert "breached" in exc.value.rules


def test_leading_and_trailing_space_warn_but_are_not_trimmed():
    result = policy().check(" pass1234 ")
    assert "leading_trailing_space" in result["warnings"]
    assert result["ok"] is True


def test_nul_byte_is_rejected():
    with pytest.raises(pp.PasswordError):
        policy().check("pass\x001234")


def test_normalized_length_boundary_is_checked():
    result = policy(min_len=8, max_len=8).check("ＡＢＣＤＥＦＧＨ")
    assert result["graphemes"] == 8


def test_error_codes_do_not_leak_specific_rule():
    with pytest.raises(pp.PasswordError) as exc:
        policy(common={"password1"}).check("password1")
    assert exc.value.code == "weak"
    assert "password1" not in str(exc.value)


def test_result_reports_policy_version_and_rule_ids():
    result = policy(policy_version="v7").check("Xk9#mQ2!z")
    assert result["version"] == "v7"
    assert isinstance(result["rules"], list)


def test_family_emoji_counts_as_one_grapheme():
    result = policy(min_len=1, max_len=2).check("\U0001f468\u200d\U0001f469\u200d\U0001f467")
    assert result["graphemes"] == 1
