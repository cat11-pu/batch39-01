class DraftError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ArenaBanPick:
    SIDES = ("blue", "red")
    ACTIONS = ("ban", "pick")
    PHASE_BAN = "ban"
    PHASE_PICK = "pick"
    PHASE_SWAP = "swap"
    PHASE_DONE = "done"
    TIME_BANK_LIMIT = 60
    ACTION_COST = 5

    def __init__(self, bans_per_side=3, picks_per_side=5, fearless=False,
                 game_number=1, time_bank=TIME_BANK_LIMIT, used_heroes=None):
        self.bans_per_side = bans_per_side
        self.picks_per_side = picks_per_side
        self.fearless = fearless
        self.game_number = game_number
        self.time_bank = time_bank
        self.first_side = (
            self.SIDES[0] if (game_number - 1) % 2 == 0 else self.SIDES[1]
        )
        self.second_side = self._opponent(self.first_side)
        self.phase = self.PHASE_PICK if bans_per_side == 0 else self.PHASE_BAN
        self.bans = {"blue": [], "red": []}
        self.picks = {"blue": [], "red": []}
        self.used_heroes = set(used_heroes or ())
        self.replay = []
        self._sequence = 0

    @classmethod
    def _opponent(cls, side):
        return cls.SIDES[1] if side == cls.SIDES[0] else cls.SIDES[0]

    def _expected_side(self):
        if self.phase == self.PHASE_BAN:
            done = len(self.bans["blue"]) + len(self.bans["red"])
            order = (self.first_side, self.second_side)
            return order[done % 2]
        if self.phase == self.PHASE_PICK:
            done = len(self.picks["blue"]) + len(self.picks["red"])
            order = (self.first_side, self.second_side)
            return order[done % 2]
        return None

    def _taken_heroes(self):
        taken = set(self.used_heroes)
        for side in self.SIDES:
            taken.update(self.bans[side])
            taken.update(self.picks[side])
        return taken

    def _validate_hero_available(self, side, action, hero):
        if not isinstance(hero, str) or not hero:
            raise DraftError("invalid_hero")
        if hero in self.bans[side] or hero in self.picks[side]:
            raise DraftError("hero_already_used_by_side")
        for other in self.SIDES:
            if hero in self.bans[other]:
                raise DraftError("hero_banned")
            if hero in self.picks[other]:
                raise DraftError("hero_picked")
        if action == "pick" and self.fearless and hero in self.used_heroes:
            raise DraftError("hero_used_in_previous_game")

    def _record(self, side, action, hero, result, now=0):
        self._sequence += 1
        self.replay.append({
            "seq": self._sequence,
            "side": side,
            "action": action,
            "hero": hero,
            "result": result,
            "time": now,
        })

    def _auto_fill_bans(self):
        while any(
            len(self.bans[side]) < self.bans_per_side for side in self.SIDES
        ):
            side = next(
                side for side in self.SIDES
                if len(self.bans[side]) < self.bans_per_side
            )
            placeholder = "#auto_ban_%d" % (
                len(self.bans["blue"]) + len(self.bans["red"])
            )
            self.bans[side].append(placeholder)
            self._record(side, "ban", placeholder, "auto")
        self.phase = self.PHASE_PICK

    def apply(self, side, action, hero, now=0):
        if side not in self.SIDES:
            raise DraftError("invalid_side")
        if action not in self.ACTIONS:
            raise DraftError("invalid_action")
        if self.phase not in (self.PHASE_BAN, self.PHASE_PICK):
            raise DraftError("draft_not_active")
        if self.time_bank < self.ACTION_COST:
            raise DraftError("time_bank_exhausted")

        auto_bans = 0
        if action == "ban":
            if self.phase != self.PHASE_BAN:
                raise DraftError("ban_phase_closed")
            if side != self._expected_side():
                raise DraftError("out_of_turn")
            if len(self.bans[side]) >= self.bans_per_side:
                raise DraftError("ban_quota_exceeded")
        else:
            if self.phase == self.PHASE_BAN:
                auto_bans = (
                    self.bans_per_side - len(self.bans[side])
                    + self.bans_per_side
                    - len(self.bans[self._opponent(side)])
                )
                expected_after_skip = self.first_side
            else:
                expected_after_skip = self._expected_side()
            if side != expected_after_skip:
                raise DraftError("out_of_turn")
            if len(self.picks[side]) >= self.picks_per_side:
                raise DraftError("pick_quota_exceeded")

        self._validate_hero_available(side, action, hero)

        if action == "ban":
            self.bans[side].append(hero)
            if len(self.bans["blue"]) == self.bans_per_side and \
                    len(self.bans["red"]) == self.bans_per_side:
                self.phase = self.PHASE_PICK
        else:
            for _ in range(auto_bans):
                fill_side = next(
                    side for side in self.SIDES
                    if len(self.bans[side]) < self.bans_per_side
                )
                placeholder = "#auto_ban_%d" % (
                    len(self.bans["blue"]) + len(self.bans["red"])
                )
                self.bans[fill_side].append(placeholder)
                self._record(fill_side, "ban", placeholder, "auto", now)
            if auto_bans:
                self.phase = self.PHASE_PICK
            self.picks[side].append(hero)
            if self.fearless:
                self.used_heroes.add(hero)
            if len(self.picks["blue"]) == self.picks_per_side and \
                    len(self.picks["red"]) == self.picks_per_side:
                self.phase = self.PHASE_SWAP
        self.time_bank -= self.ACTION_COST
        self._record(side, action, hero, "ok", now)
        return hero

    def auto_pick(self, side, preference):
        if side not in self.SIDES:
            raise DraftError("invalid_side")
        if self.phase not in (self.PHASE_BAN, self.PHASE_PICK):
            raise DraftError("draft_not_active")
        if not preference:
            raise DraftError("empty_preference")
        if self.phase == self.PHASE_BAN and \
                len(self.bans[side]) >= self.bans_per_side:
            raise DraftError("ban_quota_exceeded")
        if self.phase == self.PHASE_PICK and \
                len(self.picks[side]) >= self.picks_per_side:
            raise DraftError("pick_quota_exceeded")
        taken = self._taken_heroes()
        chosen = None
        for hero in preference:
            if hero not in taken:
                if self.phase == self.PHASE_PICK and self.fearless and \
                        hero in self.used_heroes:
                    continue
                chosen = hero
                break
        if chosen is None:
            raise DraftError("no_available_hero")

        action = "ban" if self.phase == self.PHASE_BAN else "pick"
        if action == "ban":
            self.bans[side].append(chosen)
            if len(self.bans["blue"]) == self.bans_per_side and \
                    len(self.bans["red"]) == self.bans_per_side:
                self.phase = self.PHASE_PICK
        else:
            self.picks[side].append(chosen)
            if self.fearless:
                self.used_heroes.add(chosen)
            if len(self.picks["blue"]) == self.picks_per_side and \
                    len(self.picks["red"]) == self.picks_per_side:
                self.phase = self.PHASE_SWAP
        self._record(side, action, chosen, "auto")
        return chosen

    def skip_phase(self):
        if self.phase != self.PHASE_BAN:
            raise DraftError("phase_not_skippable")
        self._auto_fill_bans()

    def swap(self, side, first, second):
        if side not in self.SIDES:
            raise DraftError("invalid_side")
        if self.phase != self.PHASE_SWAP:
            raise DraftError("swap_not_allowed_in_phase")
        lineup = self.picks[side]
        if first not in lineup or second not in lineup:
            raise DraftError("hero_not_in_lineup")
        left = lineup.index(first)
        right = lineup.index(second)
        lineup[left], lineup[right] = lineup[right], lineup[left]
        self._record(side, "swap", "%s<->%s" % (first, second), "ok")

    def finalize(self):
        for side in self.SIDES:
            if len(self.picks[side]) != self.picks_per_side:
                raise DraftError("invalid_lineup_size")
            if len(set(self.picks[side])) != len(self.picks[side]):
                raise DraftError("duplicate_hero_in_lineup")
        all_picks = self.picks["blue"] + self.picks["red"]
        if len(set(all_picks)) != len(all_picks):
            raise DraftError("hero_not_unique")
        positions = {"blue": set(), "red": set()}
        for side in self.SIDES:
            for index, hero in enumerate(self.picks[side]):
                position = getattr(hero, "position", index)
                if position in positions[side]:
                    raise DraftError("duplicate_position")
                positions[side].add(position)
        self.phase = self.PHASE_DONE
        self._record("system", "finalize", "-", "ok")
        return {
            "blue": list(self.picks["blue"]),
            "red": list(self.picks["red"]),
        }

    def state(self):
        return {
            "phase": self.phase,
            "turn": self._expected_side(),
            "first_side": self.first_side,
            "game_number": self.game_number,
            "bans": {side: list(self.bans[side]) for side in self.SIDES},
            "picks": {side: list(self.picks[side]) for side in self.SIDES},
            "used_heroes": set(self.used_heroes),
            "time_bank": self.time_bank,
            "auto_only": self.time_bank < self.ACTION_COST,
            "fearless": self.fearless,
            "replay": [dict(item) for item in self.replay],
        }
