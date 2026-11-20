class DamageMitigationChain:
    def __init__(self, order=None, min_damage=0, resist_cap=0.8):
        pass

    def resolve(self, hit):
        raise NotImplementedError

    def resolve_all(self, hits):
        raise NotImplementedError
