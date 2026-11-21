import math

_UNSET = object()


class AudioResamplePlan:
    def __init__(self, in_rate, out_rate, channels=1, filter_len=32, bits=16):
        if in_rate <= 0:
            raise ValueError("in_rate must be a positive integer")
        if out_rate <= 0:
            raise ValueError("out_rate must be a positive integer")
        if channels <= 0:
            raise ValueError("channels must be a positive integer")
        if filter_len <= 0:
            raise ValueError("filter_len must be a positive integer")
        if bits <= 0:
            raise ValueError("bits must be a positive integer")
        self.in_rate = in_rate
        self.out_rate = out_rate
        self.channels = channels
        self.filter_len = filter_len
        self.bits = bits
        gcd = math.gcd(in_rate, out_rate)
        self.down = in_rate // gcd
        self.up = out_rate // gcd
        self.passthrough = in_rate == out_rate

    def plan(self, total_in, mix=_UNSET):
        if mix is None:
            raise ValueError("channel change requires an explicit mix matrix")
        if mix is not _UNSET:
            self._validate_mix(mix)
        if total_in < 0:
            raise ValueError("total_in must be non-negative")

        if self.passthrough:
            in_per_block = 1024
            out_per_block = 1024
            total_out = total_in
            latency = 0
            remainder = 0
        else:
            cycles = max(1, math.ceil(self.filter_len / self.up))
            in_per_block = self.down * cycles
            out_per_block = self.up * cycles
            total_out = (total_in * self.up) // self.down
            latency = self.filter_len // 2
            remainder = (total_in * self.up) % self.down

        blocks = math.ceil(total_in / in_per_block) if total_in else 0
        tail_pad = blocks * in_per_block - total_in

        return {
            "ratio": (self.down, self.up),
            "blocks": blocks,
            "in_per_block": in_per_block,
            "out_per_block": out_per_block,
            "total_in": total_in,
            "total_out": total_out,
            "channels": self.channels,
            "latency": latency,
            "remainder": remainder,
            "tail_pad": tail_pad,
            "passthrough": self.passthrough,
        }

    def execute(self, samples, block=1024):
        if block <= 0:
            raise ValueError("block must be a positive integer")
        if samples and isinstance(samples[0], (list, tuple)):
            channels_data = [list(channel) for channel in samples]
        else:
            channels_data = [list(samples)]

        out_channels = [
            self._resample_channel(channel, block) for channel in channels_data
        ]
        total_out = len(out_channels[0]) if out_channels else 0
        if len(out_channels) == 1:
            flat = out_channels[0]
        else:
            flat = [value for frame in zip(*out_channels) for value in frame]

        return {
            "samples": flat,
            "total_out": total_out,
            "channels": len(out_channels),
            "latency": 0 if self.passthrough else self.filter_len // 2,
        }

    def _resample_channel(self, data, block):
        if self.passthrough:
            return [self._to_int(value) for value in data]
        total_in = len(data)
        if total_in == 0:
            return []
        total_out = (total_in * self.up) // self.down
        out = []
        out_index = 0
        for start in range(0, total_in, block):
            end = min(start + block, total_in)
            while out_index < total_out:
                num = out_index * self.down
                idx = num // self.up
                if idx >= end:
                    break
                frac = num - idx * self.up
                x0 = data[idx]
                x1 = data[idx + 1] if idx + 1 < total_in else 0.0
                value = x0 + (x1 - x0) * frac / self.up
                out.append(self._to_int(value))
                out_index += 1
        return out

    def _to_int(self, value):
        scale = 1 << (self.bits - 1)
        quantized = int(round(value * scale))
        return max(-scale, min(scale - 1, quantized))

    def _validate_mix(self, mix):
        rows = list(mix)
        if not rows:
            raise ValueError("mix matrix must not be empty")
        for row in rows:
            if not isinstance(row, (list, tuple)) or not row:
                raise ValueError("mix matrix rows must be non-empty sequences")
