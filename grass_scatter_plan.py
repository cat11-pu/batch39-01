import hashlib
import math

_TWO_PI = math.pi * 2.0


def _hash01(seed, ix, iy, salt):
    key = "{0}:{1}:{2}:{3}".format(seed, ix, iy, salt).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


class GrassScatterPlan:
    def __init__(self, seed=0, spacing=1.0, max_instances=10000, **over):
        self.seed = seed
        self.spacing = spacing
        self.max_instances = max_instances
        self.over = dict(over)

    def _option(self, over, name, default):
        if name in over:
            return over[name]
        return self.over.get(name, default)

    def build(self, region, density, blocked=(), slope=None, height=None, **over):
        seed = self._option(over, "seed", self.seed)
        spacing = float(self._option(over, "spacing", self.spacing))
        if spacing <= 0:
            spacing = 1.0
        max_instances = int(self._option(over, "max_instances", self.max_instances))
        max_total = self._option(over, "max_total_instances", None)
        max_slope = self._option(over, "max_slope", None)
        min_height = self._option(over, "min_height", None)
        max_height = self._option(over, "max_height", None)
        lod = float(self._option(over, "lod", 1.0))
        sway = float(self._option(over, "sway", 0.0))
        slope_fn = slope if slope is not None else self.over.get("slope")
        height_fn = height if height is not None else self.over.get("height")
        blocked = blocked or self.over.get("blocked", ()) or ()

        x0 = float(region["x"])
        y0 = float(region["y"])
        x1 = x0 + float(region["w"])
        y1 = y0 + float(region["h"])

        keep_prob = max(0.0, min(1.0, float(density) * lod))

        grid = {}
        accepted = []
        i0 = math.floor(x0 / spacing)
        i1 = math.floor(x1 / spacing)
        j0 = math.floor(y0 / spacing)
        j1 = math.floor(y1 / spacing)
        for ix in range(i0, i1 + 1):
            for iy in range(j0, j1 + 1):
                if _hash01(seed, ix, iy, "density") >= keep_prob:
                    continue
                px = (ix + _hash01(seed, ix, iy, "jitter_x")) * spacing
                py = (iy + _hash01(seed, ix, iy, "jitter_y")) * spacing
                if not (x0 <= px < x1 and y0 <= py < y1):
                    continue
                if slope_fn is not None and max_slope is not None:
                    if slope_fn(px, py) > max_slope:
                        continue
                if height_fn is not None:
                    h = height_fn(px, py)
                    if min_height is not None and h < min_height:
                        continue
                    if max_height is not None and h > max_height:
                        continue
                if any(
                    b["x"] <= px < b["x"] + b["w"] and b["y"] <= py < b["y"] + b["h"]
                    for b in blocked
                ):
                    continue
                cx = int(math.floor(px / spacing))
                cy = int(math.floor(py / spacing))
                clear = True
                for nx in range(cx - 1, cx + 2):
                    if not clear:
                        break
                    for ny in range(cy - 1, cy + 2):
                        if not clear:
                            break
                        for qx, qy in grid.get((nx, ny), ()):
                            if (qx - px) ** 2 + (qy - py) ** 2 < spacing * spacing:
                                clear = False
                                break
                if not clear:
                    continue
                grid.setdefault((cx, cy), []).append((px, py))
                priority = _hash01(seed, ix, iy, "priority")
                accepted.append((priority, ix, iy, px, py))

        accepted.sort(key=lambda item: (item[0], item[1], item[2]))

        limit = max_instances
        if max_total is not None:
            limit = min(limit, int(max_total))
        limit = max(0, limit)
        truncated = len(accepted) > limit
        kept = accepted[:limit]

        chunk_w = float(region["w"]) or 1.0
        chunk_h = float(region["h"]) or 1.0
        instances = []
        for _, ix, iy, px, py in kept:
            instances.append(
                {
                    "x": px,
                    "y": py,
                    "rotation": _hash01(seed, ix, iy, "rotation") * _TWO_PI,
                    "scale": 0.8 + 0.4 * _hash01(seed, ix, iy, "scale"),
                    "wind": float(_hash01(seed, ix, iy, "wind") * _TWO_PI),
                    "chunk": (
                        int(math.floor(px / chunk_w)),
                        int(math.floor(py / chunk_h)),
                    ),
                }
            )

        return {
            "instances": instances,
            "bounds": (x0 - sway, y0 - sway, x1 + sway, y1 + sway),
            "grid_cells": len(grid),
            "truncated": truncated,
        }
