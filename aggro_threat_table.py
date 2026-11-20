class AggroThreatTable:
    def __init__(self, heal_factor=0.5, switch_ratio=1.1, decay=0.05,
                 idle_timeout=5.0, pet_merge_ratio=1.0):
        self.heal_factor = heal_factor
        self.switch_ratio = switch_ratio
        self.decay = decay
        self.idle_timeout = idle_timeout
        self.pet_merge_ratio = pet_merge_ratio
        self._threat = {}
        self._sources = {}
        self._owners = {}
        self._current = None
        self._taunt_target = None
        self._taunt_until = 0.0
        self._now = 0.0
        self._last_update = 0.0
        self._last_attack = 0.0

    def add(self, unit, owner=None):
        if unit in self._threat:
            return
        self._threat[unit] = 0.0
        self._sources[unit] = {}
        if owner is not None:
            self._owners[unit] = owner
            if owner not in self._threat:
                self.add(owner)

    def remove(self, unit):
        if unit not in self._threat:
            return
        owner = self._owners.get(unit)
        if owner is not None and owner in self._threat:
            merged = self._threat[unit] * self.pet_merge_ratio
            self._threat[owner] += merged
            for kind, value in self._sources[unit].items():
                self._sources[owner][kind] = (
                    self._sources[owner].get(kind, 0.0)
                    + value * self.pet_merge_ratio
                )
        del self._threat[unit]
        del self._sources[unit]
        self._owners.pop(unit, None)
        if self._current == unit:
            self._current = None
        if self._taunt_target == unit:
            self._taunt_target = None

    def damage(self, source, hp_lost, distance=0.0, visible=True):
        if not visible:
            return
        amount = hp_lost * self._distance_factor(distance)
        self._add_threat(source, "damage", amount)
        self._last_attack = self._now

    def heal(self, source, effective, overheal=0.0):
        self._add_threat(source, "heal", effective * self.heal_factor)

    def taunt(self, source, duration, now, immune=False):
        self._now = now
        if immune or source not in self._threat:
            return
        self._taunt_target = source
        self._taunt_until = now + duration

    def update(self, now, in_combat=True):
        self._now = now
        idle = now - self._last_attack > self.idle_timeout
        if not in_combat or idle:
            elapsed = max(0.0, now - self._last_update)
            if elapsed:
                factor = (1.0 - self.decay) ** elapsed
                for unit in self._threat:
                    self._threat[unit] *= factor
                for sources in self._sources.values():
                    for kind in sources:
                        sources[kind] *= factor
        self._last_update = now
        if self._taunt_target is not None and now >= self._taunt_until:
            self._taunt_target = None

    def target(self):
        if (self._taunt_target is not None
                and self._now < self._taunt_until
                and self._taunt_target in self._threat):
            return self._taunt_target
        if not self._threat:
            return None
        best = max(self._threat, key=lambda u: self._threat[u])
        if self._current not in self._threat:
            self._current = best
        elif (best != self._current
                and self._threat[best]
                > self._threat[self._current] * self.switch_ratio):
            self._current = best
        return self._current

    def reset(self):
        self._threat.clear()
        self._sources.clear()
        self._owners.clear()
        self._current = None
        self._taunt_target = None
        self._taunt_until = 0.0
        self._last_attack = 0.0
        self._last_update = 0.0
        self._now = 0.0

    def snapshot(self):
        return {
            "threat": dict(self._threat),
            "sources": {unit: dict(s) for unit, s in self._sources.items()},
            "sorted": [
                {"unit": unit, "threat": self._threat[unit]}
                for unit in sorted(
                    self._threat, key=lambda u: self._threat[u], reverse=True
                )
            ],
        }

    def _add_threat(self, unit, kind, amount):
        if unit not in self._threat:
            owner = self._owners.get(unit)
            if owner is None:
                return
            unit = owner
        owner = self._owners.get(unit)
        if owner is not None and owner in self._threat:
            unit = owner
        self._threat[unit] += amount
        sources = self._sources[unit]
        sources[kind] = sources.get(kind, 0.0) + amount
        if self._current is None:
            self._current = unit

    @staticmethod
    def _distance_factor(distance):
        if distance <= 10.0:
            return 1.0
        if distance <= 20.0:
            return 0.75
        if distance <= 30.0:
            return 0.5
        return 0.25
