"""Adaptive screen-space flattening for line and cubic Bezier segments."""

import math


_NUMERIC_EPS = 1e-12


def _as_point(value):
    try:
        x, y = value[0], value[1]
    except (TypeError, IndexError, KeyError) as exc:
        raise ValueError("points must contain at least two coordinates") from exc
    x = float(x)
    y = float(y)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("point coordinates must be finite")
    return (x, y)


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _point_segment_distance(point, start, end):
    """Distance from a point to a finite segment."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _NUMERIC_EPS * _NUMERIC_EPS:
        return _distance(point, start)

    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    if projection <= 0.0:
        return _distance(point, start)
    if projection >= 1.0:
        return _distance(point, end)

    closest = (start[0] + projection * dx, start[1] + projection * dy)
    return _distance(point, closest)


def _normalize_matrix(matrix):
    """Return a six-value affine matrix as (a, b, c, d, e, f).

    Four-value matrices are interpreted as the linear part (a, b, c, d):
    x' = a*x + b*y and y' = c*x + d*y. Six-value matrices use the usual
    affine layout: x' = a*x + c*y + e and y' = b*x + d*y + f.
    """
    if matrix is None:
        return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    if isinstance(matrix, dict):
        try:
            values = (
                matrix["a"],
                matrix["b"],
                matrix["c"],
                matrix["d"],
                matrix.get("e", 0.0),
                matrix.get("f", 0.0),
            )
        except KeyError as exc:
            raise ValueError("matrix dictionary requires a, b, c and d") from exc
    else:
        try:
            values = tuple(matrix)
        except TypeError as exc:
            raise ValueError("matrix must be a sequence or None") from exc

        if len(values) == 2:
            try:
                (a, b), (c, d) = values
            except (TypeError, ValueError) as exc:
                raise ValueError("matrix must represent a 2D affine transform") from exc
            values = (a, b, c, d, 0.0, 0.0)
        elif len(values) == 3 and all(len(row) >= 3 for row in values):
            a, c, e = values[0][0], values[0][1], values[0][2]
            b, d, f = values[1][0], values[1][1], values[1][2]
            values = (a, b, c, d, e, f)
        elif len(values) == 9:
            a, c, e = values[0], values[1], values[2]
            b, d, f = values[3], values[4], values[5]
            values = (a, b, c, d, e, f)
        elif len(values) == 4:
            a, b, c, d = values
            values = (a, b, c, d, 0.0, 0.0)
        elif len(values) != 6:
            raise ValueError("matrix must have 4, 6 or 9 values")

    affine = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in affine):
        raise ValueError("matrix values must be finite")
    return affine


def _transform_point(point, matrix):
    a, b, c, d, e, f = matrix
    x, y = point
    return (a * x + c * y + e, b * x + d * y + f)


def _cubic_derivative_coefficients(control):
    """Coefficients of B'(t)/3 = a*t^2 + b*t + c."""
    p0, p1, p2, p3 = control
    ax = -p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]
    ay = -p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]
    bx = 2.0 * (p0[0] - 2.0 * p1[0] + p2[0])
    by = 2.0 * (p0[1] - 2.0 * p1[1] + p2[1])
    cx = p1[0] - p0[0]
    cy = p1[1] - p0[1]
    return (ax, bx, cx), (ay, by, cy)


def _quadratic_roots(a, b, c):
    scale = max(abs(a), abs(b), abs(c), 1.0)
    eps = _NUMERIC_EPS * scale
    if abs(a) <= eps:
        if abs(b) <= eps:
            return []
        return [-c / b]

    discriminant = b * b - 4.0 * a * c
    if discriminant < -eps:
        return []
    discriminant = max(0.0, discriminant)
    root = math.sqrt(discriminant)

    if b >= 0.0:
        q = -0.5 * (b + root)
    else:
        q = -0.5 * (b - root)

    roots = []
    if abs(a) > eps:
        roots.append(q / a)
    if abs(q) > eps:
        roots.append(c / q)
    elif abs(a) > eps:
        roots.append(-b / (2.0 * a))
    return roots


