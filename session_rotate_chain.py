class SessionError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SessionRotateChain:
    def __init__(self, idle_ttl=900, absolute_ttl=3600, grace=5, max_per_user=5):
        pass

    def login(self, user_id, device_id, now, draft=None):
        raise NotImplementedError

    def rotate(self, token, reason, now, draft=None):
        raise NotImplementedError

    def authorize(self, token, now, device_id, write=False):
        raise NotImplementedError

    def logout(self, token, now=0):
        raise NotImplementedError

    def revoke_user(self, user_id):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
