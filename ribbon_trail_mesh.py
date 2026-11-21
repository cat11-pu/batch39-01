"""Build ribbon meshes for golf-swing trail playback.

The builder is deliberately self contained (pure Python) so it can be used by
the replay tool without pulling in a maths/mesh package.
"""

from __future__ import annotations

import math
from collections.abc import Mapping


_EPS = 1e-12


def _pick(options, *names, default=None):
    for name in names:
        if name in options and options[name] is not None:
            return options[name]
    return default


def _number(value, default=0.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _optional_number(value):
    if value is None:
        return None
    value = _number(value, float("nan"))
    return value if math.isfinite(value) else None


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _mul(a, scale):
    return tuple(x * scale for x in a)


def _length(a):
    return math.sqrt(sum(x * x for x in a))


def _normalize(a, fallback=None):
    length = _length(a)
    if length <= _EPS:
        return fallback
    return _mul(a, 1.0 / length)


def _distance(a, b):
    return _length(_sub(a, b))


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _dedupe_consecutive(items):
    result = []
    for item in items:
        if not result or item is not result[-1]:
            result.append(item)
    return result


class RibbonTrailMesh:
    """Create a sampled, segmented and capped ribbon from trail points.

    Parameters are intentionally accepted through both the explicit arguments
    and ``**over`` so older replay code can keep using its own option names.
    """

    def __init__(self, min_distance=0.1, max_points=256, max_angle=60.0, **over):
        self._overrides = dict(over)
        self._overrides.update(
            min_distance=min_distance,
            max_points=max_points,
            max_angle=max_angle,
        )

    # ------------------------------------------------------------------
    # Configuration and input handling
    # ------------------------------------------------------------------
    def _config(self, overrides):
        options = dict(self._overrides)
        options.update(overrides)

        max_points = _pick(
            options, "max_points", "max_samples", "point_limit", default=256
        )
        try:
            max_points = int(max_points)
        except (TypeError, ValueError):
            max_points = 256

        taper = _pick(
            options,
            "taper",
            "end_taper",
            "taper_end",
            "finish_taper",
            default=False,
        )
        taper_length = _optional_number(
            _pick(
                options,
                "taper_length",
                "end_taper_length",
                "finish_taper_length",
                default=None,
            )
        )
        end_width_scale = _number(
            _pick(
                options,
                "end_width_scale",
                "taper_scale",
                "tip_width_scale",
                "end_scale",
                default=0.1,
            ),
            0.1,
        )
        if isinstance(taper, (int, float)) and not isinstance(taper, bool):
            value = float(taper)
            if 0.0 <= value <= 1.0:
                end_width_scale = value
            elif value > 0.0 and taper_length is None:
                taper_length = value
            taper = True

        up = _pick(options, "up", "up_vector", "normal", default=(0.0, 0.0, 1.0))
        try:
            up = tuple(_number(value) for value in up)
        except TypeError:
            up = (0.0, 0.0, 1.0)

        dedupe_epsilon = _number(
            _pick(options, "dedupe_epsilon", "duplicate_epsilon", default=1e-9),
            1e-9,
        )

        return {
            "min_distance": max(
                0.0,
                _number(
                    _pick(
                        options,
                        "min_distance",
                        "sample_distance",
                        "distance_threshold",
                        "min_dist",
                        default=0.1,
                    ),
                    0.1,
                ),
            ),
            "max_points": max(0, max_points),
            "max_angle": max(
                0.0,
                _number(
                    _pick(
                        options,
                        "max_angle",
                        "max_turn_angle",
                        "angle_threshold",
                        default=60.0,
                    ),
                    60.0,
                ),
            ),
            "min_time": _optional_number(
                _pick(
                    options,
                    "min_time",
                    "min_time_step",
                    "max_time_step",
                    "max_time_delta",
                    "time_step",
                    "time_delta",
                    "time_threshold",
                    "sample_time",
                    "min_interval",
                    default=None,
                )
            ),
            "max_length": _optional_number(
                _pick(
                    options,
                    "max_length",
                    "max_total_length",
                    "max_arc_length",
                    "total_length_limit",
                    default=None,
                )
            ),
            "max_duration": _optional_number(
                _pick(
                    options,
                    "max_duration",
                    "max_replay_duration",
                    "duration_limit",
                    default=None,
                )
            ),
            "teleport_distance": max(
                0.0,
                _number(
                    _pick(
                        options,
                        "teleport_distance",
                        "max_jump",
                        "jump_threshold",
                        "teleport_threshold",
                        default=10.0,
                    ),
                    10.0,
                ),
            ),
            "max_time_gap": _optional_number(
                _pick(options, "max_time_gap", "max_time_jump", default=None)
            ),
            "taper": bool(taper),
            "taper_length": taper_length,
            "end_width_scale": max(0.0, end_width_scale),
            "caps": bool(_pick(options, "caps", "cap", default=False)),
            "cap_segments": max(
                1,
                int(
                    _number(
                        _pick(
                            options,
                            "cap_segments",
                            "cap_subdivisions",
                            default=4,
                        ),
                        4,
                    )
                ),
            ),
            "lod": _number(
                _pick(options, "lod", "lod_ratio", "downsample", default=1.0), 1.0
            ),
            "default_width": max(
                0.0,
                _number(
                    _pick(
                        options,
                        "width",
                        "default_width",
                        "base_width",
                        default=1.0,
                    ),
                    1.0,
                ),
            ),
            "up": up,
            "miter_limit": max(
                1.0,
                _number(
                    _pick(options, "miter_limit", "max_miter", default=4.0), 4.0
                ),
            ),
            "dedupe_epsilon": max(1e-15, dedupe_epsilon),
            "detect_intersections": bool(
                _pick(
                    options,
                    "detect_intersections",
                    "self_intersection",
                    default=True,
                )
            ),
        }

    @staticmethod
    def _source_value(source, index, default, total=None):
        if source is None:
            return default
        if isinstance(source, (int, float)):
            return _number(source, default)
        try:
            count = len(source)
        except TypeError:
            return source
        if count == 0:
            return default
        if total is None or count == total or count == 1:
            return source[min(index, count - 1)]
        position = index * (count - 1) / max(1, total - 1)
        lower = min(count - 1, int(math.floor(position)))
        upper = min(count - 1, lower + 1)
        fraction = position - lower
        low = _number(source[lower], default)
        high = _number(source[upper], default)
        return low + (high - low) * fraction

    @staticmethod
    def _source_color(source, index, default, total=None):
        if source is None:
            return default
        if isinstance(source, (int, float)):
            return (_number(source, 0.0),)
        try:
            count = len(source)
        except TypeError:
            return default
        if count == 0:
            return default
        try:
            scalar_sequence = all(
                isinstance(value, (int, float)) for value in source
            )
        except TypeError:
            scalar_sequence = False
        if scalar_sequence and count in (3, 4):
            values = source
        else:
            if total is not None and count not in (1, total):
                position = index * (count - 1) / max(1, total - 1)
                lower = min(count - 1, int(math.floor(position)))
                upper = min(count - 1, lower + 1)
                fraction = position - lower
                first = source[lower]
                second = source[upper]
                if isinstance(first, (int, float)):
                    first = (first,)
                if isinstance(second, (int, float)):
                    second = (second,)
                width = min(len(first), len(second))
                values = tuple(
                    _number(first[channel], 0.0)
                    + (
                        _number(second[channel], 0.0)
                        - _number(first[channel], 0.0)
                    )
                    * fraction
                    for channel in range(width)
                )
            else:
                values = source[min(index, count - 1)]
            if isinstance(values, (int, float)):
                values = (values,)
        try:
            return tuple(_number(value, 0.0) for value in values)
        except TypeError:
            return default

    def _prepare_input(self, points, widths, colors, times, cfg):
        raw = []
        dimension = None
        try:
            total_samples = len(points)
        except TypeError:
            points = list(points)
            total_samples = len(points)

        for index, item in enumerate(points):
            item_width = None
            item_color = None
            item_time = None

            if isinstance(item, Mapping):
                coords = item.get("point", item.get("position"))
                item_time = item.get("time", item.get("t"))
                item_width = item.get("width")
                item_color = item.get("color", item.get("colour"))
                if coords is None and all(axis in item for axis in ("x", "y")):
                    coords = (
                        item.get("x"),
                        item.get("y"),
                        item.get("z", 0.0),
                    )
            else:
                coords = item

            if coords is None:
                continue
            try:
                values = [_number(value, float("nan")) for value in coords]
            except TypeError:
                continue
            if len(values) < 2 or not all(math.isfinite(value) for value in values):
                continue

            if dimension is None:
                dimension = max(2, len(values))
            if len(values) < dimension:
                values.extend([0.0] * (dimension - len(values)))
            else:
                values = values[:dimension]

            time_value = item_time
            if time_value is None:
                time_value = self._source_value(
                    times, index, None, total_samples
                )
            time_value = _optional_number(time_value)
            if time_value is None:
                time_value = float(index)

            width_value = item_width
            if width_value is None:
                width_value = self._source_value(
                    widths, index, cfg["default_width"], total_samples
                )
            width_value = max(0.0, _number(width_value, cfg["default_width"]))

            color_value = item_color
            if color_value is None:
                color_value = self._source_color(
                    colors, index, (1.0, 1.0, 1.0, 1.0), total_samples
                )
            elif isinstance(color_value, (int, float)):
                color_value = (_number(color_value, 0.0),)
            else:
                try:
                    color_value = tuple(_number(value, 0.0) for value in color_value)
                except TypeError:
                    color_value = (1.0, 1.0, 1.0, 1.0)

            raw.append(
                {
                    "point": tuple(values),
                    "time": time_value,
                    "width": width_value,
                    "color": color_value,
                    "source_index": index,
                }
            )

        if dimension is None:
            dimension = 2

        cumulative = 0.0
        previous = None
        for sample in raw:
            if previous is not None:
                cumulative += _distance(previous, sample["point"])
            sample["source_arc"] = cumulative
            previous = sample["point"]
        return raw, dimension

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def _sample(self, raw, cfg, closed=False):
        groups = []
        current = []
        teleports = 0
        corner_splits = 0
        skipped = 0
        epsilon = cfg["dedupe_epsilon"]

        def flush():
            nonlocal current
            if current:
                groups.append(current)
            current = []

        for sample in raw:
            if not current:
                current = [sample]
                continue

            last = current[-1]
            distance = _distance(last["point"], sample["point"])
            if distance <= epsilon:
                skipped += 1
                continue

            delta_time = sample["time"] - last["time"]
            if delta_time < -epsilon:
                flush()
                current = [sample]
                continue

            if distance > cfg["teleport_distance"]:
                flush()
                current = [sample]
                teleports += 1
                continue

            max_time_gap = cfg["max_time_gap"]
            if max_time_gap is not None and delta_time > max_time_gap:
                flush()
                current = [sample]
                teleports += 1
                continue

            distance_ok = distance + epsilon >= cfg["min_distance"]
            min_time = cfg["min_time"]
            time_ok = (
                min_time is not None
                and delta_time is not None
                and delta_time + epsilon >= min_time
            )
            if not distance_ok and not time_ok:
                skipped += 1
                continue

            if len(current) >= 2 and not closed:
                previous = current[-2]["point"]
                previous_tangent = _normalize(
                    _sub(last["point"], previous), (1.0,) * len(last["point"])
                )
                next_tangent = _normalize(
                    _sub(sample["point"], last["point"]),
                    (1.0,) * len(sample["point"]),
                )
                cosine = max(-1.0, min(1.0, _dot(previous_tangent, next_tangent)))
                angle = math.degrees(math.acos(cosine))
                if angle > cfg["max_angle"] + 1e-9:
                    bridge = last
                    flush()
                    current = [bridge, sample]
                    corner_splits += 1
                    continue

            current.append(sample)

        flush()
        if len(groups) == 1 and len(groups[0]) < 2:
            groups = []
        return groups, {
            "skipped": skipped,
            "teleports": teleports,
            "corner_splits": corner_splits,
        }

    @staticmethod
    def _group_length(group, closed=False):
        if len(group) < 2:
            return 0.0
        length = sum(
            _distance(group[index - 1]["point"], group[index]["point"])
            for index in range(1, len(group))
        )
        if closed and len(group) >= 2:
            length += _distance(group[-1]["point"], group[0]["point"])
        return length

    @staticmethod
    def _total_points(groups):
        return sum(len(group) for group in groups)

    def _enforce_limits(self, groups, closed, cfg):
        groups = [list(group) for group in groups if group]

        # A duplicate closing sample is not a second logical sample.
        if closed and groups and len(groups) == 1:
            group = groups[0]
            if len(group) >= 2 and _distance(
                group[0]["point"], group[-1]["point"]
            ) <= cfg["dedupe_epsilon"]:
                group.pop()
                if not group:
                    groups = []

        max_points = cfg["max_points"]
        if max_points is not None:
            while groups and self._total_points(groups) > max_points:
                if len(groups) > 1:
                    groups.pop(0)
                    continue
                group = groups[0]
                excess = len(group) - max_points
                if excess >= len(group):
                    groups = []
                    break
                del group[:excess]
                break

        max_length = cfg["max_length"]
        if max_length is not None:
            def total_length():
                return sum(
                    self._group_length(group, closed and len(groups) == 1)
                    for group in groups
                )

            while groups and total_length() > max_length:
                if len(groups) > 1:
                    groups.pop(0)
                    continue
                group = groups[0]
                while (
                    len(group) > 1
                    and self._group_length(group, closed) > max_length
                ):
                    group.pop(0)
                if len(group) < 2:
                    groups = []
                break

        max_duration = cfg["max_duration"]
        if max_duration is not None and groups:
            while True:
                all_samples = [sample for group in groups for sample in group]
                if not all_samples:
                    groups = []
                    break
                duration = max(sample["time"] for sample in all_samples) - min(
                    sample["time"] for sample in all_samples
                )
                if duration <= max_duration:
                    break
                if len(groups) > 1:
                    groups.pop(0)
                    continue
                group = groups[0]
                while len(group) > 1:
                    duration = group[-1]["time"] - group[0]["time"]
                    if duration <= max_duration:
                        break
                    group.pop(0)
                if len(group) < 2:
                    groups = []
                break

        groups = [group for group in groups if group]
        if closed and len(groups) != 1:
            closed = False
        return groups, closed

    # ------------------------------------------------------------------
    # Adaptive LOD
    # ------------------------------------------------------------------
    def _segment_lod(self, group, factor):
        if factor >= 1.0 or len(group) <= 2:
            return list(group)

        target = max(2, int(round(len(group) * max(0.0, factor))))
        if target >= len(group):
            return list(group)

        count = len(group)
        arcs = [0.0]
        for index in range(1, count):
            arcs.append(
                arcs[-1]
                + _distance(group[index - 1]["point"], group[index]["point"])
            )

        keep = {0, count - 1}
        importance = [0.0] * count

        # Curvature is the strongest shape signal: a slow-motion reduction must
        # not round away the fastest part of a swing.
        tangents = []
        for index in range(1, count):
            tangents.append(
                _normalize(
                    _sub(group[index]["point"], group[index - 1]["point"]),
                    (1.0,) * len(group[index]["point"]),
                )
            )
        for index in range(1, count - 1):
            cosine = max(-1.0, min(1.0, _dot(tangents[index - 1], tangents[index])))
            importance[index] += (1.0 - cosine) * 2.0

        extrema = set()

        def mark_extrema(values):
            for index in range(1, count - 1):
                before = values[index] - values[index - 1]
                after = values[index + 1] - values[index]
                if before * after < -1e-12:
                    extrema.add(index)
                    importance[index] += 0.6

        dimension = len(group[0]["point"])
        for axis in range(dimension):
            mark_extrema([sample["point"][axis] for sample in group])
        mark_extrema([sample["width"] for sample in group])
        color_dimension = min(
            (len(sample["color"]) for sample in group), default=0
        )
        for channel in range(color_dimension):
            mark_extrema([sample["color"][channel] for sample in group])

        for index in range(1, count - 1):
            if importance[index] >= max(
                importance[index - 1], importance[index + 1], 1e-9
            ):
                importance[index] += 0.25

        candidates = [index for index in extrema if index not in keep]
        candidates.sort(key=lambda index: (-importance[index], index))
        for index in candidates:
            if len(keep) >= target:
                break
            keep.add(index)

        # Fill remaining slots with farthest-point sampling over arc length so
        # the retained points stay evenly distributed and endpoints survive.
        while len(keep) < target:
            best_index = None
            best_key = None
            for index in range(1, count - 1):
                if index in keep:
                    continue
                nearest = min(abs(arcs[index] - arcs[kept]) for kept in keep)
                key = (nearest, importance[index], -index)
                if best_key is None or key > best_key:
                    best_key = key
                    best_index = index
            if best_index is None:
                break
            keep.add(best_index)

        return [group[index] for index in sorted(keep)]

    def _apply_lod(self, groups, cfg):
        factor = cfg["lod"]
        if factor <= 0.0:
            factor = 0.0
        if factor >= 1.0:
            return groups
        return [self._segment_lod(group, factor) for group in groups]

    # ------------------------------------------------------------------
    # Self-intersection detection
    # ------------------------------------------------------------------
    @staticmethod
    def _segment_conflict(a, b, c, d, epsilon=1e-10):
        """Return the crossing point for two 2D segments, or ``None``."""
        if len(a) < 2:
            return None
        a = a[:2]
        b = b[:2]
        c = c[:2]
        d = d[:2]
        r = _sub(b, a)
        s = _sub(d, c)
        denominator = _cross2(r, s)
        offset = _sub(c, a)

        if abs(denominator) <= epsilon:
            if abs(_cross2(offset, r)) > epsilon:
                return None
            rr = _dot(r, r)
            if rr <= epsilon:
                return None
            t0 = _dot(offset, r) / rr
            t1 = _dot(_sub(d, a), r) / rr
            low = max(0.0, min(t0, t1))
            high = min(1.0, max(t0, t1))
            if high - low <= 1e-7:
                return None
            return _lerp(a, b, (low + high) * 0.5)

        t = _cross2(offset, s) / denominator
        u = _cross2(offset, r) / denominator
        if epsilon < t < 1.0 - epsilon and epsilon < u < 1.0 - epsilon:
            return _lerp(a, b, t)
        return None

    def _detect_and_split(self, groups, closed, cfg):
        if not cfg["detect_intersections"] or len(groups) < 1:
            return groups, closed, []

        edges = []
        for group_index, group in enumerate(groups):
            if len(group) < 2:
                continue
            edge_count = len(group) if closed and len(groups) == 1 else len(group) - 1
            for edge_index in range(edge_count):
                next_index = (edge_index + 1) % len(group)
                edges.append(
                    (
                        group_index,
                        edge_index,
                        group[edge_index]["point"],
                        group[next_index]["point"],
                    )
                )

        intersections = []
        local_breaks = {index: set() for index in range(len(groups))}

        for first in range(len(edges)):
            group_a, edge_a, a, b = edges[first]
            for second in range(first + 1, len(edges)):
                group_b, edge_b, c, d = edges[second]
                same_group = group_a == group_b
                if same_group:
                    if closed and len(groups) == 1:
                        if abs(edge_a - edge_b) <= 1:
                            continue
                        if {edge_a, edge_b} == {0, len(groups[0]) - 1}:
                            continue
                    elif abs(edge_a - edge_b) <= 1:
                        continue
                point = self._segment_conflict(a, b, c, d)
                if point is None:
                    continue
                intersections.append((group_a, edge_a, group_b, edge_b, point))
                if same_group:
                    group = groups[group_a]
                    local_breaks[group_a].add((edge_a + 1) % len(group))
                    local_breaks[group_b].add((edge_b + 1) % len(group))

        if not intersections:
            return groups, closed, []

        split_groups = []
        for group_index, group in enumerate(groups):
            breaks = local_breaks[group_index]
            if not breaks or len(group) < 3:
                split_groups.append(group)
                continue

            if closed and len(groups) == 1:
                cuts = sorted(set(breaks))
                cyclic_chunks = []
                for position, start in enumerate(cuts):
                    end = cuts[(position + 1) % len(cuts)]
                    if end <= start:
                        end += len(group)
                    chunk = [
                        group[index % len(group)]
                        for index in range(start, end + 1)
                    ]
                    chunk = _dedupe_consecutive(chunk)
                    if len(chunk) >= 1:
                        cyclic_chunks.append(chunk)
                if cyclic_chunks:
                    split_groups.extend(cyclic_chunks)
                else:
                    split_groups.append(group)
                closed = False
                continue

            cuts = sorted(index for index in breaks if 0 < index < len(group) - 1)
            if not cuts:
                split_groups.append(group)
                continue
            bounds = [0] + cuts + [len(group) - 1]
            for start, end in zip(bounds, bounds[1:]):
                chunk = group[start : end + 1]
                if chunk:
                    split_groups.append(chunk)

        split_groups = [group for group in split_groups if group]
        if closed and len(split_groups) != 1:
            closed = False

        return split_groups, closed, intersections

    # ------------------------------------------------------------------
    # Taper and mesh construction
    # ------------------------------------------------------------------
    def _apply_taper(self, groups, cfg):
        if not cfg["taper"]:
            return
        for group in groups:
            length = self._group_length(group, False)
            if length <= _EPS:
                continue
            if cfg["taper_length"] is None:
                taper_length = 0.2 * length
            else:
                taper_length = min(length, max(0.0, cfg["taper_length"]))
            if taper_length <= _EPS:
                continue
            end_scale = cfg["end_width_scale"]
            distance_to_end = 0.0
            for index in range(len(group) - 1, -1, -1):
                if index < len(group) - 1:
                    distance_to_end += _distance(
                        group[index]["point"], group[index + 1]["point"]
                    )
                if distance_to_end <= taper_length:
                    factor = end_scale + (1.0 - end_scale) * (
                        distance_to_end / taper_length
                    )
                    group[index]["width"] = min(
                        group[index]["width"], group[index]["width"] * factor
                    )

    def _tangents(self, group, closed):
        count = len(group)
        tangents = []
        for index in range(count):
            if closed:
                previous = group[(index - 1) % count]["point"]
                following = group[(index + 1) % count]["point"]
            elif index == 0:
                previous = group[index]["point"]
                following = group[index + 1]["point"]
            elif index == count - 1:
                previous = group[index - 1]["point"]
                following = group[index]["point"]
            else:
                previous = group[index - 1]["point"]
                following = group[index + 1]["point"]
            tangent = _normalize(
                _sub(following, previous), (1.0,) * len(group[index]["point"])
            )
            tangents.append(tangent)
        return tangents

    def _side_vector(self, tangent, dimension, cfg):
        if dimension == 2:
            return (-tangent[1], tangent[0])

        up = tuple(
            (cfg["up"][index] if index < len(cfg["up"]) else 0.0)
            for index in range(3)
        )
        tangent3 = tuple(
            tangent[index] if index < len(tangent) else 0.0 for index in range(3)
        )
        side = _cross3(tangent3, up)
        if _length(side) <= 1e-9:
            fallback = (
                (1.0, 0.0, 0.0)
                if abs(tangent3[0]) < 0.9
                else (0.0, 1.0, 0.0)
            )
            side = _cross3(tangent3, fallback)
        side = _normalize(side, (0.0, 0.0, 0.0))
        if dimension > 3:
            side = tuple(side) + (0.0,) * (dimension - 3)
        return side

    def _ring_sides(self, group, closed, cfg):
        count = len(group)
        dimension = len(group[0]["point"])
        tangents = self._tangents(group, closed)
        base_normals = [
            self._side_vector(tangent, dimension, cfg) for tangent in tangents
        ]
        sides = []

        for index in range(count):
            if not closed and index == 0:
                sides.append(base_normals[index])
                continue
            if not closed and index == count - 1:
                sides.append(base_normals[index])
                continue

            previous_index = (index - 1) % count
            next_index = (index + 1) % count
            previous_normal = base_normals[previous_index]
            next_normal = base_normals[next_index]
            miter = _add(previous_normal, next_normal)
            miter_normal = _normalize(miter)
            if miter_normal is None:
                sides.append(next_normal)
                continue

            cosine = _dot(miter_normal, previous_normal)
            if abs(cosine) <= 1e-9:
                sides.append(next_normal)
                continue
            scale = 1.0 / cosine
            if scale < 0.0:
                sides.append(next_normal)
                continue
            scale = min(scale, cfg["miter_limit"])
            sides.append(_mul(miter_normal, scale))
        return sides

    @staticmethod
    def _triangle_area(a, b, c):
        ab = _sub(b, a)
        ac = _sub(c, a)
        if len(a) >= 3:
            return 0.5 * _length(_cross3(ab[:3], ac[:3]))
        return 0.5 * abs(_cross2(ab[:2], ac[:2]))

    def _build_mesh(self, groups, closed, dimension, cfg):
        vertices = []
        indices = []
        uvs = []
        vertex_segment_ids = []
        vertex_colors = []
        caps = 0
        segments = len(groups)

        segment_lengths = [
            self._group_length(group, closed and index == 0)
            for index, group in enumerate(groups)
        ]
        total_arc = sum(segment_lengths)
        base_arc = 0.0

        for group_index, group in enumerate(groups):
            if len(group) < 2:
                base_arc += segment_lengths[group_index]
                continue

            is_closed = closed and group_index == 0 and len(groups) == 1
            sides = self._ring_sides(group, is_closed, cfg)
            group_length = segment_lengths[group_index]

            ring_samples = list(group)
            ring_sides = list(sides)
            ring_arcs = [0.0]
            for index in range(1, len(group)):
                ring_arcs.append(
                    ring_arcs[-1]
                    + _distance(group[index - 1]["point"], group[index]["point"])
                )
            if is_closed:
                ring_samples.append(group[0])
                ring_sides.append(sides[0])
                ring_arcs.append(group_length)

            ring_start = len(vertices) // 2
            for ring_index, sample in enumerate(ring_samples):
                point = sample["point"]
                side = ring_sides[ring_index]
                width = max(0.0, sample["width"]) * 0.5
                left = _add(point, _mul(side, width))
                right = _sub(point, _mul(side, width))
                vertices.append(tuple(left))
                vertices.append(tuple(right))
                local_arc = ring_arcs[ring_index]
                u = (
                    min(1.0, max(0.0, (base_arc + local_arc) / total_arc))
                    if total_arc > _EPS
                    else 0.0
                )
                uvs.append((u, 0.0))
                uvs.append((u, 1.0))
                vertex_segment_ids.extend((group_index, group_index))
                vertex_colors.extend((sample["color"], sample["color"]))

            for ring_index in range(len(ring_samples) - 1):
                left_a = ring_start + ring_index * 2
                right_a = left_a + 1
                left_b = left_a + 2
                right_b = left_a + 3
                for triangle in (
                    (left_a, right_a, right_b),
                    (left_a, right_b, left_b),
                ):
                    if self._triangle_area(
                        vertices[triangle[0]],
                        vertices[triangle[1]],
                        vertices[triangle[2]],
                    ) > 1e-12:
                        indices.extend(triangle)

            if cfg["caps"] and not is_closed:
                first = group[0]
                last = group[-1]
                first_tangent = _normalize(
                    _sub(group[1]["point"], first["point"]),
                    (1.0,) * dimension,
                )
                last_tangent = _normalize(
                    _sub(last["point"], group[-2]["point"]),
                    (1.0,) * dimension,
                )
                uv_start = (
                    min(1.0, max(0.0, base_arc / total_arc))
                    if total_arc > _EPS
                    else 0.0
                )
                uv_end = (
                    min(1.0, max(0.0, (base_arc + group_length) / total_arc))
                    if total_arc > _EPS
                    else 0.0
                )
                if self._add_cap(
                    first["point"],
                    sides[0],
                    _mul(first_tangent, -1.0),
                    first["width"] * 0.5,
                    ring_start,
                    ring_start + 1,
                    uv_start,
                    group_index,
                    first["color"],
                    cfg,
                    vertices,
                    indices,
                    uvs,
                    vertex_segment_ids,
                    vertex_colors,
                ):
                    caps += 1

                last_ring = ring_start + (len(ring_samples) - 1) * 2
                if self._add_cap(
                    last["point"],
                    sides[-1],
                    last_tangent,
                    last["width"] * 0.5,
                    last_ring,
                    last_ring + 1,
                    uv_end,
                    group_index,
                    last["color"],
                    cfg,
                    vertices,
                    indices,
                    uvs,
                    vertex_segment_ids,
                    vertex_colors,
                ):
                    caps += 1

            base_arc += group_length

        return {
            "vertices": vertices,
            "indices": indices,
            "uvs": uvs,
            "caps": caps,
            "segments": segments,
            "vertex_segment_ids": vertex_segment_ids,
            "vertex_colors": vertex_colors,
            "total_length": total_arc,
        }

    def _add_cap(
        self,
        center,
        side,
        backward,
        half_width,
        left_index,
        right_index,
        u,
        segment_id,
        color,
        cfg,
        vertices,
        indices,
        uvs,
        vertex_segment_ids,
        vertex_colors,
    ):
        if half_width <= 1e-9:
            return False

        center_index = len(vertices)
        vertices.append(tuple(center))
        uvs.append((u, 0.5))
        vertex_segment_ids.append(segment_id)
        vertex_colors.append(color)

        arc = [left_index]
        subdivisions = cfg["cap_segments"]
        for step in range(1, subdivisions):
            angle = math.pi * step / subdivisions
            offset = _add(
                _mul(side, math.cos(angle)),
                _mul(backward, math.sin(angle)),
            )
            vertex_index = len(vertices)
            vertices.append(tuple(_add(center, _mul(offset, half_width))))
            uvs.append((u, step / subdivisions))
            vertex_segment_ids.append(segment_id)
            vertex_colors.append(color)
            arc.append(vertex_index)
        arc.append(right_index)

        for first, second in zip(arc, arc[1:]):
            if self._triangle_area(
                vertices[center_index], vertices[first], vertices[second]
            ) > 1e-12:
                indices.extend((center_index, first, second))
        return True

    @staticmethod
    def _bbox(vertices, dimension):
        if not vertices:
            zero = (0.0,) * max(2, dimension)
            return {"min": zero, "max": zero}
        minimum = tuple(
            min(vertex[axis] for vertex in vertices) for axis in range(dimension)
        )
        maximum = tuple(
            max(vertex[axis] for vertex in vertices) for axis in range(dimension)
        )
        return {"min": minimum, "max": maximum}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def build(
        self, points, widths=None, colors=None, closed=False, times=None, **over
    ):
        if times is None:
            times = over.pop("times", None)
        if times is None:
            times = over.pop("time", None)
        cfg = self._config(over)

        raw, dimension = self._prepare_input(points, widths, colors, times, cfg)
        closed = bool(closed)
        groups, sampling = self._sample(raw, cfg, closed)

        groups, closed = self._enforce_limits(groups, closed, cfg)
        groups = self._apply_lod(groups, cfg)
        groups, closed, intersections = self._detect_and_split(groups, closed, cfg)
        groups, closed = self._enforce_limits(groups, closed, cfg)
        self._apply_taper(groups, cfg)

        mesh = self._build_mesh(groups, closed, dimension, cfg)
        samples = [sample for group in groups for sample in group]
        segment_ids = [
            group_index
            for group_index, group in enumerate(groups)
            for _ in group
        ]

        bbox = self._bbox(mesh["vertices"], dimension)
        vertices = mesh["vertices"] if mesh["vertices"] else 0

        return {
            "vertices": vertices,
            "indices": mesh["indices"],
            "uvs": mesh["uvs"],
            "segments": mesh["segments"],
            "segment_ids": segment_ids,
            "vertex_segment_ids": mesh["vertex_segment_ids"],
            "sample_count": len(samples),
            "points": [sample["point"] for sample in samples],
            "widths": [sample["width"] for sample in samples],
            "colors": [sample["color"] for sample in samples],
            "vertex_colors": mesh["vertex_colors"],
            "closed": bool(closed),
            "caps": mesh["caps"],
            "bbox": bbox,
            "intersections": intersections,
            "intersection_count": len(intersections),
            "total_length": mesh["total_length"],
            "teleports": sampling["teleports"],
            "corner_splits": sampling["corner_splits"],
            "skipped_points": sampling["skipped"],
        }
