class QuotaError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class QuotaTokenWindow:
    def __init__(self, window=60, limit=100, max_cost=50, burst=0.2, tenants=()):
        pass

    def consume(self, tenant, cost, now, idem=None):
        raise NotImplementedError

    def refund(self, tenant, idem):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

    def restore(self, snapshot):
        raise NotImplementedError
