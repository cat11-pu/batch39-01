class PasswordError(ValueError):
    def __init__(self, code, rules=None):
        super().__init__(code)
        self.code = code
        self.rules = rules or []


class PasswordUnicodePolicy:
    def __init__(self, min_len=8, max_len=64, max_bytes=128, common=(), breached_prefixes=(), policy_version="v1"):
        pass

    def normalize(self, password):
        raise NotImplementedError

    def check(self, password, username=None):
        raise NotImplementedError
