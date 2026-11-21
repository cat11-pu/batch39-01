_EPS = 1e-12


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _smoothstep(value):
    value = _clamp(value)
    return value * value * (3.0 - 2.0 * value)


class _Source:
    __slots__ = (
        "source_id",
        "bus",
        "priority",
        "depth",
        "attack",
        "hold",
        "release",
        "status",
        "hold_remaining",
        "release_remaining",
    )

    def __init__(self, source_id, bus, priority, depth, attack, hold, release):
        self.source_id = source_id
        self.bus = bus
        self.priority = priority
        self.depth = depth
        self.attack = attack
        self.hold = hold
        self.release = release
        self.status = "active"
        self.hold_remaining = 0.0
        self.release_remaining = 0.0


class _BusEnvelope:
    __slots__ = (
        "current",
        "target",
        "phase",
        "start_gain",
        "elapsed",
        "duration",
        "release_hint",
        "has_advanced",
    )

    def __init__(self):
        self.current = 1.0
        self.target = 1.0
        self.phase = None
        self.start_gain = 1.0
        self.elapsed = 0.0
        self.duration = 0.0
        self.release_hint = None
        self.has_advanced = False

    def begin(self, phase, target, duration):
        self.phase = phase
        self.start_gain = self.current
        self.target = target
        self.elapsed = 0.0
        self.duration = max(0.0, duration)
        if self.duration <= _EPS:
            self.current = target
            self.phase = None
            self.elapsed = 0.0
            self.duration = 0.0

    def advance(self, dt):
        if dt <= _EPS:
            return
        self.has_advanced = True
        if self.phase is None:
            return

        self.elapsed += dt
        if self.duration <= _EPS:
            progress = 1.0
        else:
            progress = self.elapsed / self.duration

        if progress >= 1.0:
            self.current = self.target
            self.phase = None
            self.elapsed = 0.0
            self.duration = 0.0
        else:
            self.current = self.start_gain + (
                self.target - self.start_gain
            ) * _smoothstep(progress)


