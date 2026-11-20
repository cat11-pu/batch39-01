class BpfError(ValueError):
    def __init__(self, code, index=None):
        super().__init__(code)
        self.code = code
        self.index = index


class BpfVerifierLite:
    def __init__(self, max_insns=4096, max_depth=32, max_stack=512):
        pass

    def verify(self, program):
        raise NotImplementedError
