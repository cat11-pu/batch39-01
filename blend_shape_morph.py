import math
import struct


class MorphError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _quantize(value):
    try:
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error) as exc:
        raise MorphError("non_finite_value") from exc


def _vector(value, size=3):
    if value is None:
        return [0.0] * size
    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError) as exc:
        raise MorphError("invalid_vector") from exc
    if len(result) != size:
        raise MorphError("invalid_vector")
    if not all(math.isfinite(component) for component in result):
        raise MorphError("non_finite_value")
    return result


def _normalize(vector, fallback):
    length = math.sqrt(sum(component * component for component in vector))
    if not math.isfinite(length) or length <= 1e-12:
        return list(fallback)
    return [component / length for component in vector]


def _bounds(vertices):
    if not vertices:
        return None
    minima = list(vertices[0]["pos"])
    maxima = list(vertices[0]["pos"])
    for vertex in vertices[1:]:
        for axis, value in enumerate(vertex["pos"]):
            minima[axis] = min(minima[axis], value)
            maxima[axis] = max(maxima[axis], value)
    return (tuple(minima), tuple(maxima))


class BlendShapeMorph:
    def __init__(self, base, targets, budget=8):
        if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
            raise MorphError("invalid_budget")

        try:
            base_vertices = list(base)
        except TypeError as exc:
            raise MorphError("invalid_base") from exc

        self.base = []
        for source in base_vertices:
            if not isinstance(source, dict) or "pos" not in source:
                raise MorphError("invalid_base")
            self.base.append(
                {
                    "pos": _vector(source["pos"]),
                    "normal": _vector(source.get("normal", (0.0, 0.0, 1.0))),
                    "tangent": _vector(source.get("tangent", (1.0, 0.0, 0.0))),
                }
            )

        self.budget = budget
        self.targets = []
        self._target_by_name = {}
        self._load_targets(targets)
        self.bbox = _bounds(self.base)
        self.weights = {}
        self.vertices = self._copy_mesh(self.base)

    def _load_targets(self, targets):
        if targets is None:
            return
        if isinstance(targets, dict):
            target_items = []
            for name, target in targets.items():
                if not isinstance(target, dict):
                    raise MorphError("invalid_target")
                target = dict(target)
                target.setdefault("name", name)
                target_items.append(target)
        else:
            try:
                target_items = list(targets)
            except TypeError as exc:
                raise MorphError("invalid_target") from exc

        for source in target_items:
            if not isinstance(source, dict):
                raise MorphError("invalid_target")
            name = source.get("name")
            if not isinstance(name, str) or not name:
                raise MorphError("invalid_target")
            if name in self._target_by_name:
                raise MorphError("duplicate_target")

            if "indices" in source and source["indices"] is not None:
                try:
                    indices = list(source["indices"])
                except TypeError as exc:
                    raise MorphError("invalid_index") from exc
            else:
                indices = list(range(len(self.base)))

            if len(set(indices)) != len(indices):
                raise MorphError("duplicate_index")
            for index in indices:
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or index < 0
                    or index >= len(self.base)
                ):
                    raise MorphError("out_of_range_index")

            deltas = {}
            for key, default in (
                ("delta_pos", None),
                ("delta_normal", (0.0, 0.0, 0.0)),
                ("delta_tangent", (0.0, 0.0, 0.0)),
            ):
                if key not in source or source[key] is None:
                    if key == "delta_pos":
                        raise MorphError("missing_delta")
                    values = [default] * len(indices)
                else:
                    try:
                        values = list(source[key])
                    except TypeError as exc:
                        raise MorphError("invalid_delta") from exc
                    if len(values) != len(indices):
                        raise MorphError("delta_length_mismatch")
                deltas[key] = [_vector(value) for value in values]

            target = {
                "name": name,
                "indices": indices,
                "delta_pos": deltas["delta_pos"],
                "delta_normal": deltas["delta_normal"],
                "delta_tangent": deltas["delta_tangent"],
            }
            self.targets.append(target)
            self._target_by_name[name] = target

    @staticmethod
    def _copy_mesh(vertices):
        return [
            {
                "pos": tuple(vertex["pos"]),
                "normal": tuple(vertex["normal"]),
                "tangent": tuple(vertex["tangent"]),
            }
            for vertex in vertices
        ]

    @staticmethod
    def _normalize_weights(weights, normalize):
        if not isinstance(weights, dict):
            raise MorphError("invalid_weights")

        result = {}
        for name, value in weights.items():
            if not isinstance(name, str):
                raise MorphError("invalid_weights")
            try:
                weight = float(value)
            except (TypeError, ValueError) as exc:
                raise MorphError("invalid_weights") from exc
            if not math.isfinite(weight):
                raise MorphError("non_finite_weight")
            result[name] = weight

        if normalize:
            total = math.fsum(result.values())
            if total > 1.0:
                scale = 1.0 / total
                result = {name: value * scale for name, value in result.items()}
        return result

    @staticmethod
    def _coerce_bbox(bbox):
        if bbox is None:
            return None
        if isinstance(bbox, dict):
            if "min" not in bbox or "max" not in bbox:
                raise MorphError("invalid_bbox")
            minimum, maximum = bbox["min"], bbox["max"]
        else:
            try:
                minimum, maximum = bbox
            except (TypeError, ValueError) as exc:
                raise MorphError("invalid_bbox") from exc
        minimum = _vector(minimum)
        maximum = _vector(maximum)
        if any(low > high for low, high in zip(minimum, maximum)):
            raise MorphError("invalid_bbox")
        return minimum, maximum

    def apply(self, weights, normalize=True, mode="additive", bbox=None):
        if mode not in ("additive", "relative"):
            raise MorphError("invalid_mode")

        self.weights = self._normalize_weights(weights, normalize)
        positions = [list(vertex["pos"]) for vertex in self.base]
        normals = [list(vertex["normal"]) for vertex in self.base]
        tangents = [list(vertex["tangent"]) for vertex in self.base]
        touched = [False] * len(self.base)

        batch_size = self.budget
        batches = (len(self.targets) + batch_size - 1) // batch_size
        for batch_start in range(0, len(self.targets), batch_size):
            for target in self.targets[batch_start : batch_start + batch_size]:
                weight = self.weights.get(target["name"], 0.0)
                if weight == 0.0:
                    continue
                for local_index, vertex_index in enumerate(target["indices"]):
                    touched[vertex_index] = True
                    for axis in range(3):
                        positions[vertex_index][axis] += (
                            weight * target["delta_pos"][local_index][axis]
                        )
                        normals[vertex_index][axis] += (
                            weight * target["delta_normal"][local_index][axis]
                        )
                        tangents[vertex_index][axis] += (
                            weight * target["delta_tangent"][local_index][axis]
                        )

        clip_bounds = self._coerce_bbox(bbox)
        clamped = False
        modified = list(touched)
        if clip_bounds is not None:
            minimum, maximum = clip_bounds
            for vertex_index, position in enumerate(positions):
                for axis in range(3):
                    value = position[axis]
                    if value < minimum[axis]:
                        position[axis] = minimum[axis]
                        clamped = True
                        modified[vertex_index] = True
                    elif value > maximum[axis]:
                        position[axis] = maximum[axis]
                        clamped = True
                        modified[vertex_index] = True

        output = []
        for index, position in enumerate(positions):
            if not modified[index]:
                output.append(
                    {
                        "pos": tuple(self.base[index]["pos"]),
                        "normal": tuple(self.base[index]["normal"]),
                        "tangent": tuple(self.base[index]["tangent"]),
                    }
                )
                continue
            if touched[index]:
                normal = _normalize(normals[index], self.base[index]["normal"])
                tangent = _normalize(tangents[index], self.base[index]["tangent"])
            else:
                normal = self.base[index]["normal"]
                tangent = self.base[index]["tangent"]
            output.append(
                {
                    "pos": tuple(_quantize(value) for value in position),
                    "normal": tuple(_quantize(value) for value in normal),
                    "tangent": tuple(_quantize(value) for value in tangent),
                }
            )

        if clip_bounds is None:
            self.bbox = _bounds(output)
        else:
            self.bbox = (
                tuple(_quantize(value) for value in clip_bounds[0]),
                tuple(_quantize(value) for value in clip_bounds[1]),
            )
        self.vertices = output

        tangent_updated = any(touched)
        return {
            "vertices": output,
            "weights": {
                name: _quantize(value) for name, value in self.weights.items()
            },
            "batches": batches,
            "clamped": clamped,
            "bbox": self.bbox,
            "tangent_updated": tangent_updated,
            "normal_updated": tangent_updated,
        }

    def reset(self):
        self.weights = {}
        self.vertices = self._copy_mesh(self.base)
        self.bbox = _bounds(self.base)
        return {
            "vertices": self.vertices,
            "weights": {},
            "batches": 0,
            "clamped": False,
            "bbox": self.bbox,
            "tangent_updated": False,
            "normal_updated": False,
        }
