MISSING = object()


class YamlTagError(ValueError):
    def __init__(self, code, line=None, column=None, anchor=None):
        super().__init__(code)
        self.code = code
        self.line = line
        self.column = column
        self.anchor = anchor


class YamlTagFence:
    def __init__(self, max_depth=20, max_nodes=1000, max_scalar=10000, allow_merge=False):
        pass

    def convert(self, text):
        raise NotImplementedError

    def events(self, text):
        raise NotImplementedError
