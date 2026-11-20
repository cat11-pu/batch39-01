class DuckingEnvelope:
    def __init__(self, attack=0.1, release=0.3, hold=0.0):
        pass

    def add_source(self, source_id, bus, priority, depth, start=0.0, hold=None, release=None):
        raise NotImplementedError

    def remove_source(self, source_id):
        raise NotImplementedError

    def set_bus_gain(self, bus, gain):
        raise NotImplementedError

    def update(self, dt, paused=False):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
