class NineSliceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class NineSliceScale:
    def __init__(self, mode="nine", tile_center=False, flip=False, rotate=0):
        if mode not in ("nine", "three"):
            raise NineSliceError("invalid_mode")
        self.mode = mode
        self.tile_center = bool(tile_center)
        self.flip = bool(flip)
        self.rotate = rotate

    def build(self, src, borders, dst, flip=None, rotate=None):
        flip = self.flip if flip is None else bool(flip)
        rotate = self.rotate if rotate is None else rotate
        sx, sy, sw, sh = src["x"], src["y"], src["w"], src["h"]
        left = borders["left"]
        right = borders["right"]
        top = borders["top"]
        bottom = borders["bottom"]

        if min(left, right, top, bottom) < 0:
            raise NineSliceError("border_negative")
        if sw <= 0 or sh <= 0:
            raise NineSliceError("invalid_source")
        if left + right > sw or top + bottom > sh:
            raise NineSliceError("border_too_large")

        dx, dy, dw, dh = dst["x"], dst["y"], dst["w"], dst["h"]
        clamped = False
        if dw < left + right:
            dw = left + right
            clamped = True
        if dh < top + bottom:
            dh = top + bottom
            clamped = True

        quads = []
        if self.mode == "three":
            self._build_three(quads, sx, sy, sw, sh, left, right, dx, dy, dw, dh)
        else:
            self._build_nine(
                quads, sx, sy, sw, sh, left, right, top, bottom, dx, dy, dw, dh
            )

        if flip:
            quads = [self._flip_quad(q, sx, sw) for q in quads]

        rotate = rotate % 360
        if rotate not in (0, 90, 180, 270):
            raise NineSliceError("invalid_rotate")
        if rotate:
            quads = [
                self._rotate_quad(q, sx, sy, sw, sh, dx, dy, dw, dh, rotate)
                for q in quads
            ]

        return {"quads": quads, "clamped": clamped}

    def _build_nine(self, quads, sx, sy, sw, sh, left, right, top, bottom,
                    dx, dy, dw, dh):
        cols_x = (dx, dx + left, dx + dw - right)
        cols_w = (left, dw - left - right, right)
        cols_u = ((sx, sx + left), (sx + left, sx + sw - right), (sx + sw - right, sx + sw))
        rows_y = (dy, dy + top, dy + dh - bottom)
        rows_h = (top, dh - top - bottom, bottom)
        rows_v = ((sy, sy + top), (sy + top, sy + sh - bottom), (sy + sh - bottom, sy + sh))
        parts = (
            ("corner_tl", "top", "corner_tr"),
            ("left", "center", "right"),
            ("corner_bl", "bottom", "corner_br"),
        )
        for row in range(3):
            for col in range(3):
                part = parts[row][col]
                u0, u1 = cols_u[col]
                v0, v1 = rows_v[row]
                if part == "center":
                    self._emit_center(
                        quads, part,
                        cols_x[col], rows_y[row], cols_w[col], rows_h[row],
                        u0, v0, u1, v1,
                    )
                else:
                    self._emit(
                        quads, part,
                        cols_x[col], rows_y[row], cols_w[col], rows_h[row],
                        u0, v0, u1, v1,
                    )

    def _build_three(self, quads, sx, sy, sw, sh, left, right, dx, dy, dw, dh):
        self._emit(quads, "left", dx, dy, left, dh, sx, sy, sx + left, sy + sh)
        self._emit_center(
            quads, "center", dx + left, dy, dw - left - right, dh,
            sx + left, sy, sx + sw - right, sy + sh,
        )
        self._emit(
            quads, "right", dx + dw - right, dy, right, dh,
            sx + sw - right, sy, sx + sw, sy + sh,
        )

    def _emit(self, quads, part, x, y, w, h, u0, v0, u1, v1):
        if w <= 0 or h <= 0 or u1 <= u0 or v1 <= v0:
            return
        quads.append({
            "part": part,
            "dst": {"x": x, "y": y, "w": w, "h": h},
            "uv": (u0, v0, u1, v1),
        })

    def _emit_center(self, quads, part, x, y, w, h, u0, v0, u1, v1):
        if not self.tile_center:
            self._emit(quads, part, x, y, w, h, u0, v0, u1, v1)
            return
        tile_w = u1 - u0
        tile_h = v1 - v0
        if w <= 0 or h <= 0 or tile_w <= 0 or tile_h <= 0:
            return
        off_y = 0
        while off_y < h:
            cur_h = min(tile_h, h - off_y)
            off_x = 0
            while off_x < w:
                cur_w = min(tile_w, w - off_x)
                self._emit(
                    quads, part,
                    x + off_x, y + off_y, cur_w, cur_h,
                    u0, v0, u0 + cur_w, v0 + cur_h,
                )
                off_x += cur_w
            off_y += cur_h

    @staticmethod
    def _flip_quad(quad, sx, sw):
        u0, v0, u1, v1 = quad["uv"]
        return {
            "part": quad["part"],
            "dst": dict(quad["dst"]),
            "uv": (2 * sx + sw - u1, v0, 2 * sx + sw - u0, v1),
        }

    @staticmethod
    def _rotate_quad(quad, sx, sy, sw, sh, dx, dy, dw, dh, rotate):
        dst = quad["dst"]
        rel_x = dst["x"] - dx
        rel_y = dst["y"] - dy
        w = dst["w"]
        h = dst["h"]
        u0, v0, u1, v1 = quad["uv"]
        if rotate == 90:
            new_dst = {"x": dx + (dh - rel_y - h), "y": dy + rel_x, "w": h, "h": w}
            new_uv = (
                sx + sh - (v1 - sy),
                sy + (u0 - sx),
                sx + sh - (v0 - sy),
                sy + (u1 - sx),
            )
        elif rotate == 180:
            new_dst = {
                "x": dx + (dw - rel_x - w),
                "y": dy + (dh - rel_y - h),
                "w": w,
                "h": h,
            }
            new_uv = (
                2 * sx + sw - u1,
                2 * sy + sh - v1,
                2 * sx + sw - u0,
                2 * sy + sh - v0,
            )
        else:
            new_dst = {"x": dx + rel_y, "y": dy + (dw - rel_x - w), "w": h, "h": w}
            new_uv = (
                sx + (v0 - sy),
                sy + sw - (u1 - sx),
                sx + (v1 - sy),
                sy + sw - (u0 - sx),
            )
        return {"part": quad["part"], "dst": new_dst, "uv": new_uv}
