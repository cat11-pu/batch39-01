class PortalError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class PortalLinkTraverse:
    def __init__(self, links, agent_radius=0.5):
        pass

    def load(self):
        raise NotImplementedError

    def path_cost(self, link_id):
        raise NotImplementedError

    def traverse(self, unit, link_id, now=0):
        raise NotImplementedError

    def tick(self, unit, now):
        raise NotImplementedError

    def close(self, link_id):
        raise NotImplementedError
