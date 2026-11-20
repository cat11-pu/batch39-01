class RuleError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class NetfilterRuleEval:
    def __init__(self, rules, default_policy=None, max_depth=16):
        pass

    def evaluate(self, packet):
        raise NotImplementedError
