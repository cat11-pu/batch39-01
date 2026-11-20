class IsoDepthSort:
    def __init__(self):
        pass

    def add(self, obj):
        raise NotImplementedError

    def remove(self, obj_id):
        raise NotImplementedError

    def order(self):
        raise NotImplementedError

    def occlusion(self, obj_id):
        raise NotImplementedError
