class CameraShakeFalloff:
    def __init__(self, decay=1.5, max_trauma=1.0, aim_scale=0.5, seed=0):
        pass

    def add(self, source, strength, frequency=1.0, duration=0.2, axis=(1.0, 1.0, 1.0)):
        raise NotImplementedError

    def update(self, dt, paused=False, aim=False):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
