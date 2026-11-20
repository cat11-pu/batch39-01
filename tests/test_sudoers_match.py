import pytest

import sudoers_match as sm


def rules(text, aliases=None):
    return sm.SudoersMatch(text, aliases=aliases)


def check(text, user="alice", host="web-1", command="/bin/ls", args=(), runas=None, aliases=None):
    return rules(text, aliases).check(user, host, command, args=args, runas=runas)


def test_last_matching_rule_wins():
    text = "alice ALL=(root) /bin/ls\nalice ALL=(root) !/bin/ls"
    result = check(text)
    assert result["allowed"] is False


def test_host_suffix_wildcard_does_not_match_parent_domain():
    result = check("alice example.com=(root) /bin/ls", host="dev.example.com")
    assert result["allowed"] is False


def test_command_args_must_match_item_by_item():
    text = "alice ALL=(root) /bin/ls /tmp/a"
    assert check(text, args=("/tmp/a",))["allowed"] is True
    assert check(text, args=("/tmp/b",))["allowed"] is False


def test_command_wildcard_does_not_cross_path_separator():
    text = "alice ALL=(root) /bin/cat /var/*"
    assert check(text, command="/bin/cat", args=("/var/log/x",))["allowed"] is True
    assert check(text, command="/bin/cat", args=("/var/log/sub/x",))["allowed"] is False


def test_alias_declared_before_use_is_resolved():
    result = check("User_Alias DEVS = alice\nDEVS ALL=(root) /bin/ls")
    assert result["allowed"] is True


def test_include_rule_is_loaded_in_order():
    result = check("alice ALL=(root) /bin/ls\n@include extra", aliases={"extra": "alice ALL=(root) !/bin/ls"})
    assert result["allowed"] is False


def test_nopasswd_tag_does_not_change_allowance():
    result = check("alice ALL=(root) NOPASSWD: /bin/ls")
    assert result["allowed"] is True
    assert result["password_required"] is False


def test_empty_runas_defaults_to_current_user():
    result = check("alice ALL=() /bin/ls", runas=None)
    assert result["allowed"] is True
    assert result["runas"] == "alice"


def test_user_name_is_case_insensitive():
    assert check("Alice ALL=(root) /bin/ls", user="alice")["allowed"] is True


def test_missing_digest_does_not_allow_command():
    result = check("alice ALL=(root) sha256:deadbeef /bin/ls")
    assert result["allowed"] is False
    assert result["needs_digest"] is True


def test_negated_rule_is_marked():
    result = check("alice ALL=(root) !/bin/ls")
    assert result["negated"] is True


def test_four_part_rule_is_parsed():
    result = check("alice ALL=(root) /bin/ls")
    assert result["user"] == "alice"
    assert result["host"] == "ALL"


def test_reason_is_returned():
    result = check("alice ALL=(root) /bin/ls")
    assert result["reason"]


def test_snapshot_is_stable_between_checks():
    s = rules("alice ALL=(root) /bin/ls")
    first = s.check("alice", "web-1", "/bin/ls")
    second = s.check("alice", "web-1", "/bin/ls")
    assert first == second


def test_deny_rule_after_alias_use_wins():
    text = "User_Alias DEVS = alice\nDEVS ALL=(root) /bin/ls\nalice ALL=(root) !/bin/ls"
    assert check(text)["allowed"] is False
