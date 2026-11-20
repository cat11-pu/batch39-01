import json

import pytest

import trusted_device_ledger as td


def registry(**over):
    kwargs = {"max_devices": 5, "ttl": 30 * 86400, "idle": 7 * 86400, "grace": 300}
    kwargs.update(over)
    return td.TrustedDeviceRegistry(**kwargs)


def enroll(r, device="dev-1", name="desk", fp="fp-1", now=0, strong=True):
    return r.enroll("u-1", device, name, fp, strong, now)["token"]


def test_copied_credential_on_another_device_is_rejected():
    r = registry()
    token = enroll(r)
    with pytest.raises(td.DeviceError) as exc:
        r.use(token, "dev-2", "fp-1", 1)
    assert exc.value.code == "device_mismatch"


def test_region_change_requires_reauthentication():
    r = registry()
    token = enroll(r)
    assert r.use(token, "dev-1", "fp-1", 1, region="region-a")["user_id"] == "u-1"
    with pytest.raises(td.DeviceError) as exc:
        r.use(token, "dev-1", "fp-1", 2, region="region-b")
    assert exc.value.code == "reauth_required"


def test_revoke_removes_device_from_snapshot():
    r = registry()
    enroll(r)
    r.revoke("u-1", "dev-1")
    assert r.snapshot()["devices"] == []


def test_revoke_user_invalidates_all_credentials():
    r = registry()
    token = enroll(r)
    r.revoke_user("u-1")
    with pytest.raises(td.DeviceError):
        r.use(token, "dev-1", "fp-1", 1)


def test_device_name_is_escaped_in_snapshot():
    r = registry()
    enroll(r, name="<script>alert(1)</script>")
    stored = r.snapshot()["devices"][0]["name"]
    assert "<script>" not in stored
    assert "&lt;script&gt;" in stored


def test_enrollment_requires_strong_auth():
    with pytest.raises(td.DeviceError) as exc:
        registry().enroll("u-1", "dev-1", "desk", "fp-1", False, 0)
    assert exc.value.code == "strong_auth_required"


def test_device_credential_expires():
    r = registry(ttl=10)
    token = enroll(r, now=0)
    with pytest.raises(td.DeviceError) as exc:
        r.use(token, "dev-1", "fp-1", 11)
    assert exc.value.code == "expired"


def test_fingerprint_change_is_rejected():
    r = registry()
    token = enroll(r, fp="fp-1")
    with pytest.raises(td.DeviceError) as exc:
        r.use(token, "dev-1", "fp-2", 1)
    assert exc.value.code == "device_mismatch"


def test_revoked_credential_stops_working():
    r = registry()
    token = enroll(r)
    r.revoke("u-1", "dev-1")
    with pytest.raises(td.DeviceError):
        r.use(token, "dev-1", "fp-1", 1)


def test_device_count_limit_is_enforced():
    r = registry(max_devices=1)
    enroll(r, device="dev-1")
    with pytest.raises(td.DeviceError) as exc:
        enroll(r, device="dev-2", fp="fp-2")
    assert exc.value.code == "too_many_devices"


def test_rotation_keeps_old_token_read_only_during_grace():
    r = registry(grace=30)
    old = enroll(r)
    new = r.rotate(old, 1)["token"]
    assert r.use(old, "dev-1", "fp-1", 2)["read_only"] is True
    with pytest.raises(td.DeviceError) as exc:
        r.use(old, "dev-1", "fp-1", 2, write=True)
    assert exc.value.code == "read_only"
    assert r.use(new, "dev-1", "fp-1", 2)["user_id"] == "u-1"


def test_last_seen_is_updated_on_use():
    r = registry()
    token = enroll(r)
    r.use(token, "dev-1", "fp-1", 50)
    assert r.snapshot()["devices"][0]["last_seen"] == 50


def test_revoke_is_audited():
    r = registry()
    enroll(r)
    r.revoke("u-1", "dev-1")
    assert any(entry["action"] == "revoke" for entry in r.snapshot()["audit"])


def test_snapshot_does_not_contain_credentials():
    r = registry()
    token = enroll(r)
    assert token not in json.dumps(r.snapshot())


def test_device_list_is_stably_sorted():
    r = registry()
    enroll(r, device="dev-b", fp="fp-b", now=2)
    enroll(r, device="dev-a", fp="fp-a", now=1)
    devices = [item["device_id"] for item in r.snapshot()["devices"]]
    assert devices == ["dev-a", "dev-b"]
