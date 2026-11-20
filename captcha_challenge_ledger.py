class CaptchaError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CaptchaChallengeMint:
    def __init__(self, secret, ttl=120, max_attempts=5, max_open=10):
        pass

    def issue(self, user_id, action, answer, kind="image", client_difficulty=None, now=0):
        raise NotImplementedError

    def verify(self, token, answer, action=None, kind=None, now=0):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
