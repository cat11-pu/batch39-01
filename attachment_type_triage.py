class AttachmentTypeTriage:
    def __init__(self, policy="reject"):
        pass

    def inspect(self, data, filename, declared_type=None):
        raise NotImplementedError
