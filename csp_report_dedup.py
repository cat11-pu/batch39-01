class CspError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class CspReportDedup:
    def __init__(self, window=120, per_site_limit=100, detail_days=30):
        pass

    def ingest(self, reports, now=0):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
