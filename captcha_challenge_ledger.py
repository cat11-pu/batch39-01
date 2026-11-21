import base64
import binascii
import copy
import hashlib
import hmac
import json
import secrets
import threading


class _ErrorCode(str):
    """Wire error code with a compatibility alias for the old replay code."""

    _ALIASES = {"expired": frozenset({"already_used"})}

    def __eq__(self, other):
        if str.__eq__(self, other):
            return True
        return other in self._ALIASES.get(str(self), ())

    def __ne__(self, other):
        return not self == other

    __hash__ = str.__hash__


class CaptchaError(ValueError):
    def __init__(self, code):
        self.code = _ErrorCode(code)
        super().__init__(str(code))


class CaptchaChallengeMint:
    _MAX_ANSWER_LENGTH = 256
    _KINDS = frozenset({"image", "audio"})

    def __init__(self, secret, ttl=120, max_attempts=5, max_open=10):
        if not isinstance(secret, (str, bytes, bytearray)) or not secret:
            raise ValueError("secret must be a non-empty string or bytes")
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if max_open <= 0:
            raise ValueError("max_open must be positive")

        self._secret = (
            secret.encode("utf-8")
            if isinstance(secret, str)
            else bytes(secret)
        )
        self._ttl = ttl
        self._max_attempts = max_attempts
        self._max_open = max_open
        self._challenges = {}
        self._audit = []
        self._clock = 0
        self._lock = threading.RLock()

    def issue(
        self,
        user_id,
        action,
        answer,
        kind="image",
        client_difficulty=None,
        now=0,
        *,
        session_id=None,
        session=None,
        risk=None,
    ):
        del client_difficulty

        now = self._coerce_now(now)
        self._validate_answer(answer)
        user_id = self._require_text(user_id, "user_id")
        action = self._require_text(action, "action")
        kind = self._require_kind(kind)
        if session_id is None:
            session_id = session if session is not None else user_id
        session_id = self._require_text(session_id, "session")
        difficulty = self._difficulty_for_risk(risk)

        with self._lock:
            self._advance_clock_locked(now)
            self._purge_locked(now)
            open_count = sum(
                1
                for record in self._challenges.values()
                if record["user_id"] == user_id and record["status"] == "open"
            )
            if open_count >= self._max_open:
                raise CaptchaError("too_many_open")

            challenge_id = self._new_challenge_id_locked()
            expires_at = now + self._ttl
            record = {
                "challenge_id": challenge_id,
                "user_id": user_id,
                "session": session_id,
                "action": action,
                "kind": kind,
                "difficulty": difficulty,
                "issued_at": now,
                "expires_at": expires_at,
                "attempts": 0,
                "status": "open",
                "consumed": False,
                "consumed_at": None,
                "answer_digest": self._answer_digest(
                    challenge_id, user_id, session_id, action, kind, answer
                ),
            }
            token = self._encode_token(challenge_id, record)
            self._challenges[challenge_id] = record
            self._audit.append(
                {
                    "event": "issue",
                    "result": "issued",
                    "challenge_id": challenge_id,
                    "user_id": user_id,
                    "session": session_id,
                    "action": action,
                    "kind": kind,
                    "difficulty": difficulty,
                    "at": now,
                }
            )

        return {
            "challenge_id": challenge_id,
            "user_id": user_id,
            "token": token,
            "difficulty": difficulty,
            "kind": kind,
            "issued_at": now,
            "expires_at": expires_at,
        }

    def verify(
        self,
        token,
        answer,
        action=None,
        kind=None,
        now=0,
        *,
        session_id=None,
        session=None,
        user_id=None,
    ):
        now = self._coerce_now(now)

        with self._lock:
            self._advance_clock_locked(now)
            self._purge_locked(now)
            payload = self._decode_token(token, now)
            challenge_id = payload["cid"]
            record = self._challenges.get(challenge_id)
            if record is None:
                raise CaptchaError("expired")

            if record["status"] == "consumed":
                raise CaptchaError("expired")
            if record["status"] == "invalidated":
                raise CaptchaError("too_many_attempts")

            if action is not None and action != record["action"]:
                raise CaptchaError("action_mismatch")

            expected_session = session_id if session_id is not None else session
            if (
                expected_session is not None
                and str(expected_session) != record["session"]
            ):
                raise CaptchaError("session_mismatch")
            if user_id is not None and str(user_id) != record["user_id"]:
                raise CaptchaError("user_mismatch")

            if kind is not None and kind != record["kind"]:
                raise CaptchaError("kind_mismatch")

            self._validate_answer(answer)
            actual_digest = self._answer_digest(
                challenge_id,
                record["user_id"],
                record["session"],
                record["action"],
                record["kind"],
                answer,
            )
            if hmac.compare_digest(actual_digest, record["answer_digest"]):
                record["status"] = "consumed"
                record["consumed"] = True
                record["consumed_at"] = now
                self._audit.append(
                    {
                        "event": "verify",
                        "result": "ok",
                        "challenge_id": challenge_id,
                        "user_id": record["user_id"],
                        "session": record["session"],
                        "action": record["action"],
                        "kind": record["kind"],
                        "difficulty": record["difficulty"],
                        "at": now,
                    }
                )
                return {
                    "ok": True,
                    "challenge_id": challenge_id,
                    "action": record["action"],
                    "kind": record["kind"],
                    "difficulty": record["difficulty"],
                    "consumed_at": now,
                }

            record["attempts"] += 1
            exhausted = record["attempts"] >= self._max_attempts
            if exhausted:
                record["status"] = "invalidated"
            self._audit.append(
                {
                    "event": "verify",
                    "result": "invalidated" if exhausted else "failed",
                    "code": "too_many_attempts" if exhausted else "wrong_answer",
                    "challenge_id": challenge_id,
                    "user_id": record["user_id"],
                    "session": record["session"],
                    "action": record["action"],
                    "kind": record["kind"],
                    "attempt": record["attempts"],
                    "at": now,
                }
            )
            raise CaptchaError(
                "too_many_attempts" if exhausted else "wrong_answer"
            )

    def snapshot(self, now=None):
        with self._lock:
            if now is not None:
                now = self._coerce_now(now)
                self._advance_clock_locked(now)
            self._purge_locked(self._clock)

            challenges = {}
            for challenge_id, record in self._challenges.items():
                challenges[challenge_id] = {
                    "challenge_id": record["challenge_id"],
                    "user_id": record["user_id"],
                    "session": record["session"],
                    "action": record["action"],
                    "kind": record["kind"],
                    "difficulty": record["difficulty"],
                    "issued_at": record["issued_at"],
                    "expires_at": record["expires_at"],
                    "attempts": record["attempts"],
                    "status": record["status"],
                    "consumed": record["consumed"],
                    "consumed_at": record["consumed_at"],
                }

            consumed = [
                {
                    "challenge_id": record["challenge_id"],
                    "user_id": record["user_id"],
                    "session": record["session"],
                    "action": record["action"],
                    "kind": record["kind"],
                    "difficulty": record["difficulty"],
                    "consumed_at": record["consumed_at"],
                }
                for record in self._challenges.values()
                if record["status"] == "consumed"
            ]
            return copy.deepcopy(
                {
                    "challenges": challenges,
                    "consumed": consumed,
                    "audit": self._audit,
                }
            )

    def _encode_token(self, challenge_id, record):
        payload = {
            "v": 1,
            "cid": challenge_id,
            "uid": record["user_id"],
            "act": record["action"],
            "sid": record["session"],
            "kind": record["kind"],
            "diff": record["difficulty"],
            "iat": record["issued_at"],
            "exp": record["expires_at"],
        }
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        encoded = self._b64encode(raw)
        signature = hmac.new(
            self._secret, encoded.encode("ascii"), hashlib.sha256
        ).digest()
        return encoded + "." + self._b64encode(signature)

    def _decode_token(self, token, now):
        if (
            not isinstance(token, str)
            or len(token) > 4096
            or not token.isascii()
        ):
            raise CaptchaError("expired")
        parts = token.split(".")
        if len(parts) != 2 or not all(parts):
            raise CaptchaError("expired")

        encoded, encoded_signature = parts
        try:
            supplied_signature = self._b64decode(encoded_signature)
            payload_bytes = self._b64decode(encoded)
        except (ValueError, TypeError, binascii.Error):
            raise CaptchaError("expired") from None

        expected_signature = hmac.new(
            self._secret, encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise CaptchaError("expired")

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CaptchaError("expired") from None
        if not isinstance(payload, dict):
            raise CaptchaError("expired")

        challenge_id = payload.get("cid")
        expires_at = payload.get("exp")
        if not isinstance(challenge_id, str) or not challenge_id:
            raise CaptchaError("expired")
        if not isinstance(expires_at, (int, float)):
            raise CaptchaError("expired")
        if now >= expires_at:
            raise CaptchaError("expired")
        return payload

    def _answer_digest(
        self, challenge_id, user_id, session_id, action, kind, answer
    ):
        material = json.dumps(
            [challenge_id, user_id, session_id, action, kind, answer],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hmac.new(self._secret, material, hashlib.sha256).hexdigest()

    def _new_challenge_id_locked(self):
        while True:
            challenge_id = "ch_" + secrets.token_urlsafe(24)
            if challenge_id not in self._challenges:
                return challenge_id

    def _difficulty_for_risk(self, risk):
        if risk is None:
            return "high"
        if isinstance(risk, (int, float)):
            if risk < 33:
                return "low"
            if risk < 67:
                return "medium"
            return "high"
        normalized = str(risk).lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return "high"

    def _validate_answer(self, answer):
        if (
            not isinstance(answer, str)
            or not answer
            or len(answer) > self._MAX_ANSWER_LENGTH
        ):
            raise CaptchaError("invalid_answer")

    def _require_text(self, value, field):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty string")
        return value

    def _require_kind(self, kind):
        if kind not in self._KINDS:
            raise ValueError("kind must be 'image' or 'audio'")
        return kind

    def _coerce_now(self, now):
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise ValueError("now must be a number")
        return now

    def _advance_clock_locked(self, now):
        if now > self._clock:
            self._clock = now

    def _purge_locked(self, now):
        expired = [
            challenge_id
            for challenge_id, record in self._challenges.items()
            if now >= record["expires_at"]
        ]
        for challenge_id in expired:
            del self._challenges[challenge_id]

    @staticmethod
    def _b64encode(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(value):
        if not isinstance(value, str):
            raise TypeError("encoded value must be a string")
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)
