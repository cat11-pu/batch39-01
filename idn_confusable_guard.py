class IdnConfusableGuard:
    def __init__(self, protected_brands, blacklist=(), max_length=253):
        pass

    def evaluate(self, value):
        raise NotImplementedError