def _critical_parameters(control):
    """Find interior cusp and inflection parameters in screen space."""
    p0, p1, p2, p3 = control
    extent = max(
        _distance(p0, p1),
        _distance(p1, p2),
        _distance(p2, p3),
        _distance(p0, p3),
    )
    scale = max(1.0, extent)
    derivative_eps = 1e-8 * scale

    (ax, bx, cx), (ay, by, cy) = _cubic_derivative_coefficients(control)
    candidates = _quadratic_roots(ax, bx, cx) + _quadratic_roots(ay, by, cy)

    breakpoints = []
    for t in candidates:
        if not (1e-9 < t < 1.0 - 1e-9):
            continue
        dx = (ax * t + bx) * t + cx
        dy = (ay * t + by) * t + cy
        if math.hypot(dx, dy) <= derivative_eps:
            breakpoints.append(t)

    # The curvature numerator of a cubic is quadratic. Splitting at its
    # roots keeps an inflection point in the output even when it lies inside
    # a span that would otherwise be accepted in one step.
    ex = p0[0] - 2.0 * p1[0] + p2[0]
    ey = p0[1] - 2.0 * p1[1] + p2[1]
    dx = p3[0] - 3.0 * p2[0] + 3.0 * p1[0] - p0[0]
    dy = p3[1] - 3.0 * p2[1] + 3.0 * p1[1] - p0[1]

    c2 = _cross(ax, ay, ex, ey) + _cross(bx, by, dx, dy)
    c1 = _cross(bx, by, ex, ey) + _cross(cx, cy, dx, dy)
    c0 = _cross(cx, cy, ex, ey)
    if max(abs(c2), abs(c1), abs(c0)) > _NUMERIC_EPS * scale * scale:
        for t in _quadratic_roots(c2, c1, c0):
            if 1e-9 < t < 1.0 - 1e-9:
                breakpoints.append(t)

    breakpoints.sort()
    unique = []
    for t in breakpoints:
        if not unique or abs(t - unique[-1]) > 1e-7:
            unique.append(t)
    return unique


def _split_cubic(control, t):
    """Split a cubic at local parameter t using de Casteljau."""
    p0, p1, p2, p3 = control
    p01 = (
        p0[0] + (p1[0] - p0[0]) * t,
        p0[1] + (p1[1] - p0[1]) * t,
    )
    p12 = (
        p1[0] + (p2[0] - p1[0]) * t,
        p1[1] + (p2[1] - p1[1]) * t,
    )
    p23 = (
        p2[0] + (p3[0] - p2[0]) * t,
        p2[1] + (p3[1] - p2[1]) * t,
    )
    p012 = (
        p01[0] + (p12[0] - p01[0]) * t,
        p01[1] + (p12[1] - p01[1]) * t,
    )
    p123 = (
        p12[0] + (p23[0] - p12[0]) * t,
        p12[1] + (p23[1] - p12[1]) * t,
    )
    middle = (
        p012[0] + (p123[0] - p012[0]) * t,
        p012[1] + (p123[1] - p012[1]) * t,
    )
    left = (p0, p01, p012, middle)
    right = (middle, p123, p23, p3)
    return left, right


def _flatness(control):
    """Conservative chord error: max control distance to the chord segment."""
    p0, p1, p2, p3 = control
    return max(
        _point_segment_distance(p1, p0, p3),
        _point_segment_distance(p2, p0, p3),
    )


