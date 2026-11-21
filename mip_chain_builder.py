import hashlib
import math


CHANNELS = 4
ROUND_DIGITS = 6


def _srgb_to_linear(value):
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value):
    if value <= 0.0031308:
        return value * 12.92
    return 1.055 * value ** (1.0 / 2.4) - 0.055


def _round_half_up(value):
    if value == 0.0:
        return 0.0
    scale = 10.0 ** ROUND_DIGITS
    return math.copysign(math.floor(abs(value) * scale + 0.5) / scale, value)


def _clamp01(value):
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


class MipChainBuilder:
    """Builds a complete mipmap chain with 2x2 box-filter downsampling."""

    def __init__(self, srgb=True, min_size=1, max_size=4096, premultiply_alpha=True):
        self.srgb = srgb
        self.min_size = min_size
        self.max_size = max_size
        self.premultiply_alpha = premultiply_alpha

    def build(self, data, width, height, layers=1, region=None):
        self._validate(data, width, height, layers)

        source = list(data)
        work_width, work_height = width, height
        if region is not None:
            source, work_width, work_height = self._extract_region(
                source, width, height, layers, region
            )

        levels = []
        current = source
        cur_width, cur_height = work_width, work_height
        while True:
            levels.append(self._make_level(current, cur_width, cur_height, layers))
            if cur_width <= self.min_size and cur_height <= self.min_size:
                break
            current = self._downsample(current, cur_width, cur_height, layers)
            cur_width = max(self.min_size, (cur_width + 1) // 2)
            cur_height = max(self.min_size, (cur_height + 1) // 2)

        return {"count": len(levels), "levels": levels}

    def _validate(self, data, width, height, layers):
        if not isinstance(width, int) or not isinstance(height, int):
            raise ValueError("width and height must be integers")
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be greater than zero")
        if width > self.max_size or height > self.max_size:
            raise ValueError(
                f"texture dimensions {width}x{height} exceed max_size {self.max_size}"
            )
        if not isinstance(layers, int) or layers <= 0:
            raise ValueError("layers must be a positive integer")
        if not isinstance(self.min_size, int) or self.min_size < 1:
            raise ValueError("min_size must be a positive integer")
        if self.min_size > width or self.min_size > height:
            raise ValueError(
                f"min_size {self.min_size} cannot exceed source dimensions "
                f"{width}x{height}"
            )
        expected = width * height * layers * CHANNELS
        if len(data) != expected:
            raise ValueError(
                f"data length {len(data)} does not match "
                f"{width}x{height}x{layers} RGBA"
            )

    def _extract_region(self, data, width, height, layers, region):
        if len(region) != 4:
            raise ValueError("region must be (x, y, width, height)")
        region_x, region_y, region_width, region_height = region
        if (
            not all(isinstance(v, int) for v in region)
            or region_width <= 0
            or region_height <= 0
            or region_x < 0
            or region_y < 0
            or region_x + region_width > width
            or region_y + region_height > height
        ):
            raise ValueError("region is outside the source texture bounds")

        extracted = []
        row_span = region_width * CHANNELS
        for layer in range(layers):
            layer_base = layer * height * width * CHANNELS
            for y in range(region_y, region_y + region_height):
                start = layer_base + (y * width + region_x) * CHANNELS
                extracted.extend(data[start:start + row_span])
        return extracted, region_width, region_height

    def _make_level(self, data, width, height, layers):
        return {
            "width": width,
            "height": height,
            "layers": layers,
            "data": list(data),
            "checksum": self._checksum(data, width, height, layers),
        }

    def _checksum(self, data, width, height, layers):
        payload = [f"{width},{height},{layers}"]
        payload.extend(f"{value:.{ROUND_DIGITS}f}" for value in data)
        return hashlib.sha256(";".join(payload).encode("utf-8")).hexdigest()

    def _downsample(self, source, width, height, layers):
        new_width = max(self.min_size, (width + 1) // 2)
        new_height = max(self.min_size, (height + 1) // 2)
        result = [0.0] * (new_width * new_height * layers * CHANNELS)

        for layer in range(layers):
            src_layer_base = layer * height * width * CHANNELS
            dst_layer_base = layer * new_height * new_width * CHANNELS
            for new_y in range(new_height):
                y0 = new_y * 2
                y1 = min(y0 + 1, height - 1)
                for new_x in range(new_width):
                    x0 = new_x * 2
                    x1 = min(x0 + 1, width - 1)
                    pixel = self._box_average(
                        source, width, src_layer_base, x0, x1, y0, y1
                    )
                    dst_index = dst_layer_base + (new_y * new_width + new_x) * CHANNELS
                    result[dst_index:dst_index + CHANNELS] = pixel
        return result

    def _box_average(self, source, width, layer_base, x0, x1, y0, y1):
        red = green = blue = alpha = 0.0
        for y in (y0, y1):
            row_base = layer_base + y * width * CHANNELS
            for x in (x0, x1):
                index = row_base + x * CHANNELS
                r, g, b, a = source[index:index + CHANNELS]
                if self.srgb:
                    r = _srgb_to_linear(r)
                    g = _srgb_to_linear(g)
                    b = _srgb_to_linear(b)
                if self.premultiply_alpha:
                    r *= a
                    g *= a
                    b *= a
                red += r
                green += g
                blue += b
                alpha += a

        red /= 4.0
        green /= 4.0
        blue /= 4.0
        alpha /= 4.0

        if self.premultiply_alpha:
            if alpha > 0.0:
                red /= alpha
                green /= alpha
                blue /= alpha
            else:
                red = green = blue = 0.0
        if self.srgb:
            red = _linear_to_srgb(red)
            green = _linear_to_srgb(green)
            blue = _linear_to_srgb(blue)

        return [
            _round_half_up(_clamp01(red)),
            _round_half_up(_clamp01(green)),
            _round_half_up(_clamp01(blue)),
            _round_half_up(_clamp01(alpha)),
        ]
