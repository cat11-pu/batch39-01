class TurnSpeedOrder:
    def __init__(self, min_speed=1, max_speed=1000, max_rounds=99):
        pass

    def order(self, units, round_no=1):
        raise NotImplementedError

    def end_round(self, units):
        raise NotImplementedError
