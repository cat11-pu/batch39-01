class GrassScatterPlan:
    def __init__(self, seed=0, spacing=1.0, max_instances=10000, **over):
        pass

    def build(self, region, density, blocked=(), slope=None, height=None):
        raise NotImplementedError
