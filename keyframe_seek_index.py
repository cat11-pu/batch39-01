class KeyframeSeekIndex:
    def __init__(self, timescale=90000, live=False):
        pass

    def build(self, entries, version=1, digest=""):
        raise NotImplementedError

    def append(self, entry):
        raise NotImplementedError

    def seek(self, target):
        raise NotImplementedError
