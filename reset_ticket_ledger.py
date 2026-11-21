import hashlib
import hmac
import secrets
import threading


class ResetTicketError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ResetTicketVault:
    def __init__(self, ttl=600, max_token_len=128):
        self.ttl = ttl
        self.max_token_len = max_token_len
        self._tickets = {}
        self._audit = []
        self._blocked_users = set()
        self._lock = threading.RLock()

    def issue(self, user_id, device_id, now):
        with self._lock:
            if user_id in self._blocked_users:
                raise ResetTicketError("account_unavailable")

            self._revoke_pending(user_id)
            token = secrets.token_urlsafe(32)
            ticket_id = secrets.token_urlsafe(16)
            while ticket_id in self._tickets:
                ticket_id = secrets.token_urlsafe(16)

            ticket = {
                "ticket_id": ticket_id,
                "user_id": user_id,
                "device_id": device_id,
                "digest": self._digest(token),
                "status": "pending",
                "expires_at": now + self.ttl,
                "created_at": now,
            }
            self._tickets[ticket_id] = ticket
            return {
                "ticket_id": ticket_id,
                "token": token,
                "user_id": user_id,
                "device_id": device_id,
                "expires_at": ticket["expires_at"],
            }

    def redeem(self, token, user_id, device_id, now):
        with self._lock:
            if not isinstance(token, str) or not token or len(token) > self.max_token_len:
                self._record_redeem(user_id, device_id, now, False, "invalid_ticket")
                raise ResetTicketError("invalid_ticket")

            digest = self._digest(token)
            ticket = self._find_by_digest(digest)
            if ticket is None:
                self._record_redeem(user_id, device_id, now, False, "invalid_ticket")
                raise ResetTicketError("invalid_ticket")

            if ticket["status"] != "pending":
                self._record_redeem(
                    user_id, device_id, now, False, "invalid_ticket", ticket["ticket_id"]
                )
                raise ResetTicketError("invalid_ticket")

            if now >= ticket["expires_at"]:
                ticket["status"] = "expired"
                self._record_redeem(
                    user_id, device_id, now, False, "invalid_ticket", ticket["ticket_id"]
                )
                raise ResetTicketError("invalid_ticket")

            if (
                ticket["user_id"] != user_id
                or ticket["device_id"] != device_id
                or user_id in self._blocked_users
            ):
                self._record_redeem(
                    user_id, device_id, now, False, "invalid_ticket", ticket["ticket_id"]
                )
                raise ResetTicketError("invalid_ticket")

            ticket["status"] = "used"
            ticket["used_at"] = now
            self._record_redeem(
                user_id, device_id, now, True, None, ticket["ticket_id"]
            )
            return {
                "ticket_id": ticket["ticket_id"],
                "user_id": ticket["user_id"],
                "device_id": ticket["device_id"],
                "expires_at": ticket["expires_at"],
            }

    def revoke_all(self, user_id, reason="revoked"):
        with self._lock:
            return self._revoke_pending(user_id, reason)

    def snapshot(self):
        with self._lock:
            tickets = {
                ticket_id: {
                    "user_id": ticket["user_id"],
                    "device_id": ticket["device_id"],
                    "status": ticket["status"],
                    "expires_at": ticket["expires_at"],
                }
                for ticket_id, ticket in self._tickets.items()
            }
            return {
                "tickets": tickets,
                "audit": [dict(entry) for entry in self._audit],
            }

    def password_changed(self, user_id):
        return self.revoke_all(user_id, reason="password_changed")

    def logout(self, user_id):
        return self.revoke_all(user_id, reason="logout")

    def ban(self, user_id):
        with self._lock:
            self._blocked_users.add(user_id)
            return self._revoke_pending(user_id, reason="banned")

    def unban(self, user_id):
        with self._lock:
            self._blocked_users.discard(user_id)

    @staticmethod
    def _digest(token):
        return hashlib.sha256(token.encode("utf-8")).digest()

    def _find_by_digest(self, digest):
        for ticket in self._tickets.values():
            if hmac.compare_digest(digest, ticket["digest"]):
                return ticket
        return None

    def _revoke_pending(self, user_id, reason="revoked"):
        revoked = 0
        for ticket in self._tickets.values():
            if ticket["user_id"] == user_id and ticket["status"] == "pending":
                ticket["status"] = "revoked"
                ticket["revoked_reason"] = reason
                revoked += 1
        return revoked

    def _record_redeem(self, user_id, device_id, now, success, code, ticket_id=None):
        entry = {
            "ticket_id": ticket_id,
            "user_id": user_id,
            "device_id": device_id,
            "at": now,
            "success": success,
            "code": code,
        }
        self._audit.append(entry)
