class MorphError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class BlendShapeMorph:
    def __init__(self, base, targets, budget=8):
        pass

    def apply(self, weights, normalize=True, mode="additive", bbox=None):
        raise NotImplementedError

    def reset(self):
        raise NotImplementedError
