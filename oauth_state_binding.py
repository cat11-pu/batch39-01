import hashlib
import hmac
import secrets
import threading


class OAuthError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OAuthStateBinding:
    def __init__(self, providers, ttl=600):
        self._providers = set(providers)
        self._ttl = ttl
        self._states = {}
        self._codes = {}
        self._lock = threading.Lock()

    def issue(self, provider, redirect_uri, action, session_id, tenant="t-1", now=0):
        if provider not in self._providers:
            raise OAuthError("unknown_provider")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(32)
        verifier_digest = _digest(verifier)
        record = {
            "session_id": session_id,
            "provider": provider,
            "action": action,
            "redirect_uri": redirect_uri,
            "tenant": tenant,
            "expires_at": now + self._ttl,
            "verifier_digest": verifier_digest,
            "consumed": False,
        }
        with self._lock:
            self._states[state] = record
        return {"state": state, "verifier": verifier_digest, "expires_at": record["expires_at"]}

    def callback(self, state, code, provider, redirect_uri, action, session_id, tenant="t-1", now=0):
        with self._lock:
            record = self._states.get(state)
            if record is None:
                raise OAuthError("state_unknown")
            if record["consumed"]:
                raise OAuthError("state_reused")
            if now > record["expires_at"]:
                raise OAuthError("state_expired")
            if not hmac.compare_digest(session_id, record["session_id"]):
                raise OAuthError("session_mismatch")
            if provider != record["provider"]:
                raise OAuthError("provider_mismatch")
            if tenant != record["tenant"]:
                raise OAuthError("tenant_mismatch")
            if action != record["action"]:
                raise OAuthError("action_mismatch")
            if redirect_uri != record["redirect_uri"]:
                raise OAuthError("redirect_mismatch")
            record["consumed"] = True
            self._codes[code] = {
                "provider": record["provider"],
                "redirect_uri": record["redirect_uri"],
                "tenant": record["tenant"],
                "verifier_digest": record["verifier_digest"],
                "used": False,
            }
        return {"code": code, "action": record["action"], "provider": record["provider"]}

    def exchange(self, code, verifier, provider, redirect_uri, tenant="t-1"):
        with self._lock:
            record = self._codes.get(code)
            if record is None:
                raise OAuthError("code_unknown")
            if record["used"]:
                raise OAuthError("code_reused")
            if redirect_uri != record["redirect_uri"]:
                raise OAuthError("redirect_mismatch")
            if provider != record["provider"]:
                raise OAuthError("provider_mismatch")
            if tenant != record["tenant"]:
                raise OAuthError("tenant_mismatch")
            if not verifier or not hmac.compare_digest(verifier, record["verifier_digest"]):
                raise OAuthError("verifier_invalid")
            record["used"] = True
        return {"access_token": secrets.token_urlsafe(32)}

    def snapshot(self):
        with self._lock:
            states = [_digest(state) for state in self._states]
            codes = [_digest(code) for code in self._codes]
        return {"states": states, "codes": codes, "ttl": self._ttl}
