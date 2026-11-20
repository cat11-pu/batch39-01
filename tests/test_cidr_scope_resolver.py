import pytest

import cidr_scope_resolver as cr


def resolver(allow, deny=(), default=False):
    return cr.CidrScopeResolver(allow=allow, deny=deny, allow_default_route=default)


def test_dotted_address_written_as_integer_is_normalized():
    result = resolver(["192.168.0.0/16"]).resolve("3232235777")
    assert result["allowed"] is True
    assert result["address"] == "192.168.1.1"


def test_port_and_whitespace_are_stripped():
    result = resolver(["192.168.0.0/16"]).resolve(" 192.168.1.5:443 ")
    assert result["allowed"] is True
    assert result["address"] == "192.168.1.5"


def test_ipv4_mapped_ipv6_is_treated_as_ipv4():
    result = resolver(["192.168.0.0/16"]).resolve("::ffff:192.168.1.5")
    assert result["allowed"] is True
    assert result["network"] == "192.168.0.0/16"


def test_host_bits_in_allow_network_are_cleared():
    result = resolver(["192.168.1.5/16"]).resolve("192.168.1.5")
    assert result["allowed"] is True
    assert result["network"] == "192.168.0.0/16"


def test_deny_rule_wins_over_overlapping_allow():
    result = resolver(["10.0.0.0/8"], ["10.1.0.0/16"]).resolve("10.1.2.3")
    assert result["allowed"] is False
    assert result["reason"] == "denied"


def test_ipv6_compressed_and_expanded_forms_are_equal():
    result = resolver(["2001:db8::/32"]).resolve("2001:0db8:0000:0000:0000:0000:0000:0001")
    assert result["allowed"] is True


def test_zone_id_is_removed_from_link_local_address():
    result = resolver(["fe80::/10"]).resolve("fe80::1%eth0")
    assert result["allowed"] is True
    assert "%" not in result["address"]


def test_default_route_is_rejected_unless_explicitly_enabled():
    with pytest.raises(cr.CidrError) as exc:
        resolver(["0.0.0.0/0"]).resolve("8.8.8.8")
    assert exc.value.code == "default_route"
    assert resolver(["0.0.0.0/0"], default=True).resolve("8.8.8.8")["allowed"] is True


def test_overlapping_allow_networks_are_merged_in_snapshot():
    snap = resolver(["10.0.0.0/8", "10.1.0.0/16"]).snapshot()
    assert snap["allow"] == ["10.0.0.0/8"]


def test_snapshot_is_sorted_and_detached():
    r = resolver(["192.168.0.0/16", "10.0.0.0/8"])
    snap = r.snapshot()
    assert snap["allow"] == ["10.0.0.0/8", "192.168.0.0/16"]
    snap["allow"].clear()
    assert r.snapshot()["allow"]


def test_invalid_address_characters_are_rejected():
    with pytest.raises(cr.CidrError):
        resolver(["10.0.0.0/8"]).resolve("10.0.0.1;DROP")


def test_prefix_longer_than_address_width_is_rejected():
    with pytest.raises(cr.CidrError):
        resolver(["10.0.0.0/33"])


def test_empty_address_is_rejected():
    with pytest.raises(cr.CidrError):
        resolver(["10.0.0.0/8"]).resolve("   ")


def test_repeated_resolution_is_identical():
    r = resolver(["10.0.0.0/8"])
    assert r.resolve("10.1.2.3") == r.resolve("10.1.2.3")


def test_result_reports_rule_number_and_reason():
    result = resolver(["10.0.0.0/8"]).resolve("10.1.2.3")
    assert result["allowed"] is True
    assert result["rule"] == 0
    assert result["reason"] == "allowed"
