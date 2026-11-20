class PathReplanWindow:
    def __init__(self, budget=4, radius=0.5, goal_threshold=1.0):
        pass

    def request(self, unit_id, start, goal, grid, priority=0, now=0):
        raise NotImplementedError

    def tick(self):
        raise NotImplementedError
