import json
import threading

import pytest

import captcha_challenge_ledger as cc


def mint(**over):
    kwargs = {"secret": "server-secret", "ttl": 120, "max_attempts": 5, "max_open": 10}
    kwargs.update(over)
    return cc.CaptchaChallengeMint(**kwargs)


def issue(m, user="u-1", action="register", answer="42", kind="image", now=0):
    return m.issue(user, action, answer, kind=kind, now=now)


def test_challenge_can_only_be_consumed_once():
    m = mint()
    token = issue(m)["token"]
    assert m.verify(token, "42", action="register", kind="image", now=1)["ok"] is True
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "42", action="register", kind="image", now=2)
    assert exc.value.code == "already_used"


def test_token_is_bound_to_action():
    m = mint()
    token = issue(m, action="register")["token"]
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "42", action="login", kind="image", now=1)
    assert exc.value.code == "action_mismatch"


def test_expired_token_is_rejected():
    m = mint(ttl=10)
    token = issue(m, now=0)["token"]
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "42", action="register", kind="image", now=11)
    assert exc.value.code == "expired"


def test_client_difficulty_is_ignored_by_server():
    m = mint()
    result = m.issue("u-1", "register", "42", client_difficulty="low", now=0)
    assert result["difficulty"] == "high"
    assert m.snapshot()["challenges"][result["challenge_id"]]["difficulty"] == "high"


def test_wrong_answers_exhaust_the_challenge():
    m = mint(max_attempts=2)
    token = issue(m)["token"]
    for _ in range(2):
        with pytest.raises(cc.CaptchaError):
            m.verify(token, "wrong", action="register", kind="image", now=1)
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "42", action="register", kind="image", now=2)
    assert exc.value.code == "too_many_attempts"


def test_concurrent_verify_allows_exactly_one_success():
    m = mint()
    token = issue(m)["token"]
    results = []

    def worker():
        try:
            m.verify(token, "42", action="register", kind="image", now=1)
            results.append("ok")
        except Exception:
            results.append("fail")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1


def test_challenge_ids_are_random_not_sequential():
    m = mint()
    a = issue(m)["challenge_id"]
    b = issue(m)["challenge_id"]
    assert a != b
    assert a.isdigit() is False or b != str(int(a) + 1)


def test_audio_and_image_answers_are_independent():
    m = mint()
    image = m.issue("u-1", "register", "cat", kind="image", now=0)
    audio = m.issue("u-1", "register", "dog", kind="audio", now=0)
    assert m.verify(image["token"], "cat", action="register", kind="image", now=1)["ok"] is True
    with pytest.raises(cc.CaptchaError):
        m.verify(audio["token"], "cat", action="register", kind="audio", now=1)


def test_successful_verification_is_audited():
    m = mint()
    token = issue(m)["token"]
    m.verify(token, "42", action="register", kind="image", now=1)
    assert any(entry["result"] == "ok" for entry in m.snapshot()["audit"])


def test_expired_forged_and_used_share_one_error_code():
    m = mint(ttl=5)
    used = issue(m, now=0)["token"]
    m.verify(used, "42", action="register", kind="image", now=1)
    expired = issue(m, now=0)["token"]
    codes = []
    for token, now in ((used, 2), (expired, 9), ("forged-token", 2)):
        with pytest.raises(cc.CaptchaError) as exc:
            m.verify(token, "42", action="register", kind="image", now=now)
        codes.append(exc.value.code)
    assert len(set(codes)) == 1


def test_snapshot_does_not_expose_the_secret():
    m = mint(secret="super-secret-value")
    issue(m)
    assert "super-secret-value" not in json.dumps(m.snapshot())


def test_empty_answer_is_rejected():
    m = mint()
    token = issue(m)["token"]
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "", action="register", kind="image", now=1)
    assert exc.value.code == "invalid_answer"


def test_overlong_answer_is_rejected():
    m = mint()
    token = issue(m)["token"]
    with pytest.raises(cc.CaptchaError) as exc:
        m.verify(token, "x" * 1000, action="register", kind="image", now=1)
    assert exc.value.code == "invalid_answer"


def test_open_challenge_limit_is_enforced():
    m = mint(max_open=2)
    issue(m, answer="a")
    issue(m, answer="b")
    with pytest.raises(cc.CaptchaError) as exc:
        issue(m, answer="c")
    assert exc.value.code == "too_many_open"


def test_snapshot_redacts_tokens_and_answers():
    m = mint()
    token = issue(m, answer="secret-answer")["token"]
    blob = json.dumps(m.snapshot())
    assert token not in blob
    assert "secret-answer" not in blob
