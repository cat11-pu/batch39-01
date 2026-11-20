class PamError(ValueError):
    def __init__(self, code, line=None):
        super().__init__(code)
        self.code = code
        self.line = line


class PamStackEval:
    def __init__(self, configs, modules, max_depth=8):
        pass

    def evaluate(self, stack_type, context=None):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
