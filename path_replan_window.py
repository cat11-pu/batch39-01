import heapq
import math
from collections import deque

SQRT2 = math.sqrt(2.0)


class PathReplanWindow:
    """Incremental replanning window for RTS unit pathfinding.

    Coordinate convention: cell (x, y) covers [x, x+1) x [y, y+1); its
    lower-left corner is (x, y). Open and closed checks share _is_open.
    """

    _MOVES = (
        (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2),
    )

    def __init__(self, budget=4, radius=0.5, goal_threshold=1.0):
        self.budget = budget
        self.radius = radius
        self.goal_threshold = goal_threshold
        self._units = {}
        self._queue = []
        self._seq = 0
        self._goal_claims = {}

    # ------------------------------------------------------------------
    # coordinate helpers (single convention: lower-left origin)
    # ------------------------------------------------------------------
    @staticmethod
    def _cell_of(pos):
        return (math.floor(pos[0]), math.floor(pos[1]))

    def _is_open(self, grid, cell):
        x, y = cell
        if x < 0 or y < 0 or x >= grid["width"] or y >= grid["height"]:
            return False
        cx = x + 0.5
        cy = y + 0.5
        limit = self.radius * self.radius + 1e-9
        for bx, by in grid["blocked"]:
            dx = cx - (bx + 0.5)
            dy = cy - (by + 0.5)
            if dx * dx + dy * dy <= limit:
                return False
        return True

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def request(self, unit_id, start, goal, grid, priority=0, now=0):
        state = self._units.get(unit_id)
        if state is not None:
            goal_moved = self._distance(goal, state["goal"]) > self.goal_threshold
            changed = grid["blocked"] ^ state["blocked"]
            affected = any(cell in state["raw_set"] for cell in changed)
            if not goal_moved and not affected:
                # Goal stayed within threshold and obstacle changes do not
                # touch the current path: reuse it verbatim.
                result = dict(state["result"])
                result["start"] = start
                result["goal"] = goal
                result["replanned"] = False
                result["reused_prefix"] = 0
                result["reused_segments"] = max(len(state["raw_path"]) - 1, 0)
                return result
            result = self._replan(unit_id, start, goal, grid, previous=state)
        else:
            result = self._replan(unit_id, start, goal, grid, previous=None)
        self._enqueue(unit_id, start, goal, grid, priority, now)
        return result

    def tick(self):
        done = []
        while self._queue and len(done) < self.budget:
            _, _, unit_id, start, goal, grid, now = heapq.heappop(self._queue)
            state = self._units.get(unit_id)
            done.append(self._replan(unit_id, start, goal, grid, previous=state))
        return done

    # ------------------------------------------------------------------
    # replanning
    # ------------------------------------------------------------------
    def _enqueue(self, unit_id, start, goal, grid, priority, now):
        self._seq += 1
        heapq.heappush(
            self._queue, (-priority, self._seq, unit_id, start, goal, grid, now)
        )

    def _replan(self, unit_id, start, goal, grid, previous):
        start_cell = self._cell_of(start)
        goal_cell = self._cell_of(goal)

        # Keep the already-walked prefix of the current path; only the
        # remaining suffix is recomputed.
        prefix = []
        if previous is not None and start_cell in previous["raw_path"]:
            idx = previous["raw_path"].index(start_cell)
            prefix = previous["raw_path"][: idx + 1]

        nearest = goal_cell
        target = goal_cell
        reason = "ok"
        if not self._is_open(grid, goal_cell):
            nearest = self._nearest_open(grid, goal_cell)
            target = nearest
            reason = "goal_blocked"

        if target is None:
            raw = [start_cell]
            reason = "no_path"
        else:
            raw, _, reached = self._astar(grid, start_cell, target)
            if not reached:
                reason = "no_path"

        if prefix:
            raw = prefix[:-1] + raw

        reused_segments = 0
        if previous is not None:
            new_set = set(raw)
            for cell in previous["raw_path"][len(prefix):]:
                if cell in new_set:
                    reused_segments += 1

        if reason == "no_path":
            path = raw
        else:
            path = self._smooth(grid, raw)

        result = {
            "unit_id": unit_id,
            "start": start,
            "goal": goal,
            "path": path,
            "cost": self._path_cost(path),
            "reason": reason,
            "nearest": nearest,
            "replanned": True,
            "reused_prefix": max(len(prefix) - 1, 0),
            "reused_segments": reused_segments,
        }

        # Conflicting goal claims are assigned deterministically, ordered
        # by unit id.
        claims = self._goal_claims.setdefault(goal_cell, [])
        if unit_id not in claims:
            claims.append(unit_id)
            claims.sort()

        self._units[unit_id] = {
            "start": start,
            "goal": goal,
            "blocked": set(grid["blocked"]),
            "raw_path": raw,
            "raw_set": set(raw),
            "result": result,
        }
        return result

    # ------------------------------------------------------------------
    # A* with sqrt(2) diagonal cost and no corner cutting
    # ------------------------------------------------------------------
    def _neighbors(self, grid, cell):
        x, y = cell
        for dx, dy, cost in self._MOVES:
            nb = (x + dx, y + dy)
            if not self._is_open(grid, nb):
                continue
            if dx and dy:
                if not self._is_open(grid, (x + dx, y)):
                    continue
                if not self._is_open(grid, (x, y + dy)):
                    continue
            yield nb, cost

    def _astar(self, grid, start, goal):
        if start == goal:
            return [start], 0.0, True

        def heuristic(cell):
            dx = abs(cell[0] - goal[0])
            dy = abs(cell[1] - goal[1])
            return max(dx, dy) + (SQRT2 - 1.0) * min(dx, dy)

        open_heap = [(heuristic(start), 0.0, start)]
        g_score = {start: 0.0}
        came_from = {}
        closed = set()
        best = start
        best_h = heuristic(start)
        while open_heap:
            _, gc, cur = heapq.heappop(open_heap)
            if cur in closed:
                continue
            closed.add(cur)
            hc = heuristic(cur)
            if hc < best_h:
                best_h = hc
                best = cur
            if cur == goal:
                return self._reconstruct(came_from, cur), gc, True
            for nb, step in self._neighbors(grid, cur):
                ng = gc + step
                if ng < g_score.get(nb, math.inf):
                    g_score[nb] = ng
                    came_from[nb] = cur
                    heapq.heappush(open_heap, (ng + heuristic(nb), ng, nb))
        # Unreachable: degrade to a partial path towards the goal instead
        # of raising.
        return self._reconstruct(came_from, best), g_score.get(best, 0.0), False

    @staticmethod
    def _reconstruct(came_from, node):
        path = [node]
        while node in came_from:
            node = came_from[node]
            path.append(node)
        path.reverse()
        return path

    def _nearest_open(self, grid, cell):
        if self._is_open(grid, cell):
            return cell
        visited = {cell}
        queue = deque([cell])
        while queue:
            cur = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb = (cur[0] + dx, cur[1] + dy)
                if nb in visited:
                    continue
                if not (0 <= nb[0] < grid["width"] and 0 <= nb[1] < grid["height"]):
                    continue
                if self._is_open(grid, nb):
                    return nb
                visited.add(nb)
                queue.append(nb)
        return None

    # ------------------------------------------------------------------
    # smoothing with radius-inflated clearance checks
    # ------------------------------------------------------------------
    def _smooth(self, grid, path):
        if len(path) <= 2:
            return list(path)
        smoothed = [path[0]]
        i = 0
        while i < len(path) - 1:
            j = len(path) - 1
            while j > i + 1 and not self._line_open(grid, path[i], path[j]):
                j -= 1
            smoothed.append(path[j])
            i = j
        return smoothed

    def _line_open(self, grid, a, b):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        steps = max(abs(dx), abs(dy), 1) * 4
        for k in range(steps + 1):
            t = k / steps
            px = a[0] + 0.5 + dx * t
            py = a[1] + 0.5 + dy * t
            if not self._is_open(grid, (math.floor(px), math.floor(py))):
                return False
        return True

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------
    @staticmethod
    def _path_cost(path):
        total = 0.0
        for a, b in zip(path, path[1:]):
            total += math.hypot(b[0] - a[0], b[1] - a[1])
        return total

    @staticmethod
    def _distance(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
