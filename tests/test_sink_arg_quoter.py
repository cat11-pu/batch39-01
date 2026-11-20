import pytest

import sink_arg_quoter as sq


def test_space_is_quoted():
    assert sq.SinkArgQuoter.quote(["a b"]) == "'a b'"


def test_single_quote_is_escaped():
    assert sq.SinkArgQuoter.quote(["it's"]) == "'it'\\''s'"


def test_double_quote_roundtrips():
    argv = ['a"b']
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_dollar_sign_roundtrips():
    argv = ["$HOME"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv
    assert "$HOME" in sq.SinkArgQuoter.quote(argv)


def test_backtick_roundtrips():
    argv = [chr(96) + "id" + chr(96)]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_newline_roundtrips():
    argv = ["a\nb"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_glob_character_roundtrips():
    argv = ["*.log"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_empty_string_is_preserved():
    assert sq.SinkArgQuoter.quote([""]) == "''"
    assert sq.SinkArgQuoter.parse("''") == [""]


def test_leading_dash_is_not_treated_as_option():
    argv = ["-rf"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_leading_equals_is_not_treated_as_assignment():
    argv = ["=x"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_chinese_text_roundtrips():
    argv = ["巡检 任务"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_emoji_roundtrips():
    argv = ["done \U0001f600"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_nul_byte_is_rejected():
    with pytest.raises(sq.SinkArgError):
        sq.SinkArgQuoter.quote(["a\x00b"])


def test_mixed_argument_list_roundtrips_exactly():
    argv = ["", "a b", "it's", "$x", "中文", "*.py", "-v", "=1"]
    assert sq.SinkArgQuoter.parse(sq.SinkArgQuoter.quote(argv)) == argv


def test_quote_is_idempotent_after_parse():
    argv = ["a b", "c'd", ""]
    once = sq.SinkArgQuoter.quote(argv)
    twice = sq.SinkArgQuoter.quote(sq.SinkArgQuoter.parse(once))
    assert once == twice
