import math


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalize(v):
    length = math.sqrt(_dot(v, v))
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _clip_polygon_against_rect(points, rect):
    x0, y0, x1, y1 = rect

    def clip_edge(poly, inside, intersect):
        if not poly:
            return []
        out = []
        prev = poly[-1]
        for curr in poly:
            if inside(curr):
                if not inside(prev):
                    out.append(intersect(prev, curr))
                out.append(curr)
            elif inside(prev):
                out.append(intersect(prev, curr))
            prev = curr
        return out

    def axis_clip(poly, axis, bound, keep_less):
        def inside(p):
            return p[axis] <= bound if keep_less else p[axis] >= bound

        def intersect(a, b):
            da = a[axis] - bound
            db = b[axis] - bound
            t = da / (da - db) if da != db else 0.0
            other = 1 - axis
            point = [0.0, 0.0]
            point[axis] = bound
            point[other] = a[other] + t * (b[other] - a[other])
            return (point[0], point[1])

        return clip_edge(poly, inside, intersect)

    poly = [(float(p[0]), float(p[1])) for p in points]
    poly = axis_clip(poly, 0, x0, keep_less=False)
    poly = axis_clip(poly, 0, x1, keep_less=True)
    poly = axis_clip(poly, 1, y0, keep_less=False)
    poly = axis_clip(poly, 1, y1, keep_less=True)
    return poly


def _polygon_area(poly):
    if len(poly) < 3:
        return 0.0
    total = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        total += p[0] * q[1] - q[0] * p[1]
    return abs(total) / 2.0


class DecalBakePlanner:
    ATLAS_SIZE = 256
    PATCH_WORLD_SIZE = 2.0
    REFERENCE_DECAL_SIZE = 1.0
    RESAMPLE_RATIO = 4.0

    def __init__(self, max_angle=60.0, padding=4, max_tasks=64):
        self.max_angle = float(max_angle)
        self.padding = int(padding)
        self.max_tasks = int(max_tasks)

    def plan(self, decals, patches):
        decals = [dict(d) for d in (decals or [])]
        patches = [dict(p) for p in (patches or [])]
        warnings = []
        tasks = []

        ordered = sorted(
            decals,
            key=lambda d: (
                -d.get("priority", 0),
                d.get("created", 0),
                str(d.get("id", "")),
            ),
        )

        pad_uv = self.padding / float(self.ATLAS_SIZE)

        for decal in ordered:
            did = decal.get("id", "")
            decal_normal = _normalize(decal.get("normal", (0.0, 1.0, 0.0)))
            size = float(decal.get("size", 1.0))
            resampled = not (
                1.0 / self.RESAMPLE_RATIO
                <= size / self.REFERENCE_DECAL_SIZE
                <= self.RESAMPLE_RATIO
            )
            effective_size = self.REFERENCE_DECAL_SIZE if resampled else size

            for patch in patches:
                pid = patch.get("id", "")
                patch_normal_raw = tuple(patch.get("normal", (0.0, 1.0, 0.0)))
                patch_normal = _normalize(patch_normal_raw)

                cos_angle = _dot(decal_normal, patch_normal)
                if cos_angle <= 0.0:
                    warnings.append("backface-culled:%s:%s" % (did, pid))
                    continue
                angle = math.degrees(math.acos(min(1.0, cos_angle)))
                if angle >= self.max_angle:
                    warnings.append("angle-culled:%s:%s" % (did, pid))
                    continue

                u0, v0, u1, v1 = [float(c) for c in patch.get("uv", (0.0, 0.0, 1.0, 1.0))]
                extent_u = u1 - u0
                extent_v = v1 - v0
                center_u = (u0 + u1) / 2.0
                center_v = (v0 + v1) / 2.0
                half_u = 0.5 * effective_size * extent_u / self.PATCH_WORLD_SIZE
                half_v = 0.5 * effective_size * extent_v / self.PATCH_WORLD_SIZE
                cover = (
                    center_u - half_u,
                    center_v - half_v,
                    center_u + half_u,
                    center_v + half_v,
                )

                writable = (
                    max(u0 + pad_uv, 0.0),
                    max(v0 + pad_uv, 0.0),
                    min(u1 - pad_uv, 1.0),
                    min(v1 - pad_uv, 1.0),
                )
                if (
                    writable[0] >= writable[2]
                    or writable[1] >= writable[3]
                    or cover[0] < writable[0]
                    or cover[1] < writable[1]
                    or cover[2] > writable[2]
                    or cover[3] > writable[3]
                ):
                    warnings.append("out-of-bounds:%s:%s" % (did, pid))
                    continue

                rect = (
                    round(cover[0], 6),
                    round(cover[1], 6),
                    round(cover[2], 6),
                    round(cover[3], 6),
                )
                local_rect = (
                    (cover[0] - u0) / extent_u if extent_u else 0.0,
                    (cover[1] - v0) / extent_v if extent_v else 0.0,
                    (cover[2] - u0) / extent_u if extent_u else 0.0,
                    (cover[3] - v0) / extent_v if extent_v else 0.0,
                )

                clip = []
                area = 0.0
                for tri in patch.get("triangles", []):
                    poly = _clip_polygon_against_rect(tri, local_rect)
                    if len(poly) >= 3:
                        clip.append([(round(x, 6), round(y, 6)) for x, y in poly])
                        area += _polygon_area(poly)

                angle_fade = 1.0 - angle / self.max_angle
                fade = round(max(0.0, min(1.0, angle_fade)), 6)

                tasks.append(
                    {
                        "id": did,
                        "patch": pid,
                        "normal": patch_normal_raw,
                        "rect": rect,
                        "uv": (u0, v0, u1, v1),
                        "uv_offset": (u0, v0),
                        "clip": clip,
                        "area": round(area, 6),
                        "blend": fade,
                        "fade": fade,
                        "padding": self.padding,
                        "resampled": resampled,
                        "priority": decal.get("priority", 0),
                        "created": decal.get("created", 0),
                    }
                )

        if len(tasks) > self.max_tasks:
            warnings.append("task-limit:%d" % self.max_tasks)
            tasks = tasks[: self.max_tasks]

        return {"tasks": tasks, "warnings": warnings}
