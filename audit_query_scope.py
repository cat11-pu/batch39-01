class AuditError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class AuditQueryScope:
    def __init__(self, secret, tenant, role, role_rank=None, max_days=31, page_cap=100, export_cap=1000):
        pass

    def query(self, request, records):
        raise NotImplementedError

    def export(self, request, records):
        raise NotImplementedError
