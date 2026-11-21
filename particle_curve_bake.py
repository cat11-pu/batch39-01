import bisect
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable, List, Tuple


_QUALITY_SCALE = {
    "high": 1.0,
    "medium": 0.75,
    "low": 0.5,
}


class _ReadOnlyDict(dict):
    """A dict whose contents cannot be changed after it is returned."""

    def _read_only(self, *args, **kwargs):
        raise TypeError("baked curve result is read-only")

    __setitem__ = _read_only
    __delitem__ = _read_only
    clear = _read_only
    pop = _read_only
    popitem = _read_only
    setdefault = _read_only
    update = _read_only


class _ReadOnlyList(list):
    """A list-compatible, immutable sequence."""

    def _read_only(self, *args, **kwargs):
        raise TypeError("baked curve result is read-only")

    __setitem__ = _read_only
    __delitem__ = _read_only
    __iadd__ = _read_only
    __imul__ = _read_only
    append = _read_only
    clear = _read_only
    extend = _read_only
    insert = _read_only
    pop = _read_only
    remove = _read_only
    reverse = _read_only
    sort = _read_only


@dataclass(frozen=True)
class _Key:
    t: float
    v: Any
    ease: str = "linear"
    cp: Tuple[float, ...] = ()


class ParticleCurveBake:
    """Bake an animation curve into a deterministic lookup table.

    Keys are dicts of the form ``{"t": float, "v": value, "ease": str,
    "cp": [...]}``. The easing configured on a key controls the segment
    that ends at that key.
    """

    QUALITY_FPS_SCALE = _QUALITY_SCALE

    def __init__(self, quality="high", value_range=(0.0, 1.0)):
        self.quality = str(quality).strip().lower()
        if self.quality not in _QUALITY_SCALE:
            self.quality = "high"

        try:
            lo, hi = value_range
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError):
            lo, hi = 0.0, 1.0
        if not math.isfinite(lo) or not math.isfinite(hi):
            lo, hi = 0.0, 1.0
        if lo > hi:
            lo, hi = hi, lo
        self.value_range = (lo, hi)

        self.duration = 0.0
        self.loop = False
        self.fps = 60.0
        self._keys: List[_Key] = []
        self._sample_times: List[float] = []
        self._sample_values: List[Any] = []
        self._result = None

    # ------------------------------------------------------------------ bake

    def bake(
        self,
        keys,
        duration,
        loop=False,
        fps=60,
        seed=None,
        burst=None,
        prewarm=None,
    ):
        """Bake keyframes into a read-only, repeatable sample table."""

        duration = float(duration)
        if not math.isfinite(duration) or duration < 0.0:
            raise ValueError("duration must be a finite non-negative number")
        fps = float(fps)
        if not math.isfinite(fps) or fps <= 0.0:
            raise ValueError("fps must be a finite positive number")

        normalized = self._normalize_keys(keys)
        if not normalized:
            raise ValueError("bake requires at least one key")

        self.duration = duration
        self.loop = bool(loop)
        self.fps = fps
        self._keys = normalized

        sample_times = self._build_sample_times()
        sample_values = [self._evaluate(t) for t in sample_times]
        self._sample_times = sample_times
        self._sample_values = sample_values

        key_times = [key.t for key in normalized]
        key_values = [self._finalize(key.v) for key in normalized]

        result = {
            "times": _ReadOnlyList(key_times),
            "values": _ReadOnlyList(key_values),
            "samples": len(sample_times),
            "sample_count": len(sample_times),
            "sample_times": _ReadOnlyList(sample_times),
            "sample_values": _ReadOnlyList(
                [self._finalize(value) for value in sample_values]
            ),
            "keys": _ReadOnlyList(
                [
                    _ReadOnlyDict(
                        {
                            "t": key.t,
                            "v": self._freeze_value(self._copy_value(key.v)),
                            "ease": key.ease,
                            "cp": _ReadOnlyList(key.cp),
                        }
                    )
                    for key in normalized
                ]
            ),
            "duration": duration,
            "loop": bool(loop),
            "fps": fps,
            "quality": self.quality,
            "value_range": tuple(self.value_range),
            "seed": seed,
            "readonly": True,
        }

        if burst is not None:
            result["burst"] = _ReadOnlyList(self.burst(int(burst), seed=seed))
        if prewarm is not None:
            warm_time = -abs(float(prewarm))
            result["prewarm"] = _ReadOnlyList(self.prewarm(warm_time, 0.0))

        self._result = _ReadOnlyDict(result)
        return self._result

    # --------------------------------------------------------------- sampling

    def sample(self, t):
        """Return the baked value at *t* without touching the keyframes."""

        if not self._sample_times:
            raise RuntimeError("bake must be called before sample")

        t = float(t)
        if self.loop and self.duration > 0.0:
            t %= self.duration

        times = self._sample_times
        values = self._sample_values

        if t <= times[0]:
            return self._finalize(values[0])
        if t >= times[-1]:
            return self._finalize(values[-1])

        index = bisect.bisect_right(times, t) - 1
        if index >= len(times) - 1:
            return self._finalize(values[-1])

        t0, t1 = times[index], times[index + 1]
        if t1 <= t0:
            return self._finalize(values[index])

        amount = (t - t0) / (t1 - t0)
        return self._finalize(self._lerp(values[index], values[index + 1], amount))

    def sample_color(self, t):
        """Return a baked color value, with RGBA alpha premultiplied."""

        return self.sample(t)

    def prewarm(self, start_time, end_time=0.0, step=None):
        """Evaluate a pre-warm interval, including negative timestamps."""

        start_time = float(start_time)
        end_time = float(end_time)
        if step is None:
            step = 1.0 / self.fps if self.fps > 0.0 else 1.0 / 60.0
        step = abs(float(step))
        if step <= 0.0:
            step = 1.0 / 60.0

        values = []
        t = start_time
        if start_time <= end_time:
            while t < end_time:
                values.append(self.sample(t))
                t += step
        else:
            while t > end_time:
                values.append(self.sample(t))
                t -= step
        values.append(self.sample(end_time))
        return values

    # ------------------------------------------------------------ burst/random

    def burst(self=None, count=None, seed=None, t=None, spread=0.0, jitter=0.0):
        """Return a caller-seeded, repeatable burst sequence.

        With no particle timing arguments this is a sequence of normalized
        random values. When ``t`` is supplied it returns particle records
        sampled from this baked curve.
        """

        # Also allow the class-style call ParticleCurveBake.burst(count, seed).
        if not isinstance(self, ParticleCurveBake):
            if self is None:
                pass
            elif count is None:
                count = self
            else:
                if seed is None:
                    seed = count
                count = self
            self = None

        count = int(count)
        if count < 0:
            raise ValueError("count must be non-negative")

        rng = random.Random(0 if seed is None else seed)
        if t is None and not spread and not jitter:
            return [rng.random() for _ in range(count)]

        base_time = 0.0 if t is None else float(t)
        spread = abs(float(spread))
        jitter = abs(float(jitter))
        particles = []
        for index in range(count):
            time = base_time + rng.uniform(0.0, spread) if spread else base_time
            offset = rng.uniform(-jitter, jitter) if jitter else 0.0
            value = self.sample(time) if self is not None else 0.0
            particles.append(
                {
                    "index": index,
                    "time": time,
                    "value": self._offset_value(value, offset)
                    if self is not None
                    else offset,
                }
            )
        return particles

    spawn_burst = burst
    emit_burst = burst
    generate_burst = burst
    bake_burst = burst

    def random_sequence(self, count, seed=None):
        """Return a repeatable sequence of normalized random samples."""

        rng = random.Random(0 if seed is None else seed)
        return [rng.random() for _ in range(int(count))]

    # ------------------------------------------------------------------ color

    @staticmethod
    def premultiply(r, g=None, b=None, a=None):
        """Premultiply RGB channels by alpha.

        Accepts either four channel arguments or one color sequence.
        """

        if g is None:
            return ParticleCurveBake.premultiply_alpha(r)
        if b is None:
            return ParticleCurveBake.premultiply_alpha(r, g)
        a = float(a)
        return (float(r) * a, float(g) * a, float(b) * a, a)

    @staticmethod
    def premultiply_alpha(color, alpha=None):
        """Premultiply a color sequence, returning the same sequence type."""

        values = list(color)
        if alpha is None:
            if len(values) < 2:
                return values
            alpha = values[-1]
            channels = values[:-1]
        else:
            channels = values
        alpha = float(alpha)
        result = [float(channel) * alpha for channel in channels] + [alpha]
        return tuple(result) if isinstance(color, tuple) else result

    premultiply_color = premultiply_alpha
    premultiply_rgba = premultiply

    # --------------------------------------------------------------- helpers

    def _normalize_keys(self, keys: Iterable[Any]) -> List[_Key]:
        entries = []
        for index, raw in enumerate(keys):
            if isinstance(raw, dict):
                t = raw.get("t", raw.get("time", 0.0))
                value = raw.get("v", raw.get("value", 0.0))
                ease = raw.get("ease", raw.get("easing", "linear"))
                cp = raw.get("cp", raw.get("control_points", ()))
            else:
                t, value = raw[0], raw[1]
                ease = raw[2] if len(raw) > 2 else "linear"
                cp = raw[3] if len(raw) > 3 else ()

            entries.append(
                (
                    float(t),
                    index,
                    self._copy_value(value),
                    self._normalize_ease(ease),
                    self._normalize_cp(cp),
                )
            )

        # Python's sort is stable, so equal timestamps retain input order.
        entries.sort(key=lambda entry: (entry[0], entry[1]))

        by_time = {}
        order = []
        for t, _, value, ease, cp in entries:
            if t == 0.0:
                t = 0.0
            if t not in by_time:
                order.append(t)
            # A later key at the same timestamp replaces the earlier one.
            by_time[t] = _Key(t, value, ease, cp)
        return [by_time[t] for t in order]

    def _build_sample_times(self) -> List[float]:
        if self.duration <= 0.0:
            return [0.0]

        scale = _QUALITY_SCALE[self.quality]
        step = 1.0 / (self.fps * scale)
        intervals = max(1, int(math.floor(self.duration / step)))
        times = [index * step for index in range(intervals)]
        times.append(self.duration)

        # Keep key timestamps so extrema survive a reduced sample count.
        for key in self._keys:
            if 0.0 <= key.t <= self.duration:
                times.append(key.t)

        # The seam is explicit, even for sparse/low-quality tables.
        times.append(0.0)
        times.append(self.duration)
        times.sort()

        unique = []
        for t in times:
            t = min(max(t, 0.0), self.duration)
            if not unique or abs(t - unique[-1]) > 1e-12:
                unique.append(t)
        return unique

    def _evaluate(self, t: float):
        if not self._keys:
            return self._clamp_value(0.0)
        if len(self._keys) == 1:
            return self._clamp_value(self._keys[0].v)

        if self.loop and self.duration > 0.0:
            t %= self.duration
            keys = self._extended_loop_keys()
        else:
            keys = self._keys
            if self.duration > 0.0:
                t = min(max(t, 0.0), self.duration)

        if t <= keys[0].t:
            return self._clamp_value(keys[0].v)
        if t >= keys[-1].t:
            return self._clamp_value(keys[-1].v)

        key_times = [key.t for key in keys]
        index = bisect.bisect_right(key_times, t) - 1
        left = keys[index]
        right = keys[index + 1]
        span = right.t - left.t
        if span <= 0.0:
            return self._clamp_value(right.v)

        progress = (t - left.t) / span
        eased = self._apply_ease(progress, right.ease, right.cp)
        return self._clamp_value(self._lerp(left.v, right.v, eased))

    def _extended_loop_keys(self) -> List[_Key]:
        if not self._keys or self.duration <= 0.0:
            return list(self._keys)

        first = self._keys[0]
        last = self._keys[-1]
        result = []

        before = _Key(last.t - self.duration, last.v, last.ease, last.cp)
        if before.t < first.t:
            result.append(before)
        result.extend(self._keys)

        after = _Key(first.t + self.duration, first.v, first.ease, first.cp)
        if after.t > last.t:
            result.append(after)
        return result

    @staticmethod
    def _normalize_ease(ease) -> str:
        if callable(ease):
            return "custom_callable"
        if ease is None:
            return "linear"

        name = str(ease).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "easein": "in",
            "ease_in": "in",
            "easeinquad": "in",
            "easeincubic": "in",
            "easeout": "out",
            "ease_out": "out",
            "easeoutquad": "out",
            "easeoutcubic": "out",
            "easeinout": "in_out",
            "ease_in_out": "in_out",
            "ease_inout": "in_out",
            "easeinoutquad": "in_out",
            "easeinoutcubic": "in_out",
            "inout": "in_out",
            "smooth": "in_out",
            "smoothstep": "in_out",
            "none": "linear",
            "bezier": "custom",
            "cubic_bezier": "custom",
            "control_points": "custom",
        }
        return aliases.get(name, name)

    @staticmethod
    def _normalize_cp(cp) -> Tuple[float, ...]:
        if cp is None:
            return ()
        if isinstance(cp, dict):
            cp = [
                cp.get("x1", cp.get("x", 0.0)),
                cp.get("y1", cp.get("y", 0.0)),
                cp.get("x2", cp.get("x", 0.0)),
                cp.get("y2", cp.get("y", 0.0)),
            ]
        if isinstance(cp, (list, tuple)):
            flat = []
            for item in cp:
                if isinstance(item, (list, tuple)):
                    flat.extend(item)
                else:
                    flat.append(item)
            try:
                return tuple(float(item) for item in flat)
            except (TypeError, ValueError):
                return ()
        return ()

    @staticmethod
    def _apply_ease(progress: float, ease: str, cp: Tuple[float, ...]) -> float:
        p = min(max(float(progress), 0.0), 1.0)
        if ease in ("linear", "none"):
            return p
        if ease in ("in", "ease_in", "easein"):
            return p * p
        if ease in ("out", "ease_out", "easeout"):
            return 1.0 - (1.0 - p) * (1.0 - p)
        if ease in ("in_out", "ease_in_out", "inout", "smooth", "smoothstep"):
            return p * p * (3.0 - 2.0 * p)
        if ease in ("custom", "bezier", "cubic_bezier", "custom_callable") or cp:
            return ParticleCurveBake._cubic_bezier(p, cp)
        return p

    @staticmethod
    def _cubic_bezier(progress: float, cp: Tuple[float, ...]) -> float:
        if not cp:
            return progress
        if len(cp) >= 4:
            x1, y1, x2, y2 = cp[:4]
        elif len(cp) >= 2:
            # A single control point followed by the implicit end point.
            x1, y1 = cp[:2]
            x2, y2 = 1.0, 1.0
        else:
            return progress

        x1 = min(max(x1, 0.0), 1.0)
        x2 = min(max(x2, 0.0), 1.0)
        if progress <= 0.0:
            return 0.0
        if progress >= 1.0:
            return 1.0

        low, high = 0.0, 1.0
        for _ in range(40):
            u = (low + high) * 0.5
            x = (
                3.0 * (1.0 - u) ** 2 * u * x1
                + 3.0 * (1.0 - u) * u * u * x2
                + u ** 3
            )
            if x < progress:
                low = u
            else:
                high = u
        u = (low + high) * 0.5
        return (
            3.0 * (1.0 - u) ** 2 * u * y1
            + 3.0 * (1.0 - u) * u * u * y2
            + u ** 3
        )

    def _lerp(self, left: Any, right: Any, amount: float) -> Any:
        if self._is_sequence(left) or self._is_sequence(right):
            left_values = self._as_list(left)
            right_values = self._as_list(right)
            if len(left_values) != len(right_values):
                return right
            result = [
                float(a) + (float(b) - float(a)) * amount
                for a, b in zip(left_values, right_values)
            ]
            return tuple(result) if isinstance(left, tuple) else result
        return float(left) + (float(right) - float(left)) * amount

    def _clamp_value(self, value: Any) -> Any:
        if self._is_sequence(value):
            values = [self._clamp_component(item) for item in value]
            return tuple(values) if isinstance(value, tuple) else values
        return self._clamp_component(value)

    def _clamp_component(self, value: Any) -> float:
        lo, hi = self.value_range
        return min(max(float(value), lo), hi)

    def _finalize(self, value: Any) -> Any:
        value = self._clamp_value(value)
        if self._is_sequence(value) and len(value) == 4:
            alpha = float(value[3])
            channels = [float(channel) * alpha for channel in value[:3]]
            return (
                tuple(channels + [alpha])
                if isinstance(value, tuple)
                else channels + [alpha]
            )
        return value

    def _offset_value(self, value: Any, offset: float):
        if offset == 0.0:
            return value
        if self._is_sequence(value):
            return [self._clamp_component(float(item) + offset) for item in value]
        return self._clamp_component(float(value) + offset)

    @staticmethod
    def _is_sequence(value: Any) -> bool:
        return isinstance(value, (list, tuple))

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        return list(value) if isinstance(value, (list, tuple)) else [value]

    @staticmethod
    def _copy_value(value: Any) -> Any:
        if isinstance(value, list):
            return list(value)
        if isinstance(value, tuple):
            return tuple(value)
        return value

    @classmethod
    def _freeze_value(cls, value: Any) -> Any:
        if isinstance(value, list):
            return tuple(cls._freeze_value(item) for item in value)
        if isinstance(value, tuple):
            return tuple(cls._freeze_value(item) for item in value)
        if isinstance(value, dict):
            return _ReadOnlyDict(
                {key: cls._freeze_value(item) for key, item in value.items()}
            )
        return value
