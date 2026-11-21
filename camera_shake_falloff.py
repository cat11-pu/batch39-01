import math


MAX_TRANSLATION = 10.0
MAX_ROTATION = 2.0
MAX_SUBSTEP = 1.0 / 60.0
TIME_EPSILON = 1e-9


class CameraShakeFalloff:
    """创伤（trauma）驱动的相机抖动。

    每个来源贡献 strength**2 的创伤能量，多来源按平方和累加后夹到
    max_trauma；创伤以 decay/秒 的固定速率线性衰减，与帧率无关，
    大帧间隔按 MAX_SUBSTEP 拆成子步推进。偏移/旋转由 (seed, 轴, 时间)
    纯函数确定性噪声采样，同一时间序列回放结果一致。
    """

    def __init__(self, decay=1.5, max_trauma=1.0, aim_scale=0.5, seed=0):
        self.decay = decay
        self.max_trauma = max_trauma
        self.aim_scale = aim_scale
        self.seed = seed
        self._time = 0.0
        self._sources = []

    def add(self, source, strength, frequency=1.0, duration=0.2, axis=(1.0, 1.0, 1.0)):
        if strength < 0:
            raise ValueError("shake strength must be non-negative, got %r" % (strength,))
        if strength == 0:
            return
        self._sources.append(
            {
                "source": source,
                "strength": float(strength),
                "energy": float(strength) ** 2,
                "frequency": float(frequency),
                "duration": float(duration),
                "axis": (float(axis[0]), float(axis[1]), float(axis[2])),
                "age": 0.0,
            }
        )

    def update(self, dt, paused=False, aim=False):
        dt = max(0.0, float(dt))
        if not paused and dt > 0.0:
            steps = max(1, int(math.ceil(dt / MAX_SUBSTEP)))
            step = dt / steps
            for _ in range(steps):
                self._advance(step)
            self._time += dt

        trauma = self._current_trauma()
        axis = self._combined_axis()
        frequency = max(
            (src["frequency"] for src in self._sources), default=1.0
        )
        phase = self._time * frequency
        scale = self.aim_scale if aim else 1.0

        offset_x = (
            trauma * MAX_TRANSLATION * self._noise(0, phase) * axis[0] * scale
        )
        offset_y = (
            trauma * MAX_TRANSLATION * self._noise(1, phase) * axis[1] * scale
        )
        rotation = (
            trauma * MAX_ROTATION * self._noise(2, phase) * axis[2] * scale
        )

        return {
            "trauma": trauma,
            "offset": (offset_x, offset_y),
            "rotation": rotation,
            "ui_offset": (0.0, 0.0),
        }

    def snapshot(self):
        return {
            "trauma": self._current_trauma(),
            "time": self._time,
            "sources": [
                {
                    "source": src["source"],
                    "strength": src["strength"],
                    "trauma": max(0.0, src["energy"] - self.decay * src["age"]),
                    "frequency": src["frequency"],
                    "duration": src["duration"],
                    "axis": src["axis"],
                    "age": src["age"],
                }
                for src in self._sources
            ],
        }

    def _advance(self, step):
        alive = []
        for src in self._sources:
            src["age"] += step
            if src["age"] <= src["duration"] + TIME_EPSILON:
                alive.append(src)
        self._sources = alive

    def _remaining(self, src):
        return max(0.0, src["energy"] - self.decay * src["age"])

    def _current_trauma(self):
        total = sum(self._remaining(src) for src in self._sources)
        return min(self.max_trauma, max(0.0, total))

    def _combined_axis(self):
        weight = 0.0
        axes = [0.0, 0.0, 0.0]
        for src in self._sources:
            contribution = self._remaining(src)
            if contribution <= 0.0:
                continue
            for index in range(3):
                axes[index] += src["axis"][index] * contribution
            weight += contribution
        if weight <= 0.0:
            return (1.0, 1.0, 1.0)
        return (axes[0] / weight, axes[1] / weight, axes[2] / weight)

    def _hash(self, axis, index):
        value = (
            (index + 1) * 374761393
            + (axis + 1) * 668265263
            + (self.seed + 1) * 1274126177
        )
        value &= 0xFFFFFFFF
        value = (value ^ (value >> 13)) * 1274126177
        value &= 0xFFFFFFFF
        value ^= value >> 16
        return value / 2147483648.0 - 1.0

    def _noise(self, axis, time):
        base = math.floor(time)
        fraction = time - base
        blend = fraction * fraction * (3.0 - 2.0 * fraction)
        low = self._hash(axis, base)
        high = self._hash(axis, base + 1)
        return low + (high - low) * blend
