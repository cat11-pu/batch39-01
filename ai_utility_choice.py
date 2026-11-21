import math
import random


class AiUtilityChoice:
    """Deterministic utility-based behavior selector.

    Each behavior declares: id, weight, scale (scoring curve divisor),
    cooldown, precondition, priority and interrupt priority. Raw scores are
    normalized to [0, 1] before weighting; behaviors on cooldown or with a
    failing precondition never enter the candidate list; the current behavior
    is kept while the challenger stays inside the hysteresis band; ties break
    by priority then behavior id; when nothing is usable the selector returns
    "idle" instead of raising.
    """

    def __init__(self, behaviors, seed=0, hysteresis=0.05):
        self.behaviors = list(behaviors or [])
        self.seed = seed
        self.hysteresis = float(hysteresis)
        self._rng = random.Random(seed)
        self._by_id = {}
        for behavior in self.behaviors:
            weight = float(behavior.get("weight", 1.0))
            if weight < 0.0:
                raise ValueError(
                    "negative weight for behavior %r" % (behavior.get("id"),)
                )
            self._by_id[behavior.get("id")] = behavior

    def choose(self, context):
        context = dict(context or {})
        current = context.get("current")
        event = context.get("event")
        cooldowns = context.get("cooldown") or {}
        overrides = context.get("scores") or {}

        candidates = []
        scores = {}
        for behavior in self.behaviors:
            bid = behavior.get("id")
            if cooldowns.get(bid, 0) > 0:
                continue
            precondition = behavior.get("precondition")
            if precondition is not None and not precondition(context):
                continue
            candidates.append(bid)
            scores[bid] = self._score(behavior, bid, context, overrides)

        if not candidates:
            return self._result("idle", [], {}, "no_candidate", False)

        best = min(
            candidates,
            key=lambda bid: (-scores[bid], -self._priority(bid), str(bid)),
        )

        if scores[best] <= 0.0:
            return self._result("idle", candidates, scores, "all_zero", False)

        choice = best
        reason = "best"
        interrupted = False

        if (
            current in candidates
            and current != best
            and scores[current] > 0.0
            and scores[best] - scores[current] < self.hysteresis
        ):
            choice = current
            reason = "hysteresis"

        if current is not None and choice != current and event:
            if self._interrupt(choice) > self._interrupt(current):
                interrupted = True
                reason = "interrupted:%s" % (event,)

        return self._result(choice, candidates, scores, reason, interrupted)

    def _score(self, behavior, bid, context, overrides):
        if bid in overrides:
            return self._clamp(overrides[bid])
        factor = 1.0
        for key in ("hp", "range"):
            value = context.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                factor *= float(value)
        raw = float(behavior.get("scale", 1.0)) * factor
        normalized = self._clamp(raw)
        weighted = normalized * float(behavior.get("weight", 1.0))
        return self._clamp(weighted)

    def _priority(self, bid):
        behavior = self._by_id.get(bid) or {}
        return float(behavior.get("priority", 0))

    def _interrupt(self, bid):
        behavior = self._by_id.get(bid) or {}
        return float(behavior.get("interrupt", 0))

    @staticmethod
    def _clamp(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(number):
            return 0.0
        if math.isinf(number):
            return 1.0 if number > 0 else 0.0
        return min(max(number, 0.0), 1.0)

    @staticmethod
    def _result(choice, candidates, scores, reason, interrupted):
        return {
            "choice": choice,
            "candidates": list(candidates),
            "scores": dict(scores),
            "reason": reason,
            "interrupted": interrupted,
        }
