import base64

import authorized_keys_fence as ak

KEY = "AAAAB3NzaC1yc2EAAAADAQABAAABAQC7"


def line(options="", key_type="ssh-rsa", blob=KEY, comment="user@host"):
    prefix = options + " " if options else ""
    return prefix + key_type + " " + blob + (" " + comment if comment else "")


def parse(text):
    return ak.AuthorizedKeysFence().parse(text)


def test_command_option_with_spaces_is_preserved():
    text = 'command="cd /srv && ./run --flag" ' + line()
    entry = parse(text)["entries"][0]
    assert "cd /srv" in entry["options"]["command"]


def test_multiple_source_networks_are_all_kept():
    entry = parse('from="10.0.0.0/8,192.168.0.0/16" ' + line())["entries"][0]
    assert len(entry["options"]["from"]) == 2


def test_no_value_options_do_not_shift_key_type():
    entry = parse("no-pty,no-port-forwarding " + line())["entries"][0]
    assert entry["key_type"] == "ssh-rsa"


def test_duplicate_key_is_merged_by_fingerprint():
    result = parse(line(comment="a") + "\n" + line(comment="b"))
    assert len(result["entries"]) == 1
    assert result["entries"][0]["comment"] == "a"


def test_invalid_base64_skips_only_that_line():
    result = parse(line() + "\n" + line(blob="!!!") + "\n" + line(blob=KEY))
    assert len(result["entries"]) == 2
    assert result["counts"]["invalid"] == 1


def test_unknown_key_type_is_flagged():
    result = parse(line(key_type="ssh-magic"))
    assert result["counts"]["unknown_type"] == 1


def test_comment_newline_is_stripped():
    entry = parse(line(comment="hello\nworld"))["entries"][0]
    assert "\n" not in entry["comment"]


def test_weak_key_length_is_flagged():
    result = parse(line(blob=base64.b64encode(b"\x00" * 64).decode()))
    assert result["counts"]["weak"] >= 1


def test_unknown_option_is_counted():
    result = parse("mystery-option " + line())
    assert result["counts"]["unknown_option"] == 1


def test_line_numbers_are_reported():
    entry = parse(line() + "\n" + line(comment="second"))["entries"][0]
    assert entry["line"] == 1


def test_duplicate_keeps_first_line_number():
    result = parse(line() + "\n" + line(comment="dup"))
    assert result["entries"][0]["line"] == 1


def test_counts_report_empty_and_invalid_lines():
    result = parse("\n\n" + line() + "\n")
    assert result["counts"]["empty"] >= 2


def test_entries_are_sorted_by_line():
    text = line(comment="one") + "\n" + line(comment="two") + "\n" + line(comment="three")
    entries = parse(text)["entries"]
    assert [item["line"] for item in entries] == sorted(item["line"] for item in entries)


def test_fingerprint_is_stable_for_same_key():
    a = parse(line())["entries"][0]["fingerprint"]
    b = parse(line(comment="other"))["entries"][0]["fingerprint"]
    assert a == b


def test_scan_continues_after_bad_line():
    result = parse(line(blob="@@@") + "\n" + line() + "\n" + line(comment="last"))
    assert len(result["entries"]) == 2
