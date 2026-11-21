import math


class ShadowAtlasPlanner:
    BYTES_PER_TEXEL = 4
    MIN_TILE_SIZE = 64
    DEGENERATE_DOT = 0.999

    def __init__(self, max_tiles=16, tile_size=1024, budget_mb=256, overlap=0.1):
        self.max_tiles = max_tiles
        self.tile_size = tile_size
        self.budget_mb = budget_mb
        self.overlap = overlap

    def plan(self, shots):
        warnings = []
        cascades = []
        for shot in sorted(shots, key=lambda item: item["id"]):
            degenerate = self._is_degenerate(shot)
            if degenerate:
                warnings.append(
                    "shot %s: light direction nearly parallel to camera direction" % shot["id"]
                )
            layers = shot.get("layers", [])
            max_coverage = max(
                (layer.get("coverage", 0.0) for layer in layers if not layer.get("empty")),
                default=0.0,
            )
            for index, layer in enumerate(layers):
                empty = bool(layer.get("empty"))
                near = layer["near"]
                far = layer["far"]
                coverage = layer.get("coverage", 0.0)
                if empty or max_coverage <= 0.0:
                    size = 0
                else:
                    size = int(round(self.tile_size * coverage / max_coverage))
                    size = max(self.MIN_TILE_SIZE, min(self.tile_size, size))
                depth = far - near
                cascades.append({
                    "id": "%s#c%d" % (shot["id"], index),
                    "shot_id": shot["id"],
                    "near": near,
                    "far": far,
                    "coverage": coverage,
                    "overlap": self.overlap,
                    "empty": empty,
                    "degenerate": degenerate,
                    "tile_size": size,
                    "texel_density": (size / depth) if size and depth > 0 else 0.0,
                    "tile": None,
                })

        budget_bytes = int(self.budget_mb * 1024 * 1024)
        used_bytes = 0
        tiles = []
        candidates = sorted(
            (c for c in cascades if c["tile_size"] > 0),
            key=lambda c: (-c["coverage"], c["id"]),
        )
        for cascade in candidates:
            memory = cascade["tile_size"] ** 2 * self.BYTES_PER_TEXEL
            if len(tiles) >= self.max_tiles or used_bytes + memory > budget_bytes:
                warnings.append(
                    "cascade %s: tile dropped, tile/memory budget exhausted" % cascade["id"]
                )
                continue
            cascade["tile"] = len(tiles)
            tiles.append({
                "id": "tile-%d" % len(tiles),
                "cascade": cascade["id"],
                "size": cascade["tile_size"],
                "texel_density": cascade["texel_density"],
            })
            used_bytes += memory

        atlas = self._pack(tiles)
        return {
            "cascades": cascades,
            "tiles": tiles,
            "atlas": atlas,
            "warnings": warnings,
        }

    def _pack(self, tiles):
        if not tiles:
            return (0, 0)
        max_width = max(tile["size"] for tile in tiles)
        columns = max(1, int(math.ceil(math.sqrt(len(tiles)))))
        atlas_width = columns * max_width
        x = 0
        y = 0
        shelf_height = 0
        for tile in tiles:
            side = tile["size"]
            if x + side > atlas_width:
                x = 0
                y += shelf_height
                shelf_height = 0
            tile["rect"] = (x, y, side, side)
            x += side
            shelf_height = max(shelf_height, side)
        return (atlas_width, y + shelf_height)

    @staticmethod
    def _is_degenerate(shot):
        light = shot.get("light_dir", (0.0, 0.0, 0.0))
        camera = shot.get("camera_dir", (0.0, 0.0, 0.0))
        light_len = math.sqrt(sum(v * v for v in light))
        camera_len = math.sqrt(sum(v * v for v in camera))
        if light_len == 0.0 or camera_len == 0.0:
            return True
        dot = sum(a * b for a, b in zip(light, camera)) / (light_len * camera_len)
        return abs(dot) > ShadowAtlasPlanner.DEGENERATE_DOT
