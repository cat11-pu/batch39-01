class WaveformPeakIndex:
    def __init__(self, bucket=1000, silence=1e-4, max_levels=8, memory_cap=1000000):
        pass

    def build(self, samples, channels=1, bits=16):
        raise NotImplementedError

    def update(self, samples, start=0):
        raise NotImplementedError

    def levels(self):
        raise NotImplementedError
