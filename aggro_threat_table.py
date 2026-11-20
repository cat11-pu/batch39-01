class AggroThreatTable:
    def __init__(self, heal_factor=0.5, switch_ratio=1.1, decay=0.05):
        pass

    def add(self, unit, owner=None):
        raise NotImplementedError

    def remove(self, unit):
        raise NotImplementedError

    def damage(self, source, hp_lost, distance=0.0, visible=True):
        raise NotImplementedError

    def heal(self, source, effective, overheal=0.0):
        raise NotImplementedError

    def taunt(self, source, duration, now, immune=False):
        raise NotImplementedError

    def update(self, now, in_combat=True):
        raise NotImplementedError

    def target(self):
        raise NotImplementedError

    def reset(self):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
