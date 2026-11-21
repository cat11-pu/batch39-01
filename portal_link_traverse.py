class PortalError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_HALF_CELL = 0.5
_MODES = ("forward", "backward", "both")


def _snap(cell):
    return (cell[0] + _HALF_CELL, cell[1] + _HALF_CELL)


class PortalLinkTraverse:
    def __init__(self, links, agent_radius=0.5, walkable=None, traverse_duration=1.0):
        self.agent_radius = agent_radius
        self.walkable = walkable
        self.traverse_duration = traverse_duration
        self._raw_links = list(links)
        self._links = {}
        self._edges = []
        self._active = {}
        self.load()

    def load(self):
        seen = set()
        links = {}
        for raw in self._raw_links:
            link_id = raw["id"]
            if link_id in seen:
                raise PortalError("duplicate_link_id")
            seen.add(link_id)
            mode = raw.get("mode", "both")
            if mode not in _MODES:
                raise PortalError("invalid_mode")
            links[link_id] = {
                "id": link_id,
                "a": tuple(raw["a"]),
                "b": tuple(raw["b"]),
                "mode": mode,
                "cost": float(raw.get("cost", 0.0)),
                "max_size": raw.get("max_size"),
                "enabled": bool(raw.get("enabled", True)),
            }
        self._links = links
        self._edges = []
        for link in links.values():
            if link["mode"] in ("forward", "both"):
                self._edges.append((link["id"], "forward"))
            if link["mode"] in ("backward", "both"):
                self._edges.append((link["id"], "backward"))
        return self

    def path_cost(self, link_id, walk_before=0.0, walk_after=0.0):
        link = self._links.get(link_id)
        if link is None:
            raise PortalError("unknown_link")
        return walk_before + link["cost"] + walk_after

    def candidates(self, size=None):
        result = [
            link
            for link in self._links.values()
            if link["enabled"]
            and (size is None or link["max_size"] is None or size <= link["max_size"])
        ]
        result.sort(key=lambda link: (link["cost"], link["id"]))
        return result

    def traverse(self, unit, link_id, now=0):
        link = self._links.get(link_id)
        if link is None:
            raise PortalError("unknown_link")
        if not link["enabled"]:
            raise PortalError("link_disabled")
        max_size = link["max_size"]
        if max_size is not None and unit.get("size", 0) > max_size:
            raise PortalError("too_large")
        start_cell, end_cell, direction = self._resolve_direction(
            link, unit.get("pos", (0.0, 0.0))
        )
        if not self._direction_allowed(link, direction):
            raise PortalError("wrong_direction")
        start = _snap(start_cell)
        arrival = _snap(end_cell)
        reason = "" if self._is_walkable(end_cell) else "blocked_target"
        unit["locked"] = True
        unit["invulnerable"] = True
        self._active[unit.get("id")] = {
            "link_id": link_id,
            "direction": direction,
            "start": start,
            "arrival": arrival,
            "start_time": now,
        }
        return {
            "ok": not reason,
            "link_id": link_id,
            "direction": direction,
            "start": start,
            "arrival": arrival,
            "reason": reason,
        }

    def tick(self, unit, now):
        state = self._active.get(unit.get("id"))
        if state is None:
            return {"travelling": False, "position": tuple(unit.get("pos", (0.0, 0.0)))}
        link = self._links[state["link_id"]]
        if not link["enabled"]:
            position = self._interpolate(state, now)
            self._finish(unit, position)
            return {"interrupted": True, "reason": "link_closed", "position": position}
        elapsed = now - state["start_time"]
        if elapsed >= self.traverse_duration:
            self._finish(unit, state["arrival"])
            return {"done": True, "position": state["arrival"]}
        return {
            "travelling": True,
            "progress": elapsed / self.traverse_duration,
            "position": self._interpolate(state, now),
        }

    def close(self, link_id):
        link = self._links.get(link_id)
        if link is None:
            raise PortalError("unknown_link")
        link["enabled"] = False

    def _finish(self, unit, position):
        unit["pos"] = position
        unit["locked"] = False
        unit["invulnerable"] = False
        self._active.pop(unit.get("id"), None)

    def _interpolate(self, state, now):
        span = self.traverse_duration or 1.0
        t = min(max((now - state["start_time"]) / span, 0.0), 1.0)
        start, arrival = state["start"], state["arrival"]
        return (
            start[0] + (arrival[0] - start[0]) * t,
            start[1] + (arrival[1] - start[1]) * t,
        )

    def _resolve_direction(self, link, pos):
        a = _snap(link["a"])
        b = _snap(link["b"])
        dist_a = (pos[0] - a[0]) ** 2 + (pos[1] - a[1]) ** 2
        dist_b = (pos[0] - b[0]) ** 2 + (pos[1] - b[1]) ** 2
        if dist_a <= dist_b:
            return link["a"], link["b"], "forward"
        return link["b"], link["a"], "backward"

    @staticmethod
    def _direction_allowed(link, direction):
        if direction == "forward":
            return link["mode"] in ("forward", "both")
        return link["mode"] in ("backward", "both")

    def _is_walkable(self, cell):
        if self.walkable is None:
            return False
        if callable(self.walkable):
            return bool(self.walkable(cell))
        return cell in self.walkable
