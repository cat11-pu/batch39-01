class NineSliceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class NineSliceScale:
    def __init__(self, mode="nine", tile_center=False):
        pass

    def build(self, src, borders, dst, flip=False, rotate=0):
        raise NotImplementedError
