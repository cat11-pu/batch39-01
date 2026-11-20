class AuthorizedKeysError(ValueError):
    def __init__(self, code, line=None):
        super().__init__(code)
        self.code = code
        self.line = line


class AuthorizedKeysFence:
    def __init__(self, max_comment=256):
        pass

    def parse(self, text):
        raise NotImplementedError
