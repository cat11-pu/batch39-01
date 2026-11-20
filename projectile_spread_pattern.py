class SpreadError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ProjectileSpreadPattern:
    def __init__(self, first_shot=0.0, per_shot=0.5, recovery=2.0, max_spread=5.0, ads_scale=0.5, pellets=1):
        pass

    def fire(self, shots=1, seed=0, ads=False, moving=False, jumping=False, crouching=False, mirror=False):
        raise NotImplementedError
