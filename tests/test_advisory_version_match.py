import pytest

import advisory_version_match as av


def adv(id="A-1", package="pkg", ranges=None, severity="high", fixed=None):
    return {"id": id, "package": package, "ranges": ranges or [("<", "2.0.0")], "severity": severity, "fixed": fixed}


def match(package, version, advisories, rename=None):
    return av.AdvisoryVersionMatch(rename=rename).match(package, version, advisories)


def test_lexicographic_comparison_is_not_used():
    result = match("pkg", "1.0.2", [adv(ranges=[("<", "1.0.10")])])
    assert result["affected"] is True


def test_prerelease_sorts_below_release():
    result = match("pkg", "1.0.0-rc1", [adv(ranges=[("<", "1.0.0")])])
    assert result["affected"] is True


def test_disjoint_ranges_are_both_evaluated():
    ranges = [(">=", "1.0.0"), ("<", "2.0.0"), (">=", "3.0.0"), ("<", "4.0.0")]
    assert match("pkg", "3.5.0", [adv(ranges=ranges)])["affected"] is True


def test_wildcard_range_matches_patch_versions():
    assert match("pkg", "1.2.7", [adv(ranges=[("=", "1.2.*")])])["affected"] is True


def test_build_metadata_is_ignored_in_comparison():
    assert match("pkg", "1.2.3+build.9", [adv(ranges=[("=", "1.2.3")])])["affected"] is True


def test_epoch_makes_version_newer():
    assert match("pkg", "1!1.0.0", [adv(ranges=[("<", "2.0.0")])])["affected"] is False


def test_fixed_version_is_not_affected():
    result = match("pkg", "2.0.0", [adv(ranges=[("<", "2.0.0")])])
    assert result["affected"] is False


def test_package_rename_is_applied():
    result = match("new-name", "1.0.0", [adv(package="old-name")], rename={"old-name": "new-name"})
    assert result["affected"] is True


def test_duplicate_advisories_merge_to_highest_severity():
    result = match("pkg", "1.0.0", [adv(id="A-1", severity="low"), adv(id="A-1", severity="critical")])
    assert result["advisories"] == ["A-1"]
    assert result["severity"] == "critical"


def test_leading_zero_version_goes_to_isolation():
    result = match("pkg", "01.2.3", [adv()])
    assert result["isolated"] is True
    assert result["affected"] is False


def test_non_numeric_version_goes_to_isolation():
    result = match("pkg", "1.x.3", [adv()])
    assert result["isolated"] is True


def test_package_name_is_case_insensitive():
    assert match("PKG", "1.0.0", [adv(package="pkg")])["affected"] is True


def test_empty_range_matches_nothing():
    assert match("pkg", "1.0.0", [adv(ranges=[])])["affected"] is False


def test_full_range_matches_any_version():
    assert match("pkg", "9.9.9", [adv(ranges=[(">=", "0")])])["affected"] is True


def test_overlapping_ranges_do_not_duplicate_advisory_id():
    ranges = [(">=", "1.0.0"), ("<", "3.0.0"), (">=", "2.0.0"), ("<", "4.0.0")]
    result = match("pkg", "2.5.0", [adv(id="A-9", ranges=ranges)])
    assert result["advisories"] == ["A-9"]
