class TurnSpeedOrder:
    SIDE_RANK = {"ally": 0, "enemy": 1}
    SKIP_STATUSES = {"stunned", "dead", "left"}

    def __init__(self, min_speed=1, max_speed=1000, max_rounds=99):
        self.min_speed = min_speed
        self.max_speed = max_speed
        self.max_rounds = max_rounds

    def _effective_speed(self, unit, reasons):
        base = unit.get("speed", 0)
        if base == 0:
            reasons.append("zero_speed")
            reasons.append("clamped_to_min_speed:%s" % self.min_speed)
            return self.min_speed, True
        if base < 0:
            reasons.append("negative_speed")
            reasons.append("clamped_to_min_speed:%s" % self.min_speed)
            return self.min_speed, True
        haste = unit.get("haste", 1.0) or 1.0
        slow = unit.get("slow", 1.0) or 1.0
        once = unit.get("once_modifier", 0) or 0
        raw = base * haste / slow + once
        effective = max(self.min_speed, min(self.max_speed, raw))
        reasons.append(
            "effective_speed:%s=base:%s*haste:%s/slow:%s+once:%s"
            % (effective, base, haste, slow, once)
        )
        if effective != raw:
            reasons.append("clamped_to_limits:[%s,%s]" % (self.min_speed, self.max_speed))
        return effective, False

    def _sort_key(self, entry):
        unit, effective, flagged = entry
        return (
            -unit.get("priority", 0),
            -effective,
            1 if flagged else 0,
            self.SIDE_RANK.get(unit.get("side"), 99),
            unit.get("slot", 0),
            str(unit.get("id")),
        )

    def order(self, units, round_no=1):
        if not 1 <= round_no <= self.max_rounds:
            raise ValueError(
                "round_no %s out of range [1, %s]" % (round_no, self.max_rounds)
            )
        reasons = {}
        actionable = []
        skipped = []
        turn_count = 0
        for unit in units:
            uid = unit.get("id")
            unit_reasons = reasons.setdefault(uid, [])
            join_round = unit.get("reinforcement_round", 0) or 0
            if join_round and round_no < join_round:
                unit_reasons.append("reinforcement_joins_round:%s" % join_round)
                continue
            delay_round = unit.get("delay_round", 0) or 0
            if delay_round and round_no < delay_round:
                unit_reasons.append("delayed_until_round:%s" % delay_round)
                continue
            turn_count += 1
            status = unit.get("status", "alive")
            if status in self.SKIP_STATUSES:
                unit_reasons.append("skipped_%s" % status)
                skipped.append((unit, 0, False))
                continue
            effective, flagged = self._effective_speed(unit, unit_reasons)
            unit_reasons.append("priority_group:%s" % unit.get("priority", 0))
            actionable.append((unit, effective, flagged))

        actionable.sort(key=self._sort_key)
        skipped.sort(key=self._sort_key)

        sequence = [entry[0].get("id") for entry in actionable]
        for unit, _, _ in actionable:
            if unit.get("extra"):
                sequence.append(unit.get("id"))
                reasons[unit.get("id")].append("extra_action_appended")

        return {
            "round": round_no,
            "order": sequence,
            "skipped": [entry[0].get("id") for entry in skipped],
            "reasons": reasons,
            "turn_count": turn_count,
            "round_boundary": {
                "round": round_no,
                "turn_count": turn_count,
                "action_count": len(sequence),
            },
        }

    def end_round(self, units):
        cleaned = []
        for unit in units:
            new_unit = dict(unit)
            new_unit["once_modifier"] = 0
            cleaned.append(new_unit)
        return cleaned
