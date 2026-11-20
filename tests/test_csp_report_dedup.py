import csp_report_dedup as csp


def report(**over):
    item = {
        "site": "Shop.Example.com/",
        "directive": "script-src",
        "blocked": "https://cdn.example.com/a.js?nonce=1",
        "source": "https://shop.example.com/app.js",
        "line": 10,
        "column": 2,
        "disposition": "enforce",
    }
    item.update(over)
    return item


def ingest(reports, now=0, **over):
    kwargs = {"window": 120, "per_site_limit": 100, "detail_days": 30}
    kwargs.update(over)
    return csp.CspReportDedup(**kwargs).ingest(reports, now=now)


def test_query_string_is_removed_before_fingerprinting():
    result = ingest([report(blocked="https://cdn.example.com/a.js?x=1"), report(blocked="https://cdn.example.com/a.js?x=2")])
    assert result["counts"]["accepted"] == 1


def test_line_and_column_do_not_create_new_fingerprints():
    result = ingest([report(line=1, column=1), report(line=99, column=7)])
    assert result["counts"]["accepted"] == 1


def test_report_only_and_enforce_are_counted_separately():
    result = ingest([report(disposition="enforce"), report(disposition="report-only")])
    assert result["counts"]["enforce"] == 1
    assert result["counts"]["report_only"] == 1


def test_site_identifier_is_normalized():
    result = ingest([report(site="SHOP.EXAMPLE.COM/"), report(site="shop.example.com")])
    assert result["counts"]["accepted"] == 1


def test_malformed_record_does_not_fail_whole_batch():
    result = ingest([report(), {"site": None}])
    assert result["counts"]["accepted"] == 1
    assert result["counts"]["quarantined"] == 1


def test_batch_array_is_validated_per_record():
    result = ingest([report(), "not-a-dict", report(blocked="https://cdn.example.com/b.js")])
    assert result["counts"]["quarantined"] == 1
    assert result["counts"]["accepted"] == 2


def test_unknown_directive_goes_to_other_bucket():
    result = ingest([report(directive="unknown-thing")])
    assert result["counts"]["other"] == 1


def test_missing_disposition_defaults_to_report_only():
    item = report()
    item.pop("disposition")
    result = ingest([item])
    assert result["counts"]["report_only"] == 1


def test_identifiers_and_emails_are_masked():
    result = ingest([report(blocked="https://cdn.example.com/a.js?user=alice@example.com&token=abc")])
    blob = str(result["counts"])
    assert "alice@example.com" not in blob
    assert "token=abc" not in blob


def test_per_site_limit_triggers_sampling_flag():
    reports = [report(blocked="https://cdn.example.com/%d.js" % i) for i in range(10)]
    result = ingest(reports, per_site_limit=3)
    assert result["sites"]["shop.example.com"]["sampled"] is True


def test_duplicate_reports_inside_window_are_merged():
    result = ingest([report(), report()], now=10)
    assert result["counts"]["accepted"] == 1
    assert result["counts"]["merged"] == 1


def test_details_are_purged_after_retention_window():
    d = csp.CspReportDedup(detail_days=1)
    d.ingest([report()], now=0)
    d.ingest([], now=3 * 86400)
    assert d.snapshot()["details"] == []


def test_aggregate_count_matches_detail_count():
    d = csp.CspReportDedup()
    d.ingest([report(), report()], now=0)
    snap = d.snapshot()
    assert snap["counts"]["accepted"] == len(snap["details"])


def test_output_is_sorted_by_site_directive_and_count():
    result = ingest([report(site="b.example.com"), report(site="a.example.com")])
    assert sorted(result["sites"]) == list(result["sites"])


def test_repeated_ingest_is_idempotent_for_same_fingerprint():
    d = csp.CspReportDedup()
    d.ingest([report()], now=0)
    first = d.snapshot()["counts"]["accepted"]
    d.ingest([report()], now=1)
    second = d.snapshot()["counts"]["accepted"]
    assert first == second == 1
