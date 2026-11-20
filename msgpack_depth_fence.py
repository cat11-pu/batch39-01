class MsgpackError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


class MsgpackNestedCheck:
    def __init__(self, max_depth=16, max_elements=10000, max_bytes=4096):
        pass

    def unpack(self, data):
        raise NotImplementedError
