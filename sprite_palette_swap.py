class PaletteError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SpritePaletteSwap:
    def __init__(self, atlas_version=1):
        pass

    def swap(self, indices, palette, mapping, weights=None, region=None):
        raise NotImplementedError

    def restore(self, image):
        raise NotImplementedError
