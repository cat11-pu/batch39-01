import copy
import hashlib
import secrets


class SessionError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SessionRotateChain:
    ROTATION_REASONS = ("login", "privilege_change", "password_change", "tenant_switch")

    def __init__(self, idle_ttl=900, absolute_ttl=3600, grace=5, max_per_user=5):
        self.idle_ttl = idle_ttl
        self.absolute_ttl = absolute_ttl
        self.grace = grace
        self.max_per_user = max_per_user
        self._salt = secrets.token_hex(16)
        self._chains = {}
        self._tokens = {}
        self._user_chains = {}
        self._replay_rejected = 0
        self._audit = []
        self._chain_seq = 0

    def _digest(self, token):
        return hashlib.sha256((self._salt + token).encode("utf-8")).hexdigest()

    def _new_chain_id(self):
        self._chain_seq += 1
        return "chain-%d" % self._chain_seq

    def _record_audit(self, event, **detail):
        entry = {"event": event, "at": detail.pop("at", None)}
        entry.update(detail)
        self._audit.append(entry)

    def login(self, user_id, device_id, now, draft=None):
        active = [
            chain
            for chain in self._user_chains.get(user_id, ())
            if chain["active"]
        ]
        if len(active) >= self.max_per_user:
            raise SessionError("too_many_sessions")

        chain_id = self._new_chain_id()
        token = secrets.token_urlsafe(32)
        chain = {
            "chain_id": chain_id,
            "user_id": user_id,
            "device_id": device_id,
            "created_at": now,
            "absolute_deadline": now + self.absolute_ttl,
            "last_activity": now,
            "draft": copy.deepcopy(draft),
            "active": True,
            "end_reason": None,
        }
        self._chains[chain_id] = chain
        self._user_chains.setdefault(user_id, []).append(chain)
        self._tokens[self._digest(token)] = {
            "chain_id": chain_id,
            "generation": 0,
            "state": "head",
            "grace_deadline": None,
        }
        self._record_audit(
            "login", at=now, user_id=user_id, chain_id=chain_id, device_id=device_id
        )
        return {"token": token, "chain_id": chain_id, "user_id": user_id}

    def rotate(self, token, reason, now, draft=None):
        if reason not in self.ROTATION_REASONS:
            raise SessionError("invalid_reason")
        record = self._tokens.get(self._digest(token))
        if record is None:
            raise SessionError("invalid_token")
        chain = self._chains.get(record["chain_id"])
        if chain is None or not chain["active"] or record["state"] != "head":
            raise SessionError("invalid_token")

        self._check_lifetime(chain, now)

        head_digest = self._digest(token)
        for digest, other in self._tokens.items():
            if digest == head_digest:
                continue
            if other["chain_id"] != chain["chain_id"] or other["state"] != "grace":
                continue
            other["state"] = "retired"

        record["state"] = "grace"
        record["grace_deadline"] = now + self.grace

        new_token = secrets.token_urlsafe(32)
        self._tokens[self._digest(new_token)] = {
            "chain_id": chain["chain_id"],
            "generation": record["generation"] + 1,
            "state": "head",
            "grace_deadline": None,
        }
        chain["last_activity"] = now
        if draft is not None:
            chain["draft"] = copy.deepcopy(draft)
        self._record_audit(
            "rotation",
            at=now,
            user_id=chain["user_id"],
            chain_id=chain["chain_id"],
            reason=reason,
        )
        return {
            "token": new_token,
            "chain_id": chain["chain_id"],
            "user_id": chain["user_id"],
        }

    def _terminate(self, chain, reason, now):
        chain["active"] = False
        chain["end_reason"] = reason
        self._record_audit(
            "chain_terminated",
            at=now,
            user_id=chain["user_id"],
            chain_id=chain["chain_id"],
            reason=reason,
        )

    def _check_lifetime(self, chain, now):
        if now >= chain["absolute_deadline"]:
            self._terminate(chain, "absolute_timeout", now)
            raise SessionError("absolute_timeout")
        if now - chain["last_activity"] > self.idle_ttl:
            self._terminate(chain, "idle_timeout", now)
            raise SessionError("idle_timeout")

    def authorize(self, token, now, device_id, write=False):
        record = self._tokens.get(self._digest(token))
        if record is None:
            raise SessionError("invalid_token")
        chain = self._chains.get(record["chain_id"])
        if chain is None:
            raise SessionError("invalid_token")
        if chain["device_id"] != device_id:
            raise SessionError("device_mismatch")
        if not chain["active"]:
            raise SessionError(chain["end_reason"] or "revoked")

        self._check_lifetime(chain, now)

        if record["state"] == "head":
            chain["last_activity"] = now
            return {
                "user_id": chain["user_id"],
                "chain_id": chain["chain_id"],
                "device_id": chain["device_id"],
                "read_only": False,
                "migration": False,
                "draft": copy.deepcopy(chain["draft"]),
            }

        if record["state"] == "retired" or now >= record["grace_deadline"]:
            self._replay_rejected += 1
            self._record_audit(
                "replay_rejected",
                at=now,
                user_id=chain["user_id"],
                chain_id=chain["chain_id"],
                generation=record["generation"],
                reason="expired",
            )
            raise SessionError("expired")

        if write:
            self._replay_rejected += 1
            self._record_audit(
                "replay_rejected",
                at=now,
                user_id=chain["user_id"],
                chain_id=chain["chain_id"],
                generation=record["generation"],
                reason="read_only",
            )
            raise SessionError("read_only")

        return {
            "user_id": chain["user_id"],
            "chain_id": chain["chain_id"],
            "device_id": chain["device_id"],
            "read_only": True,
            "migration": True,
            "draft": copy.deepcopy(chain["draft"]),
        }

    def logout(self, token, now=0):
        record = self._tokens.get(self._digest(token))
        if record is None:
            raise SessionError("invalid_token")
        chain = self._chains.get(record["chain_id"])
        if chain is None:
            raise SessionError("invalid_token")
        if chain["active"]:
            self._terminate(chain, "logout", now)
        return {"chain_id": chain["chain_id"]}

    def revoke_user(self, user_id):
        for chain in self._user_chains.get(user_id, ()):
            if chain["active"]:
                self._terminate(chain, "user_revoked", None)
        return {"user_id": user_id}

    def snapshot(self):
        return {
            "idle_ttl": self.idle_ttl,
            "absolute_ttl": self.absolute_ttl,
            "grace": self.grace,
            "max_per_user": self.max_per_user,
            "replay_rejected": self._replay_rejected,
            "chains": copy.deepcopy(
                [
                    {
                        "chain_id": chain["chain_id"],
                        "user_id": chain["user_id"],
                        "device_id": chain["device_id"],
                        "created_at": chain["created_at"],
                        "absolute_deadline": chain["absolute_deadline"],
                        "last_activity": chain["last_activity"],
                        "active": chain["active"],
                        "end_reason": chain["end_reason"],
                        "draft": copy.deepcopy(chain["draft"]),
                    }
                    for chain in self._chains.values()
                ]
            ),
            "audit": copy.deepcopy(self._audit),
        }
