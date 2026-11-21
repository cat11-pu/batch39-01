from bisect import bisect_right
from fractions import Fraction


class KeyframeSeekIndex:
    """Incremental keyframe seek index.

    Entries are read from the container in decode order, sorted by
    presentation time, and queried with a single boundary rule: the
    seek target maps to the last keyframe whose (segment-adjusted)
    presentation time is not greater than the target.
    """

    INDEX_VERSION = 1

    def __init__(self, timescale=90000, live=False):
        if timescale <= 0:
            raise ValueError("timescale must be positive")
        self.timescale = int(timescale)
        self.live = bool(live)
        self.version = self.INDEX_VERSION
        self.digest = ""
        self._records = []
        self._pts_keys = []
        self._decode_seq = 0
        self._segment_bases = {}
        self.corrupt_entries = []

    def ticks_to_seconds(self, ticks):
        return Fraction(int(ticks), self.timescale)

    def seconds_to_ticks(self, seconds):
        ticks = Fraction(seconds) * self.timescale
        return ticks.numerator // ticks.denominator

    def build(self, entries, version=1, digest=""):
        self.version = version
        self.digest = digest
        self._records = []
        self._pts_keys = []
        self._decode_seq = 0
        self._segment_bases = {}
        self.corrupt_entries = []
        for entry in entries:
            self.append(entry)
        return {
            "version": self.version,
            "digest": self.digest,
            "entries": len(self._records),
            "corrupt": len(self.corrupt_entries),
        }

    def load(self, version=None, digest=None):
        if version is not None and version != self.version:
            raise ValueError(
                "index version mismatch: expected %r, got %r" % (self.version, version)
            )
        if digest is not None and digest != self.digest:
            raise ValueError("source digest mismatch")
        return self

    def append(self, entry):
        record = self._make_record(entry)
        if record is None:
            return None
        pos = bisect_right(self._pts_keys, record["pts"])
        self._pts_keys.insert(pos, record["pts"])
        self._records.insert(pos, record)
        return record

    def seek(self, target):
        target = self._coerce_ticks(target)
        empty = {
            "keyframe_pts": None,
            "offset": None,
            "segment": None,
            "predecode": 0,
            "live": self.live,
            "available": False,
        }
        if not self._records:
            return empty
        pos = bisect_right(self._pts_keys, target) - 1
        if pos < 0:
            pos = 0
        record = self._records[pos]
        gap = target - record["pts"]
        predecode = 0 if gap <= 0 else self._ceil_div(gap, self._frame_interval())
        return {
            "keyframe_pts": record["pts"],
            "offset": record["offset"],
            "segment": record["segment"],
            "predecode": predecode,
            "live": self.live,
            "available": True,
        }

    def _make_record(self, entry):
        if entry.get("corrupt"):
            self.corrupt_entries.append(entry)
            return None
        if not entry.get("keyframe", True):
            return None
        pts = entry.get("pts")
        offset = entry.get("offset")
        if pts is None or offset is None:
            self.corrupt_entries.append(entry)
            return None
        segment = entry.get("segment", 0)
        base = self._segment_base(segment)
        record = {
            "pts": int(pts) + base,
            "dts": int(entry.get("dts", pts)),
            "offset": offset,
            "segment": segment,
            "seq": self._decode_seq,
        }
        self._decode_seq += 1
        return record

    def _segment_base(self, segment):
        if segment in self._segment_bases:
            return self._segment_bases[segment]
        base = 0
        if self._records:
            base = max(r["pts"] for r in self._records) + 1
        self._segment_bases[segment] = base
        return base

    def _frame_interval(self):
        interval = None
        for prev, cur in zip(self._pts_keys, self._pts_keys[1:]):
            diff = cur - prev
            if diff > 0 and (interval is None or diff < interval):
                interval = diff
        return interval if interval is not None else self.timescale

    def _coerce_ticks(self, target):
        if isinstance(target, Fraction):
            return target.numerator // target.denominator
        return int(target)

    @staticmethod
    def _ceil_div(a, b):
        return -(-a // b)
