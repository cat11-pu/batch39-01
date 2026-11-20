class SinkArgError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SinkArgQuoter:
    @staticmethod
    def quote(argv):
        raise NotImplementedError

    @staticmethod
    def parse(command):
        raise NotImplementedError
