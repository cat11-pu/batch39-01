class SudoersError(ValueError):
    def __init__(self, code, line=None):
        super().__init__(code)
        self.code = code
        self.line = line


class SudoersMatch:
    def __init__(self, text, aliases=None):
        pass

    def check(self, user, host, command, args=(), runas=None):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
