class OAuthError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class OAuthStateBinding:
    def __init__(self, providers, ttl=600):
        pass

    def issue(self, provider, redirect_uri, action, session_id, tenant="t-1", now=0):
        raise NotImplementedError

    def callback(self, state, code, provider, redirect_uri, action, session_id, tenant="t-1", now=0):
        raise NotImplementedError

    def exchange(self, code, verifier, provider, redirect_uri, tenant="t-1"):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
