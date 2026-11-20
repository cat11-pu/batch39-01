class TomlError(ValueError):
    def __init__(self, code, line=None, column=None):
        super().__init__(code)
        self.code = code
        self.line = line
        self.column = column


class TomlKeyFence:
    def __init__(self, max_depth=20, max_nodes=1000, max_scalar=10000):
        pass

    def load(self, text):
        raise NotImplementedError
