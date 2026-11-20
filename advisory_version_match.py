class VersionError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class AdvisoryVersionMatch:
    def __init__(self, rename=None):
        pass

    def match(self, package, version, advisories):
        raise NotImplementedError
