class RedirectHopError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class RedirectHopLedger:
    def __init__(self, allowed_hosts, allowed_ports=(443,), max_hops=8):
        pass

    def resolve(self, start_url, fetch, method="GET"):
        raise NotImplementedError