class BezierFlattenTolerance:
    def __init__(self, tolerance=0.5, max_depth=16, matrix=None, closed=False):
        try:
            tolerance = float(tolerance)
        except (TypeError, ValueError) as exc:
            raise ValueError("tolerance must be a positive finite number") from exc
        if not math.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError("tolerance must be a positive finite number")

        if isinstance(max_depth, bool) or not isinstance(max_depth, int):
            raise ValueError("max_depth must be a non-negative integer")
        if max_depth < 0:
            raise ValueError("max_depth must be a non-negative integer")

        self.tolerance = tolerance
        self.max_depth = max_depth
        self.matrix = _normalize_matrix(matrix)
        self.closed = bool(closed)

    def _pieces(self, control):
        pieces = [(control, 0.0, 1.0)]
        for breakpoint in _critical_parameters(control):
            for index, (piece_control, start, end) in enumerate(pieces):
                if start < breakpoint < end:
                    local_t = (breakpoint - start) / (end - start)
                    left, right = _split_cubic(piece_control, local_t)
                    pieces[index : index + 1] = [
                        (left, start, breakpoint),
                        (right, breakpoint, end),
                    ]
                    break
        return pieces

    def _flatten_cubic(self, control):
        vertices = []
        errors = []
        for piece_control, piece_start, piece_end in self._pieces(control):
            piece_vertices = [(piece_control[0], piece_start)]
            piece_errors = []
            stack = [(piece_control, piece_start, piece_end, 0)]

            while stack:
                current, start, end, depth = stack.pop()
                error = _flatness(current)
                if error <= self.tolerance or depth >= self.max_depth:
                    piece_vertices.append((current[3], end))
                    piece_errors.append(error)
                    continue

                middle_t = (start + end) * 0.5
                left, right = _split_cubic(current, 0.5)
                stack.append((right, middle_t, end, depth + 1))
                stack.append((left, start, middle_t, depth + 1))

            if not vertices:
                vertices = piece_vertices
                errors = piece_errors
            else:
                # Adjacent pieces share their split point.
                vertices.extend(piece_vertices[1:])
                errors.extend(piece_errors)

        return vertices, errors

    @staticmethod
    def _simplify(vertices, errors, merge_tolerance, closed):
        if not vertices:
            return [], [], []
        if len(vertices) == 1:
            point = vertices[0][0]
            return [point], [vertices[0][1]], []

        points = [vertices[0][0]]
        params = [vertices[0][1]]
        merged_errors = []
        pending_error = 0.0

        for index in range(1, len(vertices)):
            point, parameter = vertices[index]
            edge_error = errors[index - 1]
            if _distance(points[-1], point) <= merge_tolerance:
                pending_error = max(pending_error, edge_error)
                continue

            points.append(point)
            params.append(parameter)
            merged_errors.append(max(pending_error, edge_error))
            pending_error = 0.0

        if len(points) == 1:
            # A wholly degenerate segment still has two endpoints.
            points.append(vertices[-1][0])
            params.append(vertices[-1][1])
            merged_errors.append(max(errors) if errors else 0.0)
        elif pending_error > 0.0:
            merged_errors[-1] = max(merged_errors[-1], pending_error)

        if closed and len(points) >= 2:
            if _distance(points[-1], points[0]) <= merge_tolerance:
                points[-1] = points[0]

        return points, params, merged_errors

    def flatten(self, segments, matrix=None, closed=None):
        """Flatten segments into a screen-space polyline.

        Returns a dictionary with ``points``, their global normalized
        ``params`` and the conservative error estimate for each output edge
        in ``errors``. Input segment dictionaries are never modified.
        """
        if isinstance(segments, dict):
            segments = [segments]
        try:
            segments = list(segments)
        except TypeError as exc:
            raise ValueError("segments must be an iterable") from exc

        affine = self.matrix if matrix is None else _normalize_matrix(matrix)
        if closed is None:
            closed = self.closed
        segment_count = len(segments)
        if segment_count == 0:
            return {"points": [], "params": [], "errors": []}

        vertices = []
        errors = []

        for segment_index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise ValueError("each segment must be a dictionary")
            segment_type = segment.get("type")

            try:
                p0 = _transform_point(_as_point(segment["p0"]), affine)
                p1 = _transform_point(_as_point(segment["p1"]), affine)
            except KeyError as exc:
                raise ValueError("segment is missing p0 or p1") from exc

            base = float(segment_index)
            if segment_type == "line":
                segment_vertices = [
                    (p0, base / segment_count),
                    (p1, (base + 1.0) / segment_count),
                ]
                segment_errors = [0.0]
            elif segment_type == "cubic":
                try:
                    p2 = _transform_point(_as_point(segment["p2"]), affine)
                    p3 = _transform_point(_as_point(segment["p3"]), affine)
                except KeyError as exc:
                    raise ValueError("cubic segment is missing p2 or p3") from exc

                segment_vertices, segment_errors = self._flatten_cubic(
                    (p0, p1, p2, p3)
                )
                segment_vertices = [
                    (point, (base + local_t) / segment_count)
                    for point, local_t in segment_vertices
                ]
            else:
                raise ValueError("segment type must be 'line' or 'cubic'")

            if vertices:
                # The next segment starts where the previous one ended.
                errors.append(0.0)
            vertices.extend(segment_vertices)
            errors.extend(segment_errors)

        points, params, edge_errors = self._simplify(
            vertices, errors, self.tolerance, bool(closed)
        )
        return {"points": points, "params": params, "errors": edge_errors}
