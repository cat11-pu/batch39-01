import bisect


class FlipbookTimeline:
    MODES = ("once", "loop", "pingpong")

    def __init__(self, durations, mode="once", events=None):
        if mode not in self.MODES:
            raise ValueError("unknown mode: %r" % (mode,))
        self.durations = [max(0.0, float(d)) for d in (durations or [0.0])]
        self.mode = mode
        self._cum = [0.0]
        for d in self.durations:
            self._cum.append(self._cum[-1] + d)
        self.total = self._cum[-1]
        self._events = sorted((dict(e) for e in (events or [])),
                              key=lambda e: e["t"])
        self._time = 0.0
        self._paused = False
        self._end_fired = False
        self.on_end = None

    def advance(self, dt):
        if self._paused:
            return self._state()
        dt = float(dt)
        if self.total <= 0.0 or dt == 0.0:
            return self._state()
        start = self._time
        end = start + dt
        events = self._collect_forward(start, end) if dt > 0.0 else []
        self._time = self._normalize(end)
        if (self.mode == "once" and self._time >= self.total
                and not self._end_fired):
            self._end_fired = True
            if callable(self.on_end):
                self.on_end()
        return self._state(events)

    def seek(self, t):
        self._time = self._normalize(float(t))
        if self.mode == "once" and self._time < self.total:
            self._end_fired = False
        return self._state()

    def pause(self):
        self._paused = True
        return self._state()

    def resume(self):
        self._paused = False
        return self._state()

    def _normalize(self, t):
        if self.total <= 0.0:
            return 0.0
        if self.mode == "once":
            return min(max(t, 0.0), self.total)
        period = self.total * 2.0 if self.mode == "pingpong" else self.total
        return t % period

    def _position(self):
        if self.total <= 0.0:
            return 0.0, 1
        t = self._time
        if self.mode == "pingpong":
            m = t % (2.0 * self.total)
            if m <= self.total:
                return m, 1
            return 2.0 * self.total - m, -1
        if self.mode == "loop":
            return t % self.total, 1
        return min(max(t, 0.0), self.total), 1

    def _frame_at(self, pos):
        idx = bisect.bisect_right(self._cum, pos) - 1
        return min(max(idx, 0), len(self.durations) - 1)

    def _weight(self, pos, frame):
        d = self.durations[frame]
        if d <= 0.0:
            return 0.0
        return min(max((pos - self._cum[frame]) / d, 0.0), 1.0)

    def _state(self, events=()):
        pos, direction = self._position()
        frame = self._frame_at(pos)
        n = len(self.durations)
        if self.mode == "loop" and n > 1:
            next_frame = (frame + 1) % n
        elif self.mode == "pingpong":
            next_frame = min(max(frame + direction, 0), n - 1)
        else:
            next_frame = min(frame + 1, n - 1)
        return {
            "frame": frame,
            "next_frame": next_frame,
            "weight": self._weight(pos, frame),
            "direction": direction,
            "time": pos,
            "events": list(events),
        }

    def _collect_forward(self, start, end):
        fired = []
        if not self._events:
            return fired
        if self.mode == "once":
            limit = min(end, self.total)
            for ev in self._events:
                if start < ev["t"] <= limit:
                    fired.append(ev)
        elif self.mode == "loop":
            cur = start
            remaining = end
            while remaining > self.total:
                for ev in self._events:
                    if cur < ev["t"] <= self.total:
                        fired.append(ev)
                cur = 0.0
                remaining -= self.total
            for ev in self._events:
                if cur < ev["t"] <= remaining:
                    fired.append(ev)
        else:  # pingpong
            period = 2.0 * self.total
            cur = start
            while cur < end:
                m = cur % period
                if m < self.total:
                    boundary = cur + (self.total - m)
                    seg_dir = 1
                else:
                    boundary = cur + (period - m)
                    seg_dir = -1
                seg_end = min(boundary, end)
                pos_a = self._map_pingpong(cur)
                pos_b = self._map_pingpong(seg_end)
                if seg_dir == 1:
                    for ev in self._events:
                        if pos_a < ev["t"] <= pos_b:
                            fired.append(ev)
                else:
                    for ev in reversed(self._events):
                        if pos_b <= ev["t"] < pos_a:
                            fired.append(ev)
                cur = seg_end
        return fired

    def _map_pingpong(self, t):
        period = 2.0 * self.total
        m = t % period
        if m <= self.total:
            return m
        return period - m
