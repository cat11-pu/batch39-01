import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


_NO_DEFAULT = object()
_MISSING = object()
_DECOR_KINDS = {
    "decor",
    "decoration",
    "decorative",
    "ground_decor",
    "floor_decor",
}


def _read(obj: Any, names: Iterable[str], default: Any = _NO_DEFAULT) -> Any:
    for name in names:
        if isinstance(obj, Mapping):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    if default is _NO_DEFAULT:
        raise ValueError("object is missing required field: %s" % next(iter(names)))
    return default


def _number(value: Any, field: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("%s must be finite" % field)
    return value


def _id_key(value: Any) -> Tuple[int, Any]:
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, str):
        return (1, value)
    return (2, type(value).__name__, repr(value))


@dataclass(frozen=True)
class _Entry:
    obj_id: Any
    col: float
    row: float
    w: float
    h: float
    layer: float
    kind: str
    shadow: bool
    occludes: bool
    id_key: Tuple[int, Any]

    @property
    def foot_depth(self) -> float:
        return self.row + self.col

    @property
    def coverage(self) -> Tuple[float, float, float, float]:
        return (self.col, self.row, self.col + self.w, self.row + self.h)

    @property
    def sort_key(self) -> Tuple[float, float, int, Tuple[int, Any]]:
        return (
            self.layer,
            self.foot_depth,
            0 if self.shadow else 1,
            self.id_key,
        )


def _overlaps(
    first: Tuple[float, float, float, float],
    second: Tuple[float, float, float, float],
) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


class IsoDepthSort:
    def __init__(self, *, decorations_occlude: bool = False):
        self._entries: Dict[Any, _Entry] = {}
        self._sorted: Optional[Tuple[_Entry, ...]] = None
        self._decorations_occlude = decorations_occlude

    def add(self, obj: Any) -> None:
        obj_id = _read(obj, ("id", "obj_id", "uid"))
        kind = str(_read(obj, ("kind", "type"), "unit")).lower()
        shadow = bool(_read(obj, ("shadow", "is_shadow"), False))
        if kind == "shadow":
            shadow = True

        explicit_occludes = _read(
            obj,
            ("occludes", "occlusion", "blocks", "blocking"),
            _MISSING,
        )
        if explicit_occludes is _MISSING:
            occludes = self._decorations_occlude or kind not in _DECOR_KINDS
        else:
            occludes = bool(explicit_occludes)
        if shadow:
            occludes = False

        entry = _Entry(
            obj_id=obj_id,
            col=_number(_read(obj, ("col", "x")), "col"),
            row=_number(_read(obj, ("row", "y")), "row"),
            w=_number(_read(obj, ("w", "width"), 1), "w"),
            h=_number(_read(obj, ("h", "height"), 1), "h"),
            layer=_number(_read(obj, ("layer", "level", "z"), 0), "layer"),
            kind=kind,
            shadow=shadow,
            occludes=occludes,
            id_key=_id_key(obj_id),
        )
        self._entries[obj_id] = entry
        self._sorted = None

    def remove(self, obj_id: Any) -> bool:
        if obj_id not in self._entries:
            return False
        del self._entries[obj_id]
        self._sorted = None
        return True

    def order(self) -> List[Any]:
        if self._sorted is None:
            self._sorted = tuple(
                sorted(self._entries.values(), key=lambda entry: entry.sort_key)
            )
        return [entry.obj_id for entry in self._sorted]

    def coverage(self, obj_id: Any) -> Optional[Tuple[float, float, float, float]]:
        entry = self._entries.get(obj_id)
        return None if entry is None else entry.coverage

    def occlusion(self, obj_id: Any) -> List[Any]:
        target = self._entries.get(obj_id)
        if target is None:
            return []

        ordered = self._sorted
        if ordered is None:
            ordered = tuple(
                sorted(self._entries.values(), key=lambda entry: entry.sort_key)
            )
            self._sorted = ordered

        target_index = next(
            index
            for index, entry in enumerate(ordered)
            if entry.obj_id == target.obj_id
        )
        return [
            entry.obj_id
            for entry in ordered[target_index + 1 :]
            if entry.layer == target.layer
            and entry.occludes
            and _overlaps(target.coverage, entry.coverage)
        ]
