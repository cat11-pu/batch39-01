class WireError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


class ProtobufWireScan:
    def __init__(self, max_depth=16, max_bytes=4096):
        pass

    def parse(self, data):
        raise NotImplementedError
