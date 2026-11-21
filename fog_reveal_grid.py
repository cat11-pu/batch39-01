import math
from collections import defaultdict


class FogRevealGrid:
    UNEXPLORED = "unexplored"
    EXPLORED = "explored"
    VISIBLE = "visible"

    def __init__(self, team="ally", chunk=8):
        if not isinstance(chunk, int) or isinstance(chunk, bool) or chunk <= 0:
            raise ValueError("chunk must be a positive integer")
        self.team = team
        self.chunk = chunk
        self.chunk_size = chunk

        self._units = []
        self._walls = set()
        self._wall_chunks = defaultdict(set)
        self._known_teams = {team}

        self._explored = defaultdict(dict)
        self._visible = defaultdict(dict)
        self._weights = defaultdict(dict)
        self._signatures = defaultdict(dict)
        self._active_chunks = defaultdict(set)
        self._last_recomputed = 0

    def set_units(self, units):
        normalized = []
        for index, item in enumerate(units or []):
            if isinstance(item, dict):
                get = item.get
            else:
                get = lambda name, default=None, item=item: getattr(item, name, default)

            unit_id = get("id", index)
            if unit_id is None:
                unit_id = index
            team = get("team", self.team)
            if team is None:
                team = self.team
            normalized.append(
                {
                    "id": unit_id,
                    "x": int(get("x", 0)),
                    "y": int(get("y", 0)),
                    "radius": max(0.0, float(get("radius", 0))),
                    "alive": bool(get("alive", True)),
                    "stealth": bool(get("stealth", False)),
                    "team": team,
                }
            )

        self._units = normalized
        self._known_teams.add(self.team)
        self._known_teams.update(unit["team"] for unit in normalized)
        return self

    def set_walls(self, walls):
        normalized = set()
        for wall in walls or []:
            if isinstance(wall, dict):
                x, y = wall.get("x"), wall.get("y")
            elif hasattr(wall, "x") and hasattr(wall, "y"):
                x, y = wall.x, wall.y
            else:
                x, y = wall[0], wall[1]
            if x is not None and y is not None:
                normalized.add((int(x), int(y)))

        self._walls = normalized
        self._wall_chunks = defaultdict(set)
        for x, y in normalized:
            self._wall_chunks[self._chunk_of(x, y)].add((x, y))
        return self

    def update(self):
        teams = set(self._known_teams)
        teams.add(self.team)
        teams.update(unit["team"] for unit in self._units)
        self._known_teams = teams

        recomputed = 0
        for team in sorted(teams, key=lambda value: (str(value), repr(value))):
            recomputed += self._update_team(team)
        self._last_recomputed = recomputed
        return self

    def state(self, x, y, team=None):
        team = self.team if team is None else team
        cell = (int(x), int(y))
        chunk = self._chunk_of(*cell)
        if cell in self._visible.get(team, {}).get(chunk, ()):
            return self.VISIBLE
        if cell in self._explored.get(team, {}).get(chunk, ()):
            return self.EXPLORED
        return self.UNEXPLORED

    def weight(self, x, y, team=None):
        team = self.team if team is None else team
        cell = (int(x), int(y))
        chunk = self._chunk_of(*cell)
        cell_weights = self._weights.get(team, {}).get(chunk, {})
        if cell in cell_weights:
            return float(cell_weights[cell])
        if cell in self._visible.get(team, {}).get(chunk, ()):
            return 1.0
        return 0.0

    def unit_visible(self, unit_id, team=None):
        team = self.team if team is None else team
        unit = next((item for item in self._units if item["id"] == unit_id), None)
        if unit is None:
            return False
        if unit["team"] == team:
            return bool(unit["alive"])
        if unit["stealth"]:
            return self.state(unit["x"], unit["y"], team=team) == self.VISIBLE
        return self.state(unit["x"], unit["y"], team=team) != self.UNEXPLORED

    def is_unit_visible(self, unit_id, team=None):
        return self.unit_visible(unit_id, team=team)

    def snapshot(self):
        chunks = []
        teams = set(self._explored)
        teams.update(self._visible)
        teams.update(self._known_teams)

        for team in teams:
            chunk_keys = set(self._explored.get(team, {}))
            chunk_keys.update(self._visible.get(team, {}))
            chunk_keys.update(self._weights.get(team, {}))
            for chunk in chunk_keys:
                explored = sorted(self._explored.get(team, {}).get(chunk, ()))
                visible = sorted(self._visible.get(team, {}).get(chunk, ()))
                weights = sorted(
                    (cell[0], cell[1], round(value, 6))
                    for cell, value in self._weights.get(team, {}).get(chunk, {}).items()
                )
                if not explored and not visible and not weights:
                    continue
                chunks.append(
                    {
                        "team": team,
                        "chunk": [chunk[0], chunk[1]],
                        "explored": [[x, y] for x, y in explored],
                        "visible": [[x, y] for x, y in visible],
                        "weights": [[x, y, value] for x, y, value in weights],
                    }
                )

        chunks.sort(key=lambda item: (str(item["team"]), repr(item["team"]), item["chunk"][0], item["chunk"][1]))
        units = sorted(
            (
                {
                    "id": unit["id"],
                    "x": unit["x"],
                    "y": unit["y"],
                    "radius": unit["radius"],
                    "alive": unit["alive"],
                    "stealth": unit["stealth"],
                    "team": unit["team"],
                }
                for unit in self._units
            ),
            key=lambda item: (str(item["team"]), repr(item["team"]), str(item["id"]), repr(item["id"]), item["x"], item["y"]),
        )
        return {
            "version": 1,
            "team": self.team,
            "chunk": self.chunk,
            "chunk_size": self.chunk,
            "recomputed": self._last_recomputed,
            "chunks": chunks,
            "units": units,
            "walls": [[x, y] for x, y in sorted(self._walls)],
        }

    def restore(self, snapshot):
        snapshot = snapshot or {}
        snapshot_chunk = snapshot.get("chunk", snapshot.get("chunk_size", self.chunk))
        if isinstance(snapshot_chunk, int) and not isinstance(snapshot_chunk, bool) and snapshot_chunk > 0:
            self.chunk = snapshot_chunk
            self.chunk_size = snapshot_chunk
        self.team = snapshot.get("team", self.team)
        self._explored = defaultdict(dict)
        self._visible = defaultdict(dict)
        self._weights = defaultdict(dict)
        self._signatures = defaultdict(dict)
        self._active_chunks = defaultdict(set)
        self._known_teams = {self.team}

        for item in snapshot.get("chunks", ()):
            team = item.get("team", self.team)
            self._known_teams.add(team)

            for coordinate in item.get("explored", ()):
                x, y = self._coordinate(coordinate)
                chunk = self._chunk_of(x, y)
                self._explored[team].setdefault(chunk, set()).add((x, y))

            for coordinate in item.get("visible", ()):
                x, y = self._coordinate(coordinate)
                chunk = self._chunk_of(x, y)
                self._explored[team].setdefault(chunk, set()).add((x, y))
                self._visible[team].setdefault(chunk, set()).add((x, y))
                self._weights[team].setdefault(chunk, {}).setdefault((x, y), 1.0)

            for entry in item.get("weights", ()):
                if isinstance(entry, dict):
                    x, y, value = entry.get("x"), entry.get("y"), entry.get("weight", 1.0)
                elif len(entry) >= 3:
                    x, y, value = entry[0], entry[1], entry[2]
                else:
                    continue
                if x is None or y is None:
                    continue
                x, y = int(x), int(y)
                chunk = self._chunk_of(x, y)
                self._explored[team].setdefault(chunk, set()).add((x, y))
                self._visible[team].setdefault(chunk, set()).add((x, y))
                self._weights[team].setdefault(chunk, {})[(x, y)] = float(value)

        units = snapshot.get("units")
        if units is not None:
            self.set_units(units)

        walls = snapshot.get("walls")
        if walls is not None:
            self.set_walls(walls)

        for team, chunks in self._visible.items():
            self._active_chunks[team] = set(chunks)

        self._last_recomputed = int(snapshot.get("recomputed", 0))
        return self

    def _update_team(self, team):
        vision_units = [
            unit
            for unit in self._units
            if unit["team"] == team and unit["alive"] and unit["radius"] >= 0
        ]

        chunk_units = defaultdict(list)
        current_chunks = set()
        for unit in vision_units:
            radius = unit["radius"]
            min_x = math.floor(unit["x"] - radius)
            max_x = math.ceil(unit["x"] + radius)
            min_y = math.floor(unit["y"] - radius)
            max_y = math.ceil(unit["y"] + radius)
            for cx in range(min_x // self.chunk, max_x // self.chunk + 1):
                for cy in range(min_y // self.chunk, max_y // self.chunk + 1):
                    chunk = (cx, cy)
                    current_chunks.add(chunk)
                    chunk_units[chunk].append(unit)

        candidates = set(current_chunks)
        candidates.update(self._active_chunks.get(team, ()))
        candidates.update(self._visible.get(team, {}))

        recomputed = 0
        signatures = self._signatures[team]
        for chunk in sorted(candidates):
            units_here = chunk_units.get(chunk, ())
            signature = self._signature(chunk, units_here)
            if chunk not in self._visible.get(team, {}) or signatures.get(chunk) != signature:
                self._recompute_chunk(team, chunk, units_here)
                signatures[chunk] = signature
                recomputed += 1

        self._active_chunks[team] = current_chunks
        return recomputed

    def _signature(self, chunk, units):
        unit_parts = []
        walls = set()
        for unit in units:
            unit_parts.append(
                (
                    str(unit["id"]),
                    repr(unit["id"]),
                    unit["x"],
                    unit["y"],
                    unit["radius"],
                    unit["alive"],
                    unit["stealth"],
                )
            )
            radius = unit["radius"]
            walls.update(
                self._walls_in_rect(
                    unit["x"] - radius,
                    unit["y"] - radius,
                    unit["x"] + radius,
                    unit["y"] + radius,
                )
            )

        unit_parts.sort()
        return (tuple(unit_parts), tuple(sorted(walls)))

    def _recompute_chunk(self, team, chunk, units):
        min_x = chunk[0] * self.chunk
        max_x = min_x + self.chunk - 1
        min_y = chunk[1] * self.chunk
        max_y = min_y + self.chunk - 1

        visible = set()
        weights = {}
        for unit in units:
            radius = unit["radius"]
            start_x = max(min_x, math.floor(unit["x"] - radius))
            end_x = min(max_x, math.ceil(unit["x"] + radius))
            start_y = max(min_y, math.floor(unit["y"] - radius))
            end_y = min(max_y, math.ceil(unit["y"] + radius))
            for y in range(start_y, end_y + 1):
                for x in range(start_x, end_x + 1):
                    dx = x - unit["x"]
                    dy = y - unit["y"]
                    distance_squared = dx * dx + dy * dy
                    if distance_squared > radius * radius:
                        continue
                    if self._blocked(unit["x"], unit["y"], x, y):
                        continue
                    cell = (x, y)
                    visible.add(cell)
                    value = self._cell_weight(math.sqrt(distance_squared), radius)
                    if value > weights.get(cell, -1.0):
                        weights[cell] = value

        explored = self._explored[team].setdefault(chunk, set())
        explored.update(visible)
        self._visible[team][chunk] = visible
        self._weights[team][chunk] = weights

    def _blocked(self, start_x, start_y, target_x, target_y):
        x, y = int(start_x), int(start_y)
        target_x, target_y = int(target_x), int(target_y)
        dx = abs(target_x - x)
        dy = abs(target_y - y)
        step_x = 1 if target_x > x else -1
        step_y = 1 if target_y > y else -1
        error = dx - dy

        while (x, y) != (target_x, target_y):
            doubled = 2 * error
            if doubled > -dy:
                error -= dy
                x += step_x
            if doubled < dx:
                error += dx
                y += step_y
            if (x, y) == (target_x, target_y):
                break
            if (x, y) in self._walls:
                return True
        return False

    def _walls_in_rect(self, min_x, min_y, max_x, max_y):
        min_cx = math.floor(min_x) // self.chunk
        max_cx = math.floor(max_x) // self.chunk
        min_cy = math.floor(min_y) // self.chunk
        max_cy = math.floor(max_y) // self.chunk
        result = set()
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                for wall in self._wall_chunks.get((cx, cy), ()):
                    if min_x <= wall[0] <= max_x and min_y <= wall[1] <= max_y:
                        result.add(wall)
        return result

    def _chunk_of(self, x, y):
        return (int(x) // self.chunk, int(y) // self.chunk)

    @staticmethod
    def _coordinate(value):
        if isinstance(value, dict):
            return int(value["x"]), int(value["y"])
        return int(value[0]), int(value[1])

    @staticmethod
    def _cell_weight(distance, radius):
        if radius <= 0:
            return 1.0
        progress = min(1.0, max(0.0, distance / radius))
        return 1.0 - 0.75 * progress