class DuckingEnvelope:
    def __init__(self, attack=0.1, release=0.3, hold=0.0):
        self.attack = max(0.0, float(attack))
        self.release = max(0.0, float(release))
        self.hold = max(0.0, float(hold))
        self._sources = {}
        self._bus_gains = {"music": 1.0, "voice": 1.0}
        self._buses = {"music": _BusEnvelope(), "voice": _BusEnvelope()}

    def add_source(
        self, source_id, bus, priority, depth, start=0.0, hold=None, release=None
    ):
        attack = self.attack if start is None or start <= 0.0 else float(start)
        hold_time = self.hold if hold is None else max(0.0, float(hold))
        release_time = (
            self.release if release is None else max(0.0, float(release))
        )

        source = _Source(
            source_id=source_id,
            bus=bus,
            priority=priority,
            depth=_clamp(float(depth)),
            attack=max(0.0, attack),
            hold=hold_time,
            release=release_time,
        )
        self._sources[source_id] = source
        self._ensure_bus(bus)
        self._refresh_buses()

    def remove_source(self, source_id):
        source = self._sources.get(source_id)
        if source is None or source.status == "done":
            return
        if source.status == "release":
            return

        bus_env = self._ensure_bus(source.bus)
        previous_target = bus_env.target
        if not bus_env.has_advanced and previous_target < bus_env.current:
            bus_env.current = previous_target
            bus_env.phase = None
            bus_env.elapsed = 0.0
            bus_env.duration = 0.0

        bus_env.release_hint = source.release
        if source.status == "hold" or source.hold > _EPS:
            source.status = "hold"
            source.hold_remaining = source.hold
            source.release_remaining = source.release
        else:
            source.status = "release"
            source.hold_remaining = 0.0
            source.release_remaining = source.release

        self._refresh_buses()

    def set_bus_gain(self, bus, gain):
        self._bus_gains[bus] = float(gain)
        self._ensure_bus(bus)

    def update(self, dt, paused=False):
        dt = max(0.0, float(dt))
        if paused:
            return self.snapshot()
        if dt <= _EPS:
            self._advance_sources(0.0)
            self._refresh_buses()
            return self.snapshot()

        self._advance_sources(0.0)
        self._refresh_buses()

        remaining = dt
        while remaining > _EPS:
            step = remaining
            for source in self._sources.values():
                if source.status == "hold":
                    step = min(step, max(0.0, source.hold_remaining))
                elif source.status == "release":
                    step = min(step, max(0.0, source.release_remaining))

            if step <= _EPS:
                changed = self._advance_sources(0.0)
                self._refresh_buses()
                if not changed:
                    step = remaining
                else:
                    continue

            self._advance_envelopes(step)
            self._advance_sources(step)
            remaining -= step
            self._refresh_buses()

        self._advance_sources(0.0)
        self._refresh_buses()
        return self.snapshot()

    def snapshot(self):
        gains = {}
        targets = {}
        for bus in sorted(self._buses):
            base = self._bus_gains.get(bus, 1.0)
            env = self._buses[bus]
            gains[bus] = _clamp(base * env.current)
            targets[bus] = _clamp(base * env.target)

        remaining = {}
        for source_id, source in self._sources.items():
            remaining[source_id] = self._source_remaining(source)

        return {"gain": gains, "target": targets, "remaining": remaining}

    def _ensure_bus(self, bus):
        env = self._buses.get(bus)
        if env is None:
            env = _BusEnvelope()
            self._buses[bus] = env
        self._bus_gains.setdefault(bus, 1.0)
        return env

    def _refresh_buses(self):
        for bus, env in self._buses.items():
            candidates = [
                source
                for source in self._sources.values()
                if source.bus == bus and source.status in ("active", "hold")
            ]
            if candidates:
                winner = min(
                    candidates, key=lambda source: (source.depth, -source.priority)
                )
                new_target = winner.depth
            else:
                winner = None
                new_target = 1.0

            if abs(new_target - env.target) <= _EPS:
                env.target = new_target
                continue

            env.target = new_target
            if new_target < env.current - _EPS:
                duration = winner.attack if winner is not None else self.attack
                env.release_hint = None
                env.begin("attack", new_target, duration)
            elif new_target > env.current + _EPS:
                duration = (
                    env.release_hint
                    if env.release_hint is not None
                    else self.release
                )
                env.release_hint = None
                env.begin("release", new_target, duration)
            else:
                env.phase = None
                env.elapsed = 0.0
                env.duration = 0.0

    def _advance_envelopes(self, dt):
        if dt <= _EPS:
            return
        for env in self._buses.values():
            env.advance(dt)

    def _advance_sources(self, dt):
        changed = False
        for source in self._sources.values():
            while True:
                if source.status == "hold" and source.hold_remaining <= _EPS:
                    source.status = "release"
                    source.hold_remaining = 0.0
                    source.release_remaining = source.release
                    changed = True
                    continue
                if source.status == "release" and source.release_remaining <= _EPS:
                    source.status = "done"
                    source.release_remaining = 0.0
                    changed = True
                break

            if dt <= _EPS:
                continue
            if source.status == "hold":
                if dt + _EPS >= source.hold_remaining:
                    source.status = "release"
                    source.hold_remaining = 0.0
                    source.release_remaining = source.release
                    changed = True
                else:
                    source.hold_remaining -= dt
            elif source.status == "release":
                if dt + _EPS >= source.release_remaining:
                    source.status = "done"
                    source.release_remaining = 0.0
                    changed = True
                else:
                    source.release_remaining -= dt
        return changed

    def _source_remaining(self, source):
        if source.status == "done":
            return 0.0
        if source.status == "hold":
            return source.hold_remaining + source.release_remaining
        if source.status == "release":
            return source.release_remaining

        env = self._buses.get(source.bus)
        if env is None or env.phase != "attack":
            return 0.0

        candidates = [
            candidate
            for candidate in self._sources.values()
            if candidate.bus == source.bus
            and candidate.status in ("active", "hold")
        ]
        if not candidates:
            return 0.0
        winner = min(
            candidates, key=lambda candidate: (candidate.depth, -candidate.priority)
        )
        if winner is not source:
            return 0.0
        return max(0.0, env.duration - env.elapsed)
