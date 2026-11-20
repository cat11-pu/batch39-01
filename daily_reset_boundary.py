class DailyResetBoundary:
    def __init__(self, reset_hour=5, tzdb=None):
        pass

    def boundaries(self, last_utc, now_utc, tz_name="UTC"):
        raise NotImplementedError

    def claim(self, user, now_utc, claimed=()):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
