class AudioResamplePlan:
    def __init__(self, in_rate, out_rate, channels=1, filter_len=32, bits=16):
        pass

    def plan(self, total_in, mix=None):
        raise NotImplementedError

    def execute(self, samples, block=1024):
        raise NotImplementedError
