class LodErrorSelect:
    def __init__(self, max_px=2.0, hysteresis=0.1):
        pass

    def select(self, model, camera):
        raise NotImplementedError

    def select_many(self, models, camera):
        raise NotImplementedError
import math


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _normalized(a):
    length = _norm(a)
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


class LodErrorSelect:
    """Screen-space-error based LOD selection.

    Selection rule: pick the coarsest level whose projected pixel error is
    within ``max_px``; on equal pixel error prefer the level with fewer
    triangles. A per-model hysteresis band keeps the current level while the
    error stays inside the buffered threshold, and a crossfade weight is
    reported whenever the level actually changes.
    """

    def __init__(self, max_px=2.0, hysteresis=0.1):
        self.max_px = float(max_px)
        self.hysteresis = float(hysteresis)
        self._state = {}

    def screen_space_error(self, geo_err, distance, fov, height):
        """Project a geometric error to screen pixels.

        ``distance`` is the distance to the bounding sphere surface, ``fov``
        is the vertical field of view in degrees and ``height`` the viewport
        height in pixels.
        """
        if distance <= 0.0:
            return float("inf")
        return (
            float(geo_err)
            * float(height)
            / (2.0 * math.tan(math.radians(float(fov)) * 0.5) * distance)
        )

    def _frustum_culled(self, model, camera):
        """Conservative frustum test against the model bounding sphere.

        Returns (culled, camera_to_center_distance). Spheres touching the
        camera plane or the view cone are kept visible.
        """
        center = tuple(float(v) for v in model["center"])
        pos = tuple(float(v) for v in camera["pos"])
        radius = float(model["radius"])
        to_center = _sub(center, pos)
        distance = _norm(to_center)

        if distance <= radius:
            return False, distance

        forward = _normalized(camera["forward"])
        depth = _dot(to_center, forward)
        if depth < -radius:
            return True, distance

        axis = (to_center[0] / distance, to_center[1] / distance, to_center[2] / distance)
        cos_angle = max(-1.0, min(1.0, _dot(forward, axis)))
        angle = math.acos(cos_angle)
        angular_radius = math.asin(min(radius / distance, 1.0))
        half_fov = math.radians(float(camera["fov"]) * 0.5)
        slack = math.radians(1.0)
        if angle - angular_radius > half_fov + slack:
            return True, distance
        return False, distance

    def _base_level(self, lods, errors):
        """Coarsest level within the pixel budget, ties prefer fewer tris."""
        count = len(lods)
        best = None
        for index in range(count - 1, -1, -1):
            if errors[index] <= self.max_px:
                if best is None:
                    best = index
                elif (
                    math.isclose(errors[index], errors[best], rel_tol=1e-9, abs_tol=1e-12)
                    and lods[index].get("triangles", 0) < lods[best].get("triangles", 0)
                ):
                    best = index
        if best is not None:
            return best
        # No level meets the budget (camera extremely close): take the
        # smallest error, breaking ties toward fewer triangles.
        return min(
            range(count),
            key=lambda index: (errors[index], lods[index].get("triangles", 0)),
        )

    def _apply_hysteresis(self, model_id, base_index, lods, errors):
        """Hold the previous level inside the buffered threshold band."""
        previous = self._state.get(model_id)
        previous_level = previous["level"] if previous is not None else None
        level_to_index = {lod["level"]: index for index, lod in enumerate(lods)}

        if previous_level is None or previous_level not in level_to_index:
            return base_index, previous_level
        if self.hysteresis <= 0.0:
            return base_index, previous_level

        previous_index = level_to_index[previous_level]
        relaxed = self.max_px * (1.0 + self.hysteresis)
        tight = self.max_px * (1.0 - self.hysteresis)

        if errors[previous_index] > relaxed:
            return base_index, previous_level

        chosen = previous_index
        for index in range(previous_index + 1, len(lods)):
            if errors[index] <= tight:
                chosen = index
        return chosen, previous_level

    def select(self, model, camera):
        model_id = model.get("id")
        culled, distance = self._frustum_culled(model, camera)
        if culled:
            return {
                "id": model_id,
                "culled": True,
                "lod": None,
                "err_px": None,
                "weight": 0.0,
            }

        lods = sorted(model["lods"], key=lambda lod: lod["level"])
        radius = float(model["radius"])

        if model.get("forced") is not None:
            forced_level = model["forced"]
            if distance <= radius:
                error_px = float("inf")
            else:
                surface_distance = distance - radius
                error_px = max(
                    self.screen_space_error(
                        lod.get("geo_err", 0.0),
                        surface_distance,
                        camera["fov"],
                        camera["height"],
                    )
                    for lod in lods
                )
            self._state[model_id] = {"level": forced_level}
            return {
                "id": model_id,
                "culled": False,
                "lod": forced_level,
                "err_px": error_px,
                "weight": 0.0,
            }

        if distance <= radius:
            selected_index = 0
            error_px = float("inf")
            previous = self._state.get(model_id)
            previous_level = previous["level"] if previous is not None else None
        else:
            surface_distance = distance - radius
            errors = [
                self.screen_space_error(
                    lod.get("geo_err", 0.0),
                    surface_distance,
                    camera["fov"],
                    camera["height"],
                )
                for lod in lods
            ]
            error_px = max(errors)
            base_index = self._base_level(lods, errors)
            selected_index, previous_level = self._apply_hysteresis(
                model_id, base_index, lods, errors
            )

        selected_level = lods[selected_index]["level"]
        weight = (
            0.5
            if previous_level is not None and selected_level != previous_level
            else 0.0
        )
        self._state[model_id] = {"level": selected_level}
        return {
            "id": model_id,
            "culled": False,
            "lod": selected_level,
            "err_px": error_px,
            "weight": weight,
        }

    def select_many(self, models, camera):
        # Stable output ordered by model id; equal ids keep input order.
        ordered = sorted(
            enumerate(models),
            key=lambda item: (str(item[1].get("id", item[0])), item[0]),
        )
        return [self.select(model, camera) for _, model in ordered]
