class DeviceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


import hashlib
import html
import secrets


MAX_NAME_LENGTH = 64


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_name(name):
    if not isinstance(name, str) or not name:
        raise DeviceError("invalid_name")
    if len(name) > MAX_NAME_LENGTH:
        raise DeviceError("invalid_name")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise DeviceError("invalid_name")


class TrustedDeviceRegistry:
    def __init__(self, max_devices=5, ttl=30 * 86400, idle=7 * 86400, grace=300):
        self.max_devices = max_devices
        self.ttl = ttl
        self.idle = idle
        self.grace = grace
        self._devices = {}
        self._tokens = {}
        self._audit = []

    def enroll(self, user_id, device_id, name, fingerprint, strong_auth, now):
        if not strong_auth:
            raise DeviceError("strong_auth_required")
        _validate_name(name)
        active = [
            d for d in self._devices.values()
            if d["user_id"] == user_id and not d["revoked"]
        ]
        if not any(d["device_id"] == device_id for d in active):
            if len(active) >= self.max_devices:
                raise DeviceError("too_many_devices")
        device = {
            "user_id": user_id,
            "device_id": device_id,
            "name": name,
            "fingerprint": fingerprint,
            "enrolled_at": now,
            "last_seen": now,
            "region": None,
            "revoked": False,
        }
        self._devices[(user_id, device_id)] = device
        self._audit.append({
            "action": "enroll",
            "user_id": user_id,
            "device_id": device_id,
            "at": now,
        })
        return {"token": self._issue_token(device, now)}

    def _issue_token(self, device, now):
        token = secrets.token_hex(32)
        self._tokens[_digest(token)] = {
            "user_id": device["user_id"],
            "device_id": device["device_id"],
            "fingerprint": device["fingerprint"],
            "enrolled_at": device["enrolled_at"],
            "issued_at": now,
            "grace_until": None,
        }
        return token

    def _lookup(self, token, device_id, fingerprint, now):
        record = self._tokens.get(_digest(token))
        if record is None:
            raise DeviceError("unknown_token")
        device = self._devices.get((record["user_id"], record["device_id"]))
        if device is None or device["revoked"]:
            raise DeviceError("revoked")
        if record["grace_until"] is not None and now > record["grace_until"]:
            raise DeviceError("expired")
        if now - record["enrolled_at"] > self.ttl:
            raise DeviceError("expired")
        if now - device["last_seen"] > self.idle:
            raise DeviceError("expired")
        if record["device_id"] != device_id or record["fingerprint"] != fingerprint:
            raise DeviceError("device_mismatch")
        return record, device

    def use(self, token, device_id, fingerprint, now, write=False, region=None):
        record, device = self._lookup(token, device_id, fingerprint, now)
        read_only = record["grace_until"] is not None
        if read_only and write:
            raise DeviceError("read_only")
        if region is not None:
            if device["region"] is not None and device["region"] != region:
                raise DeviceError("reauth_required")
            device["region"] = region
        device["last_seen"] = now
        return {"user_id": record["user_id"], "read_only": read_only}

    def rotate(self, token, now):
        record = self._tokens.get(_digest(token))
        if record is None:
            raise DeviceError("unknown_token")
        device = self._devices.get((record["user_id"], record["device_id"]))
        if device is None or device["revoked"]:
            raise DeviceError("revoked")
        record["grace_until"] = now + self.grace
        self._audit.append({
            "action": "rotate",
            "user_id": record["user_id"],
            "device_id": record["device_id"],
            "at": now,
        })
        return {"token": self._issue_token(device, now)}

    def revoke(self, user_id, device_id):
        device = self._devices.get((user_id, device_id))
        if device is not None:
            device["revoked"] = True
        self._audit.append({
            "action": "revoke",
            "user_id": user_id,
            "device_id": device_id,
            "at": device["last_seen"] if device else None,
        })

    def revoke_user(self, user_id):
        for device in self._devices.values():
            if device["user_id"] == user_id:
                device["revoked"] = True
        self._audit.append({
            "action": "revoke_user",
            "user_id": user_id,
            "device_id": None,
            "at": None,
        })

    def snapshot(self):
        devices = [
            {
                "user_id": d["user_id"],
                "device_id": d["device_id"],
                "name": html.escape(d["name"]),
                "enrolled_at": d["enrolled_at"],
                "last_seen": d["last_seen"],
            }
            for d in self._devices.values()
            if not d["revoked"]
        ]
        devices.sort(key=lambda d: (d["enrolled_at"], d["device_id"]))
        return {"devices": devices, "audit": list(self._audit)}
