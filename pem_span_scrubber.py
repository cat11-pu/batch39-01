class PemSpanScrubber:
    def __init__(self, max_block_bytes=8192, allowed_fingerprints=()):
        pass

    def scrub(self, chunks):
        raise NotImplementedError
