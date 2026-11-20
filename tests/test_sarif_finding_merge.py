import sarif_finding_merge as sf


def finding(**over):
    item = {
        "rule": "R-1",
        "path": "C:\\work\\src\\a.py",
        "line": 10,
        "column": 1,
        "severity": "high",
        "message": "bad thing",
        "fingerprint": "fp-1",
        "suppressed": False,
        "artifact_index": 0,
    }
    item.update(over)
    return item


def report(findings, artifacts=None):
    return {"run": "r", "artifacts": artifacts if artifacts is not None else ["C:\\work\\src\\a.py"], "findings": findings}


def merge(reports, baseline=None, **over):
    kwargs = {"workdir": "C:\\work", "case_sensitive": False}
    kwargs.update(over)
    return sf.SarifFindingMerge(**kwargs).merge(reports, baseline=baseline)


def test_windows_and_uri_paths_are_normalized_to_one():
    result = merge([
        report([finding(path="C:\\work\\src\\a.py")]),
        report([finding(path="file:///C:/work/src/a.py")]),
    ])
    assert len(result["findings"]) == 1


def test_workdir_prefix_is_removed():
    result = merge([report([finding(path="C:\\work\\src\\a.py")])])
    assert result["findings"][0]["path"] == "src/a.py"


def test_percent_escaped_path_is_decoded():
    result = merge([report([finding(path="C:\\work\\src\\a%2Eb.py")])])
    assert result["findings"][0]["path"] == "src/a.b.py"


def test_partial_fingerprint_falls_back_to_stable_key():
    result = merge([
        report([finding(fingerprint="abc", message="one")]),
        report([finding(fingerprint="abc", message="one")]),
    ])
    assert len(result["findings"]) == 1


def test_different_columns_are_not_merged():
    result = merge([report([finding(column=1), finding(column=5)])])
    assert len(result["findings"]) == 2


def test_severity_names_are_mapped_to_four_levels():
    result = merge([report([finding(severity="fatal"), finding(severity="warning"), finding(severity="note")])])
    levels = [item["severity"] for item in result["findings"]]
    assert levels == ["high", "medium", "low"]


def test_suppressed_findings_are_listed_separately():
    result = merge([report([finding(suppressed=True)])])
    assert result["findings"] == []
    assert len(result["suppressed"]) == 1


def test_baseline_diff_uses_fingerprints():
    result = merge([report([finding(fingerprint="fp-1"), finding(fingerprint="fp-2")])], baseline=["fp-1"])
    assert [item["fingerprint"] for item in result["new"]] == ["fp-2"]
    assert result["fixed"] == ["fp-1"]


def test_rule_ids_are_lowercased():
    result = merge([report([finding(rule="RULE-X"), finding(rule="rule-x")])])
    assert len(result["findings"]) == 1
    assert result["findings"][0]["rule"] == "rule-x"


def test_line_zero_is_flagged_not_treated_as_first_line():
    result = merge([report([finding(line=0)])])
    assert result["findings"][0]["whole_file"] is True


def test_missing_artifact_index_is_reported():
    result = merge([report([finding(artifact_index=3)], artifacts=["only-one"])])
    assert "artifact_missing" in result["warnings"]


def test_message_newlines_are_normalized():
    result = merge([report([finding(message="a\r\nb")])])
    assert "\n" not in result["findings"][0]["message"]


def test_report_order_does_not_change_output():
    a = report([finding(fingerprint="fp-1")])
    b = report([finding(fingerprint="fp-2")])
    first = merge([a, b])
    second = merge([b, a])
    assert first == second


def test_overlapping_regions_merge_when_majority_overlap():
    result = merge([report([finding(column=1), finding(column=5)])], overlap=0.5)
    assert len(result["findings"]) == 1


def test_output_is_stably_sorted():
    result = merge([report([finding(path="C:\\work\\b.py"), finding(path="C:\\work\\a.py")])])
    assert [item["path"] for item in result["findings"]] == ["a.py", "b.py"]
