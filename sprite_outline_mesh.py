import math


class OutlineError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_CLOCKWISE = (
    (0, -1), (1, -1), (1, 0), (1, 1),
    (0, 1), (-1, 1), (-1, 0), (-1, -1),
)

_ORTHOGONAL = ((0, -1), (1, 0), (0, 1), (-1, 0))


def _signed_area(points):
    if len(points) < 3:
        return 0.0
    total = 0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


class SpriteOutlineMesh:
    def __init__(self, threshold=0.5, tolerance=0.75, max_vertices=4096,
                 max_components=64, max_holes=256, expand=0):
        self.threshold = threshold
        self.tolerance = tolerance
        self.max_vertices = max_vertices
        self.max_components = max_components
        self.max_holes = max_holes
        self.expand = expand

    def build(self, alpha, width, height, region=None, expand=None):
        if expand is None:
            expand = self.expand
        solid = self._solid_pixels(alpha, width, height, region)
        if expand and expand > 0:
            solid = self._dilate(solid, float(expand))
        components = self._split_components(solid)
        if len(components) > self.max_components:
            raise OutlineError("too_many_components")
        owner = {}
        for index, pixels in enumerate(components):
            for pixel in pixels:
                owner[pixel] = index
        hole_regions = self._hole_regions(solid)
        if len(hole_regions) > self.max_holes:
            raise OutlineError("too_many_holes")
        component_holes = [[] for _ in components]
        for region_pixels in hole_regions:
            start, backtrack = self._hole_entry(solid, region_pixels)
            if start is None:
                continue
            component_holes[owner[start]].append((start, backtrack))
        traced = []
        raw_vertices = 0
        for index, pixels in enumerate(components):
            start = min(pixels, key=lambda p: (p[1], p[0]))
            outer = self._trace(solid, start, (start[0], start[1] - 1))
            holes = [self._trace(solid, s, b) for s, b in component_holes[index]]
            raw_vertices += len(outer) + sum(len(hole) for hole in holes)
            traced.append((outer, holes))
        if raw_vertices > self.max_vertices:
            raise OutlineError("too_many_vertices")
        result_components = []
        total_vertices = 0
        total_holes = 0
        for index, pixels in enumerate(components):
            outer, holes = traced[index]
            outer = self._simplify(outer)
            outer_area = _signed_area(outer)
            if outer_area < 0:
                outer.reverse()
                outer_area = -outer_area
            outer = self._canonical_rotation(outer)
            hole_entries = []
            area = outer_area
            for hole in holes:
                hole = self._simplify(hole)
                hole_area = _signed_area(hole)
                if hole_area > 0:
                    hole.reverse()
                    hole_area = -hole_area
                hole = self._canonical_rotation(hole)
                hole_entries.append({"points": hole, "area": hole_area})
                area += hole_area
                total_vertices += len(hole)
            total_vertices += len(outer)
            total_holes += len(hole_entries)
            result_components.append({
                "outer": outer,
                "outer_area": outer_area,
                "holes": hole_entries,
                "area": area,
                "diagonal_links": self._diagonal_links(pixels),
            })
        return {
            "unit": "source_pixel",
            "vertices": total_vertices,
            "holes": total_holes,
            "components": result_components,
        }

    def _solid_pixels(self, alpha, width, height, region):
        if region is None:
            x0, y0, x1, y1 = 0, 0, width, height
        else:
            rx, ry, rw, rh = region
            x0 = max(0, rx)
            y0 = max(0, ry)
            x1 = min(width, rx + rw)
            y1 = min(height, ry + rh)
        solid = set()
        for y in range(y0, y1):
            base = y * width
            for x in range(x0, x1):
                if alpha[base + x] >= self.threshold:
                    solid.add((x, y))
        return solid

    @staticmethod
    def _dilate(solid, expand):
        if not solid:
            return set(solid)
        radius = int(math.ceil(expand))
        limit = expand * expand
        xs = [p[0] for p in solid]
        ys = [p[1] for p in solid]
        dilated = set()
        for y in range(min(ys) - radius, max(ys) + radius + 1):
            for x in range(min(xs) - radius, max(xs) + radius + 1):
                for sx, sy in solid:
                    dx = x - sx
                    dy = y - sy
                    if dx * dx + dy * dy <= limit:
                        dilated.add((x, y))
                        break
        return dilated

    @staticmethod
    def _split_components(solid):
        remaining = set(solid)
        components = []
        for seed in sorted(solid, key=lambda p: (p[1], p[0])):
            if seed not in remaining:
                continue
            stack = [seed]
            remaining.discard(seed)
            pixels = set()
            while stack:
                x, y = stack.pop()
                pixels.add((x, y))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        neighbor = (x + dx, y + dy)
                        if neighbor in remaining:
                            remaining.discard(neighbor)
                            stack.append(neighbor)
            components.append(pixels)
        return components

    @staticmethod
    def _hole_regions(solid):
        if not solid:
            return []
        xs = [p[0] for p in solid]
        ys = [p[1] for p in solid]
        x0, x1 = min(xs) - 1, max(xs) + 1
        y0, y1 = min(ys) - 1, max(ys) + 1
        seen = set()
        holes = []
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x, y) in solid or (x, y) in seen:
                    continue
                region = []
                stack = [(x, y)]
                seen.add((x, y))
                touches_border = False
                while stack:
                    px, py = stack.pop()
                    region.append((px, py))
                    if px in (x0, x1) or py in (y0, y1):
                        touches_border = True
                    for dx, dy in _ORTHOGONAL:
                        neighbor = (px + dx, py + dy)
                        if neighbor in solid or neighbor in seen:
                            continue
                        if not (x0 <= neighbor[0] <= x1 and y0 <= neighbor[1] <= y1):
                            continue
                        seen.add(neighbor)
                        stack.append(neighbor)
                if not touches_border:
                    holes.append(region)
        return holes

    @staticmethod
    def _hole_entry(solid, region_pixels):
        region = set(region_pixels)
        candidates = []
        for x, y in region_pixels:
            for dx, dy in _ORTHOGONAL:
                neighbor = (x + dx, y + dy)
                if neighbor in solid:
                    candidates.append((neighbor, (x, y)))
        if not candidates:
            return None, None
        candidates.sort(key=lambda item: (item[0][1], item[0][0], item[1][1], item[1][0]))
        return candidates[0]

    @staticmethod
    def _trace(solid, start, backtrack):
        loop = [start]
        current = start
        back = backtrack
        limit = 16 * (len(solid) + 1)
        while limit > 0:
            limit -= 1
            cx, cy = current
            base = None
            for index, (dx, dy) in enumerate(_CLOCKWISE):
                if (cx + dx, cy + dy) == back:
                    base = index
                    break
            if base is None:
                break
            nxt = None
            nback = None
            for step in range(1, 9):
                offset = _CLOCKWISE[(base + step) % 8]
                candidate = (cx + offset[0], cy + offset[1])
                if candidate in solid:
                    nxt = candidate
                    previous = _CLOCKWISE[(base + step - 1) % 8]
                    nback = (cx + previous[0], cy + previous[1])
                    break
            if nxt is None:
                break
            if current == start and len(loop) >= 2 and nxt == loop[1]:
                break
            current = nxt
            back = nback
            loop.append(current)
        if len(loop) > 1 and loop[-1] == loop[0]:
            loop.pop()
        return loop

    def _simplify(self, points):
        points = self._dedupe(points)
        if self.tolerance > 0:
            points = self._merge_close(points, float(self.tolerance))
        return self._drop_collinear(points)

    @staticmethod
    def _dedupe(points):
        kept = []
        for point in points:
            if not kept or kept[-1] != point:
                kept.append(point)
        if len(kept) > 1 and kept[0] == kept[-1]:
            kept.pop()
        return kept

    @staticmethod
    def _merge_close(points, tolerance):
        if len(points) < 2:
            return points
        limit = tolerance * tolerance
        kept = [points[0]]
        for point in points[1:]:
            dx = point[0] - kept[-1][0]
            dy = point[1] - kept[-1][1]
            if dx * dx + dy * dy >= limit:
                kept.append(point)
        while len(kept) > 1:
            dx = kept[-1][0] - kept[0][0]
            dy = kept[-1][1] - kept[0][1]
            if dx * dx + dy * dy >= limit:
                break
            kept.pop()
        return kept

    @staticmethod
    def _drop_collinear(points):
        points = list(points)
        changed = True
        while changed and len(points) > 2:
            changed = False
            kept = []
            count = len(points)
            for index in range(count):
                ax, ay = points[(index - 1) % count]
                bx, by = points[index]
                cx, cy = points[(index + 1) % count]
                cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
                dot = (bx - ax) * (cx - bx) + (by - ay) * (cy - by)
                if cross == 0 and dot >= 0:
                    changed = True
                    continue
                kept.append((bx, by))
            points = kept
        return points

    @staticmethod
    def _canonical_rotation(points):
        if not points:
            return points
        index = min(range(len(points)), key=lambda i: points[i])
        return points[index:] + points[:index]

    @staticmethod
    def _diagonal_links(pixels):
        links = 0
        for x, y in pixels:
            if (x + 1, y + 1) in pixels:
                links += 1
            if (x + 1, y - 1) in pixels:
                links += 1
        return links
