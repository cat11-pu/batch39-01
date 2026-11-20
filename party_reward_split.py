class LootError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PartyRewardSplit:
    def __init__(self, mode="roll"):
        pass

    def submit(self, item_id, member, choice, roll=None, owned=False):
        raise NotImplementedError

    def resolve(self, item_id, members, master=None, proxy=None, offline=(), timeout=False):
        raise NotImplementedError

    def split_gold(self, total, members, tax=0):
        raise NotImplementedError

    def audit(self):
        raise NotImplementedError
