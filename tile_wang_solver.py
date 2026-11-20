class WangError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TileWangSolver:
    def __init__(self, tiles, seed=0, forbid_same=False):
        pass

    def solve(self, width, height, holes=(), border=None):
        raise NotImplementedError
