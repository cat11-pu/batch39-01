class RadiusError(ValueError):
    def __init__(self, code, offset=None):
        super().__init__(code)
        self.code = code
        self.offset = offset


class RadiusPacketGuard:
    def __init__(self, max_attributes=64, max_value=253, max_total=4096):
        pass

    def parse(self, packet, secret=b"secret"):
        raise NotImplementedError
