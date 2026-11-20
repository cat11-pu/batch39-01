class FlipbookTimeline:
    def __init__(self, durations, mode="once", events=None):
        pass

    def advance(self, dt):
        raise NotImplementedError

    def seek(self, t):
        raise NotImplementedError

    def pause(self):
        raise NotImplementedError

    def resume(self):
        raise NotImplementedError
