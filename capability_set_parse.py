class CapError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CapabilitySetParse:
    def __init__(self):
        pass

    def parse(self, text):
        raise NotImplementedError

    def exec_after(self, process, file_caps=None):
        raise NotImplementedError
