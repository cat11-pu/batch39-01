from dataclasses import dataclass


@dataclass
class _Request:
    source: str
    strength: float
    priority: int
    duration: float
    created_at: float
    expires_at: float
    frame: int


@dataclass
class _Freeze:
    source: str
    sources: list
    strength: float
    priority: int
    duration: float
    remaining: float


class HitstopQueue:
    def __init__(self, max_duration=0.5, min_scale=0.05, substep=1.0 / 60.0):
        self.max_duration = max(0.0, float(max_duration))
        self.min_scale = max(0.0, min(1.0, float(min_scale)))
        self.substep = max(1e-4, float(substep))

        self._requests = []
        self._freeze = None
        self._clock = 0.0
        self._frame = 0

    def add(self, source, strength, priority, duration, now=0.0, ignore=False):
        now = float(now)
        if ignore:
            return
        self._clock = max(self._clock, now)

        duration = max(0.0, float(duration))
        if duration <= 0.0:
            return

        self._requests.append(
            _Request(
                source=source,
                strength=max(0.0, float(strength)),
                priority=int(priority),
                duration=duration,
                created_at=now,
                expires_at=now + duration,
                frame=self._frame,
            )
        )

    def update(self, dt, paused=False):
        dt = max(0.0, float(dt))
        self._drain_requests()

        if not paused:
            self._advance(dt)
            self._prune_expired()

        self._frame += 1
        return self._state()

    def clear_scene(self):
        self._requests.clear()
        self._freeze = None
        self._clock = 0.0
        self._frame = 0

    def _drain_requests(self):
        if not self._requests:
            return

        grouped = {}
        order = []
        for request in self._requests:
            if request.expires_at < self._clock:
                continue
            if request.frame not in grouped:
                grouped[request.frame] = []
                order.append(request.frame)
            grouped[request.frame].append(request)
        self._requests.clear()

        for frame in order:
            self._apply_group(grouped[frame])

    def _apply_group(self, requests):
        top_priority = max(request.priority for request in requests)
        top = [request for request in requests if request.priority == top_priority]
        sources = []
        for request in requests:
            if request.source not in sources:
                sources.append(request.source)

        strength = sum(request.strength for request in requests)
        duration = min(self.max_duration, sum(request.duration for request in requests))
        if duration <= 0.0:
            return

        freeze = _Freeze(
            source=top[-1].source,
            sources=sources,
            strength=strength,
            priority=top_priority,
            duration=duration,
            remaining=duration,
        )

        active = self._freeze
        if active is None or active.remaining <= 0.0:
            self._freeze = freeze
            return

        if freeze.priority > active.priority:
            self._freeze = freeze
            return
        if freeze.priority < active.priority:
            return

        active.strength += freeze.strength
        active.sources = list(dict.fromkeys(active.sources + freeze.sources))
        active.duration = min(
            self.max_duration, max(active.duration, active.remaining + freeze.duration)
        )
        active.remaining = min(
            self.max_duration, active.remaining + freeze.duration
        )

    def _advance(self, dt):
        remaining_dt = dt
        while remaining_dt > 0.0:
            step = min(remaining_dt, self.substep)
            self._clock += step
            remaining_dt -= step

            freeze = self._freeze
            if freeze is None:
                continue

            freeze.remaining = max(0.0, freeze.remaining - step)
            if freeze.remaining <= 0.0:
                freeze.remaining = 0.0
                self._freeze = None
                if remaining_dt > 0.0:
                    self._clock += remaining_dt
                return

    def _prune_expired(self):
        if self._requests:
            self._requests = [
                request
                for request in self._requests
                if request.expires_at >= self._clock
            ]

    def _target_scale(self, strength):
        return max(self.min_scale, 1.0 - 0.25 * strength)

    def _current_scale(self):
        freeze = self._freeze
        if freeze is None or freeze.remaining <= 0.0:
            return 1.0

        duration = max(freeze.duration, freeze.remaining, 1e-9)
        progress = 1.0 - freeze.remaining / duration
        target = self._target_scale(freeze.strength)
        return min(1.0, max(self.min_scale, target + (1.0 - target) * progress))

    def _state(self):
        freeze = self._freeze
        active = freeze is not None and freeze.remaining > 0.0
        if active:
            source = freeze.source
            sources = list(freeze.sources)
            remaining = freeze.remaining
            time_scale = self._current_scale()
            priority = freeze.priority
            strength = freeze.strength
        else:
            source = None
            sources = []
            remaining = 0.0
            time_scale = 1.0
            priority = None
            strength = 0.0

        return {
            "time_scale": time_scale,
            "ui_scale": 1.0,
            "audio_scale": 1.0,
            "camera_scale": 1.0,
            "remaining": remaining,
            "source": source,
            "sources": sources,
            "priority": priority,
            "strength": strength,
            "active": active,
            "pending": len(self._requests) + (1 if active else 0),
        }
