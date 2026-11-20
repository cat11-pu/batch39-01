import heapq
import math
import random


class WangError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class TileWangSolver:
    _DIRECTIONS = ("top", "right", "bottom", "left")
    _OFFSETS = {
        "top": (0, -1),
        "right": (1, 0),
        "bottom": (0, 1),
        "left": (-1, 0),
    }
    _OPPOSITE = {
        "top": "bottom",
        "right": "left",
        "bottom": "top",
        "left": "right",
    }

    def __init__(self, tiles, seed=0, forbid_same=False):
        self.tiles = list(tiles)
        self.seed = seed
        self.forbid_same = forbid_same
        self._active_tiles = [
            tile for tile in self.tiles if self._weight(tile) > 0
        ]

    @staticmethod
    def _weight(tile):
        return tile.get("weight", 1)

    @staticmethod
    def _tile_id(tile):
        return tile["id"]

    def solve(self, width, height, holes=(), border=None):
        width = int(width)
        height = int(height)
        holes = {
            (int(x), int(y))
            for x, y in holes
            if 0 <= int(x) < width and 0 <= int(y) < height
        }
        border = border or {}

        self._width = width
        self._height = height
        self._holes = holes
        self._border = border
        self._rng = random.Random(self.seed)
        self._backtracks = 0
        self._best_partial = {}

        self._assignments = {}
        unassigned = {
            (x, y)
            for y in range(height)
            for x in range(width)
            if (x, y) not in holes
        }
        self._unassigned = unassigned

        if not unassigned:
            return self._success()

        self._domains = {}
        self._versions = {}
        self._heap = []
        for cell in unassigned:
            self._versions[cell] = 0
            self._domains[cell] = self._candidates(cell)
            self._push_domain(cell)

        stack = []
        last_conflict = None

        while True:
            self._discard_stale_heap_entries()

            if not unassigned:
                return self._success()

            if not self._heap:
                conflict = last_conflict or self._make_conflict(
                    next(iter(unassigned)), ()
                )
                return self._failure(conflict)

            cell = self._heap[0][3:]
            candidates = self._domains[cell]

            if not candidates:
                last_conflict = self._make_conflict(
                    cell, self._constraint_directions(cell)
                )
                self._remember_partial()
                if not stack:
                    return self._failure(last_conflict)

                if not self._backtrack(stack, unassigned):
                    return self._failure(last_conflict)
                continue

            ordered = self._weighted_order(candidates)
            tile = ordered[0]
            frame = {
                "cell": cell,
                "candidates": ordered,
                "next": 1,
            }
            stack.append(frame)
            self._assign(cell, tile, unassigned)

    def _success(self):
        grid = []
        for y in range(self._height):
            row = []
            for x in range(self._width):
                if (x, y) in self._holes:
                    row.append(None)
                else:
                    row.append(
                        self._tile_id(self._assignments[(x, y)])
                    )
            grid.append(row)
        return {
            "grid": grid,
            "conflict": None,
            "backtracks": self._backtracks,
        }

    def _failure(self, conflict, grid=None):
        if grid is None and self._border and self._best_partial:
            grid = self._partial_grid()
        return {
            "grid": grid,
            "conflict": conflict,
            "backtracks": self._backtracks,
        }

    def _partial_grid(self):
        grid = []
        for y in range(self._height):
            row = []
            for x in range(self._width):
                row.append(self._best_partial.get((x, y)))
            grid.append(row)
        return grid

    def _remember_partial(self):
        if len(self._assignments) > len(self._best_partial):
            self._best_partial = {
                cell: self._tile_id(tile)
                for cell, tile in self._assignments.items()
            }

    def _assign(self, cell, tile, unassigned):
        self._assignments[cell] = tile
        unassigned.discard(cell)
        self._refresh_neighbors(cell)

    def _backtrack(self, stack, unassigned):
        while stack:
            frame = stack.pop()
            cell = frame["cell"]
            self._assignments.pop(cell, None)
            unassigned.add(cell)
            self._backtracks += 1

            self._refresh_cell(cell)
            self._refresh_neighbors(cell)

            if frame["next"] < len(frame["candidates"]):
                tile = frame["candidates"][frame["next"]]
                frame["next"] += 1
                self._assign(cell, tile, unassigned)
                stack.append(frame)
                return True

        return False

    def _refresh_cell(self, cell):
        if cell not in self._unassigned:
            return
        self._versions[cell] += 1
        self._domains[cell] = self._candidates(cell)
        self._push_domain(cell)

    def _refresh_neighbors(self, cell):
        x, y = cell
        for dx, dy in self._OFFSETS.values():
            neighbor = (x + dx, y + dy)
            if neighbor in self._unassigned:
                self._refresh_cell(neighbor)

    def _push_domain(self, cell):
        x, y = cell
        heapq.heappush(
            self._heap,
            (
                len(self._domains[cell]),
                y * self._width + x,
                self._versions[cell],
                x,
                y,
            ),
        )

    def _discard_stale_heap_entries(self):
        while self._heap:
            count, _, version, x, y = self._heap[0]
            cell = (x, y)
            if (
                cell not in self._unassigned
                or self._versions.get(cell) != version
                or len(self._domains[cell]) != count
            ):
                heapq.heappop(self._heap)
                continue
            return

    def _candidates(self, cell):
        candidates = []
        for tile in self._active_tiles:
            if self._fits(cell, tile):
                candidates.append(tile)
        return candidates

    def _fits(self, cell, tile):
        x, y = cell
        for side in self._DIRECTIONS:
            border_color = self._border.get(side)
            if border_color is not None and self._on_border(cell, side):
                if tile[side] != border_color:
                    return False

            dx, dy = self._OFFSETS[side]
            neighbor = (x + dx, y + dy)
            neighbor_tile = self._assignments.get(neighbor)
            if neighbor_tile is None:
                continue
            if tile[side] != neighbor_tile[self._OPPOSITE[side]]:
                return False
            if self.forbid_same and (
                self._tile_id(tile) == self._tile_id(neighbor_tile)
            ):
                return False
        return True

    def _constraint_directions(self, cell):
        directions = []
        x, y = cell
        for side in self._DIRECTIONS:
            constrained = False
            if (
                self._border.get(side) is not None
                and self._on_border(cell, side)
            ):
                constrained = True

            dx, dy = self._OFFSETS[side]
            if (x + dx, y + dy) in self._assignments:
                constrained = True

            if constrained:
                directions.append(side)
        return directions or list(self._DIRECTIONS)

    def _on_border(self, cell, side):
        x, y = cell
        if side == "top":
            return y == 0
        if side == "bottom":
            return y == self._height - 1
        if side == "left":
            return x == 0
        return x == self._width - 1

    def _make_conflict(self, cell, directions):
        x, y = cell
        return {"x": x, "y": y, "directions": list(directions)}

    def _weighted_order(self, candidates):
        if len(candidates) == 1:
            return list(candidates)

        decorated = []
        for index, tile in enumerate(candidates):
            weight = self._weight(tile)
            key = -math.log(1.0 - self._rng.random()) / weight
            decorated.append((key, index, tile))
        decorated.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in decorated]
