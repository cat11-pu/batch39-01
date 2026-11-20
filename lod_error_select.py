class LodErrorSelect:
    def __init__(self, max_px=2.0, hysteresis=0.1):
        pass

    def select(self, model, camera):
        raise NotImplementedError

    def select_many(self, models, camera):
        raise NotImplementedError
