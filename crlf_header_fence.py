class HeaderError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CrlfHeaderFence:
    def __init__(self, allowed_hosts=(), max_headers=50, max_value=4096, max_total=16384):
        pass

    def build(self, headers, filename=None, location=None):
        raise NotImplementedError

    def render(self, headers):
        raise NotImplementedError
