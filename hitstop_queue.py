class HitstopQueue:
    def __init__(self, max_duration=0.5, min_scale=0.05):
        pass

    def add(self, source, strength, priority, duration, now=0.0, ignore=False):
        raise NotImplementedError

    def update(self, dt, paused=False):
        raise NotImplementedError

    def clear_scene(self):
        raise NotImplementedError
