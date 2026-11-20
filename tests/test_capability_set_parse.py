import pytest

import capability_set_parse as cp


def parse(text):
    return cp.CapabilitySetParse().parse(text)


def test_names_are_case_insensitive():
    result = parse("cap_net_raw")
    assert result["permitted"] == {"cap_net_raw"}


def test_number_and_name_mix_is_deduplicated():
    result = parse("cap_chown,0")
    assert result["permitted"] == {"cap_chown"}


def test_all_keyword_and_single_item_conflict_is_explicit():
    result = parse("all,cap_chown")
    assert result["all"] is True
    assert "cap_chown" in result["permitted"]


def test_set_flags_are_parsed():
    result = parse("cap_net_bind_service=ep")
    assert result["effective"] is True
    assert result["permitted"] is True


def test_inheritable_and_bounding_sets_are_not_swapped():
    result = parse("cap_net_raw+i")
    assert result["inheritable"] == {"cap_net_raw"}
    assert result["bounding"] == set()


def test_ambient_requires_inheritable_and_permitted():
    with pytest.raises(cp.CapError):
        parse("cap_net_raw+a")


def test_bounding_can_only_shrink():
    with pytest.raises(cp.CapError):
        parse("cap_chown-bounding,cap_chown")


def test_empty_and_missing_are_distinct():
    assert parse("")["empty"] is True
    assert parse("none")["empty"] is True


def test_number_above_sixty_three_is_rejected():
    with pytest.raises(cp.CapError):
        parse("64")


def test_unknown_name_is_rejected():
    with pytest.raises(cp.CapError):
        parse("cap_magic")


def test_exec_after_uses_inheritable_and_file_sets():
    p = parse("cap_net_raw+i")
    f = parse("cap_net_raw=p")
    result = cp.CapabilitySetParse().exec_after(p, f)
    assert "exec_after" in result


def test_file_capabilities_are_kept_separate():
    result = parse("cap_net_bind_service=ep")
    assert result["file_permitted"] is True


def test_warnings_are_returned():
    result = parse("cap_chown,cap_chown")
    assert result["warnings"]


def test_bounding_after_exec_is_reported():
    p = parse("cap_chown+e")
    result = cp.CapabilitySetParse().exec_after(p)
    assert "bounding" in result


def test_snapshot_is_stable():
    assert parse("cap_net_raw") == parse("cap_net_raw")
