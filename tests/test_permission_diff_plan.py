import permission_diff_plan as pd

HIGH = ("iam:DeleteUser", "iam:CreateAccessKey")


def stmt(principal="user:alice", action="s3:GetObject", resource="arn:aws:s3:::bucket/*", effect="allow", condition=None):
    return {
        "principal": principal,
        "action": action,
        "resource": resource,
        "effect": effect,
        "condition": condition or {},
    }


def plan(high=HIGH):
    return pd.PermissionDiffPlan(high_risk=high)


def test_wildcard_actions_are_expanded():
    before = [stmt(action="s3:*")]
    after = [stmt(action="s3:GetObject"), stmt(action="s3:PutObject")]
    result = plan().diff(before, after)
    assert result["added"] == []
    assert result["removed"] == []


def test_net_changes_are_reported():
    result = plan().diff([stmt(action="s3:GetObject")], [stmt(action="s3:PutObject")])
    assert [item["action"] for item in result["added"]] == ["s3:PutObject"]
    assert [item["action"] for item in result["removed"]] == ["s3:GetObject"]


def test_deny_statements_are_grouped_and_override_allow():
    result = plan().diff([], [stmt(effect="deny")])
    assert len(result["denied"]) == 1


def test_condition_key_changes_are_listed():
    before = [stmt(condition={"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}})]
    after = [stmt(condition={"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}, "Bool": {"aws:SecureTransport": "true"}})]
    result = plan().diff(before, after)
    assert "Bool" in str(result["changed"])


def test_resources_are_normalized_before_comparison():
    before = [stmt(resource="ARN:AWS:S3:::BUCKET//*")]
    after = [stmt(resource="arn:aws:s3:::bucket/*")]
    result = plan().diff(before, after)
    assert result["added"] == [] and result["removed"] == []


def test_not_action_is_expanded_to_exclusions():
    before = [stmt(action="NotAction:iam:DeleteUser")]
    after = [stmt(action="s3:GetObject")]
    result = plan().diff(before, after)
    assert result["counts"]["removed"] >= 0


def test_principal_type_change_is_marked_as_replacement():
    result = plan().diff([stmt(principal="group:devs")], [stmt(principal="role:devs")])
    assert result["replaced"]


def test_policy_version_upgrade_is_flagged():
    result = plan().diff([stmt(principal="user:alice")], [stmt(principal="user:alice")], )
    assert "version_note" in result


def test_duplicate_statements_are_deduplicated():
    result = plan().diff([stmt(), stmt()], [stmt()])
    assert result["added"] == [] and result["removed"] == []


def test_reordering_is_not_a_change():
    a = stmt(action="s3:GetObject")
    b = stmt(action="s3:PutObject")
    assert plan().diff([a, b], [b, a])["added"] == []


def test_unknown_actions_go_to_confirmation_list():
    result = plan().diff([], [stmt(action="madeup:DoThing")])
    assert [item["action"] for item in result["unknown"]] == ["madeup:DoThing"]


def test_action_case_is_folded():
    result = plan().diff([stmt(action="S3:GetObject")], [stmt(action="s3:getobject")])
    assert result["added"] == [] and result["removed"] == []


def test_scope_narrowing_is_marked():
    before = [stmt(resource="arn:aws:s3:::bucket/*")]
    after = [stmt(resource="arn:aws:s3:::bucket/public/*")]
    assert result["narrowed"]


def test_high_risk_actions_get_their_own_section():
    result = plan().diff([], [stmt(action="iam:DeleteUser")])
    assert result["high_risk"]


def test_counts_and_order_are_stable():
    before = [stmt(action="s3:GetObject")]
    after = [stmt(action="s3:PutObject")]
    first = plan().diff(before, after)
    second = plan().diff(before, after)
    assert first == second
    assert first["counts"]["added"] == 1
