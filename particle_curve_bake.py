class ParticleCurveBake:
    def __init__(self, quality="high", value_range=(0.0, 1.0)):
        pass

    def bake(self, keys, duration, loop=False, fps=60):
        raise NotImplementedError

    def sample(self, t):
        raise NotImplementedError
