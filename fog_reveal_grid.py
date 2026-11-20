class FogRevealGrid:
    def __init__(self, team="ally", chunk=8):
        pass

    def set_units(self, units):
        raise NotImplementedError

    def set_walls(self, walls):
        raise NotImplementedError

    def update(self):
        raise NotImplementedError

    def state(self, x, y):
        raise NotImplementedError

    def weight(self, x, y):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError

    def restore(self, snapshot):
        raise NotImplementedError
