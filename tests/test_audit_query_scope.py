import pytest

import audit_query_scope as aq

RANKS = {"agent": 1, "lead": 2, "admin": 3}


def scope(role="agent", tenant="t-1", **over):
    kwargs = {"secret": "signing-secret", "tenant": tenant, "role": role, "role_rank": RANKS}
    kwargs.update(over)
    return aq.AuditQueryScope(**kwargs)


def record(id="r-1", tenant="t-1", actor="alice", role="agent", ts=5, deleted=False):
    return {
        "id": id,
        "tenant": tenant,
        "actor": actor,
        "actor_role": role,
        "ts": ts,
        "ip": "10.1.2.3",
        "email": "alice@example.com",
        "event": "login",
        "deleted": deleted,
    }


def request(**over):
    item = {"tenant": "t-1", "start": 0, "end": 10, "page_size": 20, "sort": "-ts", "keyword": "", "ids": []}
    item.update(over)
    return item


def test_cross_tenant_request_is_rejected():
    with pytest.raises(aq.AuditError) as exc:
        scope().query(request(tenant="t-2"), [record()])
    assert exc.value.code == "tenant_mismatch"


def test_role_hierarchy_hides_higher_rank_events():
    rows = scope(role="agent").query(request(), [record(id="a", role="agent"), record(id="b", role="admin")])["rows"]
    assert [row["id"] for row in rows] == ["a"]


def test_export_requires_sufficient_rank():
    with pytest.raises(aq.AuditError) as exc:
        scope(role="agent").export(request(), [record()])
    assert exc.value.code == "export_forbidden"


def test_time_range_longer_than_limit_is_rejected():
    with pytest.raises(aq.AuditError) as exc:
        scope().query(request(start=0, end=40), [record()])
    assert exc.value.code == "time_range"


def test_tampered_cursor_is_rejected():
    s = scope()
    first = s.query(request(page_size=1), [record(id="a"), record(id="b")])
    with pytest.raises(aq.AuditError) as exc:
        s.query(request(page_size=1, cursor=first["next_cursor"] + "x"), [record(id="a"), record(id="b")])
    assert exc.value.code == "bad_cursor"


def test_ip_and_email_are_masked():
    row = scope(role="admin").query(request(), [record()])["rows"][0]
    assert row["ip"] == "10.1.2.0"
    assert row["email"] == "a***@example.com"


def test_deleted_records_are_hidden_by_default():
    rows = scope(role="admin").query(request(), [record(id="a"), record(id="b", deleted=True)])["rows"]
    assert [row["id"] for row in rows] == ["a"]


def test_sort_field_must_be_whitelisted():
    with pytest.raises(aq.AuditError) as exc:
        scope().query(request(sort="password"), [record()])
    assert exc.value.code == "sort_not_allowed"


def test_total_counts_only_visible_rows():
    result = scope(role="agent").query(request(), [record(id="a"), record(id="b", role="admin")])
    assert result["total"] == 1


def test_ids_from_another_tenant_are_rejected():
    with pytest.raises(aq.AuditError) as exc:
        scope(role="admin").query(request(ids=["r-2"]), [record(id="r-2", tenant="t-2")])
    assert exc.value.code == "cross_tenant_id"


def test_keyword_is_matched_literally():
    result = scope(role="admin").query(request(keyword="a' OR 1=1"), [record()])
    assert result["rows"] == []


def test_page_size_is_capped():
    records = [record(id="r-%d" % i, ts=i) for i in range(150)]
    result = scope(role="admin").query(request(page_size=1000), records)
    assert len(result["rows"]) <= 100


def test_export_is_capped_and_flagged():
    records = [record(id="r-%d" % i, ts=i) for i in range(1200)]
    result = scope(role="admin").export(request(), records)
    assert len(result["rows"]) <= 1000
    assert result["truncated"] is True


def test_export_carries_actor_and_watermark():
    result = scope(role="admin").export(request(), [record()])
    assert result["watermark"]["actor"] == "alice" or result["watermark"]["actor"] == "admin"
    assert "at" in result["watermark"]


def test_query_snapshot_is_stable_and_ordered():
    s = scope(role="admin")
    records = [record(id="b", ts=2), record(id="a", ts=1)]
    first = s.query(request(), records)
    second = s.query(request(), records)
    assert first == second
    assert [row["id"] for row in first["rows"]] == ["b", "a"]
