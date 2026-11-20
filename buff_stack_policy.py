class BuffStackPolicy:
    def __init__(self, max_stacks=5, max_sources=3):
        pass

    def apply(self, target, buff_id, source, mode="refresh", duration=10, now=0, priority=0, dispellable=True):
        raise NotImplementedError

    def remove(self, target, buff_id, source=None):
        raise NotImplementedError

    def dispel(self, target, priority=0):
        raise NotImplementedError

    def tick(self, target, now):
        raise NotImplementedError

    def stats(self, target):
        raise NotImplementedError
