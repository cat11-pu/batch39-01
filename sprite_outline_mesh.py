class OutlineError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class SpriteOutlineMesh:
    def __init__(self, threshold=0.5, tolerance=0.75, max_vertices=4096, max_components=64):
        pass

    def build(self, alpha, width, height, region=None, expand=0):
        raise NotImplementedError
