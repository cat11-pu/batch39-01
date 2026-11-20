class DraftError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ArenaBanPick:
    def __init__(self, bans_per_side=3, picks_per_side=5, fearless=False):
        pass

    def apply(self, side, action, hero, now=0):
        raise NotImplementedError

    def auto_pick(self, side, preference):
        raise NotImplementedError

    def swap(self, side, first, second):
        raise NotImplementedError

    def finalize(self):
        raise NotImplementedError

    def state(self):
        raise NotImplementedError
