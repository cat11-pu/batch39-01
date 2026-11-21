"""Multi-resolution peak index for audio waveform rendering."""

import copy
import hashlib


VERSION = 1


class WaveformPeakIndex:
    def __init__(self, bucket=1000, silence=1e-4, max_levels=8,
                 memory_cap=1000000, channels=1, bits=16):
        self.bucket = int(bucket)
        self.silence = float(silence)
        self.max_levels = int(max_levels)
        self.memory_cap = int(memory_cap)
        self.channels = int(channels)
        self.bits = bits
        self._frames = []
        self._levels = []
        self._digest = None

    def _normalize(self, samples, bits):
        """Normalize every supported input format to floats in [-1.0, 1.0]."""
        if bits == "float" or bits is None or (
            samples and isinstance(samples, (list, tuple))
            and isinstance(samples[0], float)
        ):
            return [float(sample) for sample in samples]
        if isinstance(samples, (bytes, bytearray, memoryview)):
            raw = memoryview(bytes(samples))
            if bits == 8:
                return [(byte - 128) / 128.0 for byte in raw]
            if bits == 16:
                if len(raw) % 2:
                    raise ValueError("16-bit packed input length must be even")
                return [
                    int.from_bytes(raw[i:i + 2], "little", signed=True) / 32768.0
                    for i in range(0, len(raw), 2)
                ]
            if bits == 24:
                if len(raw) % 3:
                    raise ValueError("24-bit packed input length must be a multiple of 3")
                return [
                    int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608.0
                    for i in range(0, len(raw), 3)
                ]
            raise ValueError("unsupported packed bit depth: %r" % (bits,))
        if bits == 8:
            return [(int(sample) - 128) / 128.0 for sample in samples]
        if bits == 16:
            return [int(sample) / 32768.0 for sample in samples]
        if bits == 24:
            return [int(sample) / 8388608.0 for sample in samples]
        raise ValueError("unsupported bit depth: %r" % (bits,))

    def _deinterleave(self, normalized, channels):
        frame_count = len(normalized) // channels
        return [
            [normalized[frame * channels + channel] for frame in range(frame_count)]
            for channel in range(channels)
        ]

    def _base_buckets(self, channels_data, from_index=0):
        frame_count = len(channels_data[0]) if channels_data else 0
        result = []
        start = from_index * self.bucket
        bucket_index = from_index
        while start < frame_count:
            end = min(start + self.bucket, frame_count)
            per_channel = []
            for data in channels_data:
                segment = data[start:end]
                per_channel.append({
                    "min": min(segment),
                    "max": max(segment),
                    "silent": all(abs(value) <= self.silence for value in segment),
                })
            entry = {
                "index": bucket_index,
                "start": start,
                "end": end,
                "tail": end - start < self.bucket,
                "channels": per_channel,
            }
            if len(per_channel) > 1:
                entry["min"] = sum(item["min"] for item in per_channel) / len(per_channel)
                entry["max"] = sum(item["max"] for item in per_channel) / len(per_channel)
                entry["silent"] = all(item["silent"] for item in per_channel)
                entry["phase_cancel"] = self._detect_phase_cancel(per_channel)
            else:
                entry["min"] = per_channel[0]["min"]
                entry["max"] = per_channel[0]["max"]
                entry["silent"] = per_channel[0]["silent"]
            result.append(entry)
            start = end
            bucket_index += 1
        return result

    @staticmethod
    def _detect_phase_cancel(per_channel):
        if len(per_channel) < 2:
            return False
        source_energy = sum(
            abs(item["min"]) + abs(item["max"]) for item in per_channel
        )
        mixed_min = sum(item["min"] for item in per_channel) / len(per_channel)
        mixed_max = sum(item["max"] for item in per_channel) / len(per_channel)
        mixed_energy = abs(mixed_min) + abs(mixed_max)
        return source_energy > 0.0 and mixed_energy < source_energy * 0.25

    def _merge_pair(self, left, right, bucket_index):
        per_channel = []
        for index in range(len(left["channels"])):
            left_item = left["channels"][index]
            right_item = right["channels"][index]
            per_channel.append({
                "min": min(left_item["min"], right_item["min"]),
                "max": max(left_item["max"], right_item["max"]),
                "silent": left_item["silent"] and right_item["silent"],
            })
        merged = {
            "index": bucket_index,
            "start": left["start"],
            "end": right["end"],
            "tail": left["tail"] or right["tail"],
            "channels": per_channel,
        }
        if len(per_channel) > 1:
            merged["min"] = sum(item["min"] for item in per_channel) / len(per_channel)
            merged["max"] = sum(item["max"] for item in per_channel) / len(per_channel)
            merged["silent"] = all(item["silent"] for item in per_channel)
            merged["phase_cancel"] = self._detect_phase_cancel(per_channel)
        else:
            merged["min"] = per_channel[0]["min"]
            merged["max"] = per_channel[0]["max"]
            merged["silent"] = per_channel[0]["silent"]
        return merged

    def _build_levels(self, channels_data):
        if not channels_data or not channels_data[0]:
            return []
        levels = [self._base_buckets(channels_data)]
        while len(levels) < self.max_levels and len(levels[-1]) > 1:
            previous = levels[-1]
            current = []
            for position in range(0, len(previous) - 1, 2):
                current.append(self._merge_pair(
                    previous[position], previous[position + 1], position // 2
                ))
            if len(previous) % 2:
                current.append(copy.deepcopy(previous[-1]))
                current[-1]["index"] = len(current) - 1
            levels.append(current)
        return levels

    @staticmethod
    def _bucket_cost(entry):
        return 64 + len(entry["channels"]) * 48

    def _build_cache(self, levels):
        cache = []
        for level_index, level in enumerate(levels):
            cost = sum(self._bucket_cost(entry) for entry in level)
            cache.append({
                "level": level_index,
                "cost": cost,
                "buckets": copy.deepcopy(level),
            })
        evicted = 0
        while sum(entry["cost"] for entry in cache) > self.memory_cap and len(cache) > 1:
            cache.pop()
            evicted += 1
        return cache, evicted

    def _source_digest(self, channels_data, bits):
        hasher = hashlib.sha256()
        hasher.update(b"v%d|ch=%d|bits=%s" % (
            VERSION, len(channels_data), str(bits).encode()))
        for channel in channels_data:
            for value in channel:
                hasher.update(repr(float(value)).encode())
                hasher.update(b",")
            hasher.update(b"|")
        return hasher.hexdigest()

    def _checksum(self, levels, channels_data, bits):
        hasher = hashlib.sha256()
        hasher.update(b"v%d|ch=%d|bits=%s|bucket=%d|levels=%d|frames=%d" % (
            VERSION, len(channels_data), str(bits).encode(), self.bucket,
            len(levels), len(channels_data[0]) if channels_data else 0,
        ))
        for level in levels:
            for entry in level:
                hasher.update(repr((entry["index"], entry["start"], entry["end"],
                                    entry["min"], entry["max"], entry["silent"],
                                    entry["tail"])).encode())
        hasher.update(self._digest.encode())
        return hasher.hexdigest()

    def build(self, samples, channels=None, bits=None):
        channels = self.channels if channels is None else int(channels)
        bits = self.bits if bits is None else bits
        normalized = self._normalize(samples, bits)
        channels_data = self._deinterleave(normalized, channels)
        self.channels = channels
        self.bits = bits
        self._frames = channels_data
        self._levels = self._build_levels(channels_data)
        self._digest = self._source_digest(channels_data, bits)
        return self._generate_result(bits)

    def update(self, samples, start=0):
        if not self._frames or not self._frames[0]:
            return self.build(samples, channels=self.channels, bits=self.bits)
        bits = self.bits
        normalized = self._normalize(samples, bits)
        aligned_start = (int(start) // self.bucket) * self.bucket
        aligned = aligned_start == int(start)
        frame_count = len(normalized) // self.channels
        for channel_index in range(self.channels):
            channel_frames = [
                normalized[frame * self.channels + channel_index]
                for frame in range(frame_count)
            ]
            self._frames[channel_index][
                aligned_start:aligned_start + frame_count
            ] = channel_frames
        first_bucket = aligned_start // self.bucket
        rebuilt = self._base_buckets(self._frames, from_index=first_bucket)
        self._levels[0][first_bucket:first_bucket + len(rebuilt)] = rebuilt
        del self._levels[0][first_bucket + len(rebuilt):]
        for level_index in range(1, len(self._levels)):
            previous = self._levels[level_index - 1]
            current = []
            for position in range(0, len(previous) - 1, 2):
                current.append(self._merge_pair(
                    previous[position], previous[position + 1], position // 2
                ))
            if len(previous) % 2:
                current.append(copy.deepcopy(previous[-1]))
                current[-1]["index"] = len(current) - 1
            self._levels[level_index] = current
        self._digest = self._source_digest(self._frames, bits)
        result = self._generate_result(bits)
        result["aligned"] = aligned
        return result

    def _generate_result(self, bits):
        levels = self._levels
        cache, evicted = self._build_cache(levels)
        if not self._frames or not self._frames[0]:
            return {
                "version": VERSION,
                "levels": 0,
                "buckets": [],
                "channels": self.channels,
                "bits": bits,
                "silent": True,
                "tail": False,
                "phase_cancel": False,
                "evicted": 0,
                "cache": [],
                "digest": self._digest,
                "checksum": self._checksum([], self._frames, bits),
            }
        base = levels[0]
        return {
            "version": VERSION,
            "levels": len(levels),
            "buckets": base,
            "channels": self.channels,
            "bits": bits,
            "silent": all(entry["silent"] for entry in base),
            "tail": base[-1]["tail"],
            "phase_cancel": any(entry.get("phase_cancel", False) for entry in base),
            "evicted": evicted,
            "cache": cache,
            "digest": self._digest,
            "checksum": self._checksum(levels, self._frames, bits),
        }

    def levels(self):
        return copy.deepcopy(self._levels)
