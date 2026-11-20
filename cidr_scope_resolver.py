class CidrError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CidrScopeResolver:
    def __init__(self, allow=(), deny=(), allow_default_route=False):
        pass

    def resolve(self, address):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
