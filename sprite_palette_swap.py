"""Indexed-sprite palette swapping.

The public surface is intentionally small: :class:`SpritePaletteSwap` accepts an
indexed image, a palette, and an index mapping, and returns the shaded image
together with cache/diagnostic information.  Pixel data is always derived from
the original index image, so repeatedly swapping an image cannot accumulate
colour drift.
"""

from __future__ import annotations

import hashlib
import math
import operator
from collections.abc import Mapping, Sequence


class PaletteError(ValueError):
    """Raised for invalid indices, palettes, regions, or transition weights."""

    def __init__(
        self,
        code,
        message=None,
        *,
        coordinate=None,
        index=None,
        palette_length=None,
        weight=None,
    ):
        self.code = code
        self.coordinate = (
            tuple(coordinate) if coordinate is not None else None
        )
        # Expose the failing atlas position under a few intuitive names.
        self.coords = self.coordinate
        self.position = self.coordinate
        self.index = index
        self.palette_length = palette_length
        self.weight = weight
        super().__init__(message if message is not None else code)


class SpritePaletteSwap:
    """Apply palette mappings to indexed sprite images.

    ``swap`` has two transition modes:

    * replacement (the default when ``weights`` is omitted), and
    * alpha-weighted blending (when ``weights`` is supplied).

    Index zero is the transparent index and is never remapped.
    """

    _GRAYSCALE = tuple((value, value, value) for value in range(256))
    _GRAYSCALE_VERSION = "builtin-grayscale-v1"

    def __init__(
        self,
        atlas_version=1,
        palette_version=None,
        *,
        mode=None,
        region=None,
        width=None,
        height=None,
    ):
        self.atlas_version = atlas_version
        self.palette_version = palette_version
        self.default_mode = mode
        self.default_region = region
        self.default_width = width
        self.default_height = height
        self._cache = {}

    def swap(
        self,
        indices,
        palette,
        mapping=None,
        weights=None,
        region=None,
        *,
        width=None,
        height=None,
        mode=None,
        palette_version=None,
    ):
        """Return a palette-swapped image.

        ``indices`` may be a flat index buffer, nested rows, a :class:`bytes`
        object, or an image dictionary previously returned by :meth:`swap`.
        For a flat buffer, ``width`` may be supplied when ``region`` is not a
        single-row crop.  Without either, a flat buffer is treated as one row.
        """

        if region is None:
            region = self.default_region
        if width is None:
            width = self.default_width
        if height is None:
            height = self.default_height

        source, atlas_width, atlas_height = self._unpack_indices(
            indices, width=width, height=height
        )
        colors, resolved_palette_version, palette_token = self._resolve_palette(
            palette, palette_version
        )
        mapping_table = self._normalize_mapping(mapping)

        selected_mode = mode if mode is not None else self.default_mode
        if selected_mode is None:
            selected_mode = "blend" if weights is not None else "replace"
        selected_mode = str(selected_mode).lower()
        if selected_mode not in {"replace", "blend"}:
            raise PaletteError(
                "mode",
                f"mode must be 'replace' or 'blend', got {selected_mode!r}",
            )

        weight_input = self._normalize_weights(weights)
        crop = self._normalize_region(
            region, atlas_width, atlas_height, len(source)
        )
        source_crop = self._crop(source, atlas_width, crop)
        rx, ry, _, _ = crop

        warnings = []
        pixels = []
        for offset, source_index in enumerate(source_crop):
            local_x = offset % crop[2] if crop[2] else 0
            local_y = offset // crop[2] if crop[2] else 0
            coordinate = (rx + local_x, ry + local_y)

            if source_index == 0:
                if not colors:
                    raise self._palette_error(
                        source_index, coordinate, len(colors)
                    )
                pixels.append(colors[0])
                continue

            if source_index >= len(colors):
                raise self._palette_error(
                    source_index, coordinate, len(colors)
                )

            if source_index not in mapping_table:
                pixels.append(colors[source_index])
                warnings.append(
                    "missing mapping for index "
                    f"{source_index} at ({coordinate[0]}, {coordinate[1]})"
                )
                continue

            target_index = mapping_table[source_index]
            if target_index >= len(colors):
                raise self._palette_error(
                    target_index,
                    coordinate,
                    len(colors),
                    source_index=source_index,
                )

            if selected_mode == "replace":
                pixels.append(colors[target_index])
                continue

            weight = self._weight_for(
                weight_input,
                source_index,
                target_index,
                offset,
                len(source_crop),
                coordinate,
            )
            if weight <= 0.0:
                pixels.append(colors[source_index])
            elif weight >= 1.0:
                pixels.append(colors[target_index])
            else:
                pixels.append(
                    self._blend(
                        colors[source_index],
                        colors[target_index],
                        weight,
                    )
                )

        if not warnings:
            warnings.extend(self._mapping_warnings(mapping_table, len(colors)))

        region_width = crop[2]
        region_height = crop[3]
        image = {
            "indices": list(source_crop),
            "source_indices": list(source_crop),
            "pixels": list(pixels),
            "width": region_width,
            "height": region_height,
            "atlas_width": atlas_width,
            "atlas_height": atlas_height,
            "region": crop if region is not None else None,
            "atlas_version": self.atlas_version,
            "palette_version": resolved_palette_version,
        }

        cache_key = self._cache_key(
            source_crop,
            atlas_width,
            atlas_height,
            crop,
            selected_mode,
            mapping_table,
            weight_input,
            resolved_palette_version,
            palette_token,
        )

        cached = cache_key in self._cache
        if cached:
            result = self._copy_result(self._cache[cache_key])
        else:
            result = {
                "image": image,
                "pixels": list(pixels),
                "indices": list(source_crop),
                "cache_key": cache_key,
                "cached": False,
                "warnings": list(warnings),
                "palette_version": resolved_palette_version,
                "atlas_version": self.atlas_version,
            }
            self._cache[cache_key] = result
            result = self._copy_result(result)

        result["cached"] = cached
        return result

    @staticmethod
    def _mapping_warnings(mapping, palette_length):
        missing = [
            index
            for index in range(1, palette_length)
            if index not in mapping
        ]
        if not missing:
            return []
        shown = ", ".join(str(index) for index in missing[:8])
        if len(missing) > 8:
            shown += ", ..."
        return [f"mapping has no entry for palette indices: {shown}"]

    def restore(self, image):
        """Return the original indices held by a swapped image."""

        payload = image
        if isinstance(payload, Mapping) and "image" in payload:
            payload = payload["image"]

        if isinstance(payload, Mapping):
            indices = payload.get("source_indices")
            if indices is None:
                indices = payload.get("indices")
            if indices is None:
                raise PaletteError(
                    "restore",
                    "image does not contain source indices",
                )
        elif isinstance(payload, (bytes, bytearray, memoryview)):
            indices = list(bytes(payload))
        elif isinstance(payload, Sequence) and not isinstance(payload, str):
            indices = self._flatten_indices(payload)
        else:
            raise PaletteError(
                "restore",
                f"cannot restore indices from {type(payload).__name__}",
            )

        restored = list(indices)
        restored_image = {
            "indices": list(restored),
            "source_indices": list(restored),
            "pixels": list(restored),
        }
        if isinstance(payload, Mapping):
            for key in ("width", "height", "atlas_width", "atlas_height", "region"):
                if key in payload:
                    restored_image[key] = payload[key]
        return {
            "indices": restored,
            "image": restored_image,
            "restored": True,
        }

    def _unpack_indices(self, indices, *, width, height):
        if isinstance(indices, Mapping):
            if "source_indices" in indices:
                source = indices["source_indices"]
            elif "indices" in indices:
                source = indices["indices"]
            else:
                raise PaletteError(
                    "image_shape",
                    "image mapping must contain 'indices' or 'source_indices'",
                )
            if width is None:
                width = indices.get("width")
            if height is None:
                height = indices.get("height")
            if width is None:
                width = indices.get("atlas_width")
            if height is None:
                height = indices.get("atlas_height")
            indices = source

        if isinstance(indices, (bytes, bytearray, memoryview)):
            flat = list(bytes(indices))
            nested = False
        elif isinstance(indices, Sequence) and not isinstance(indices, str):
            if indices and isinstance(indices[0], Sequence) and not isinstance(
                indices[0], (str, bytes, bytearray)
            ):
                rows = [self._flatten_indices(row) for row in indices]
                flat = [value for row in rows for value in row]
                nested = True
                if width is None:
                    width = max((len(row) for row in rows), default=0)
                if height is None:
                    height = len(rows)
            else:
                flat = self._flatten_indices(indices)
                nested = False
        else:
            raise PaletteError(
                "image_shape",
                f"indices must be a sequence, got {type(indices).__name__}",
            )

        for offset, value in enumerate(flat):
            if width:
                coordinate = (offset % width, offset // width)
            else:
                coordinate = (offset, 0)
            flat[offset] = self._as_index(value, coordinate)

        if width is None:
            width = len(flat) if flat else 0
        width = self._as_dimension(width, "width")
        if width <= 0:
            width = max(1, len(flat))

        if height is None:
            height = math.ceil(len(flat) / width) if flat else 0
        height = self._as_dimension(height, "height")

        if nested and height < math.ceil(len(flat) / width):
            height = math.ceil(len(flat) / width)

        return flat, width, height

    def _flatten_indices(self, values):
        result = []
        for value in values:
            if isinstance(value, Sequence) and not isinstance(
                value, (str, bytes, bytearray)
            ):
                result.extend(self._flatten_indices(value))
            else:
                result.append(value)
        return result

    def _resolve_palette(self, palette, explicit_version):
        if palette is None:
            colors = list(self._GRAYSCALE)
            version = (
                explicit_version
                if explicit_version is not None
                else self.palette_version
            )
            if version is None:
                version = self._GRAYSCALE_VERSION
            token = hashlib.sha256(
                repr(colors).encode("utf-8")
            ).hexdigest()
            return colors, version, token

        if isinstance(palette, (str, bytes, bytearray)) or not isinstance(
            palette, Sequence
        ):
            raise PaletteError(
                "palette_type",
                f"palette must be a sequence, got {type(palette).__name__}",
            )

        colors = []
        for color in palette:
            if isinstance(color, (str, bytes, bytearray)):
                raise PaletteError("palette_type", "palette colours must be numeric")
            if isinstance(color, Sequence):
                channels = tuple(color)
            else:
                channels = (color,)
            normalized = []
            for channel in channels:
                try:
                    value = operator.index(channel)
                except TypeError:
                    try:
                        value = round(float(channel))
                    except (TypeError, ValueError):
                        raise PaletteError(
                            "palette_type",
                            f"invalid palette channel {channel!r}",
                        ) from None
                normalized.append(max(0, min(255, value)))
            colors.append(tuple(normalized))

        token = hashlib.sha256(repr(colors).encode("utf-8")).hexdigest()
        version = explicit_version
        if version is None:
            version = self.palette_version
        if version is None:
            version = token[:16]
        return colors, version, token

    def _normalize_mapping(self, mapping):
        if mapping is None:
            return {}
        if isinstance(mapping, Mapping):
            items = mapping.items()
        elif isinstance(mapping, Sequence) and not isinstance(
            mapping, (str, bytes, bytearray)
        ):
            items = enumerate(mapping)
        else:
            raise PaletteError(
                "mapping_type",
                f"mapping must be a mapping, got {type(mapping).__name__}",
            )

        normalized = {}
        for source, target in items:
            if target is None:
                continue
            source_index = self._as_index(source, None)
            target_index = self._as_index(target, None)
            normalized[source_index] = target_index
        return normalized

    def _normalize_weights(self, weights):
        if weights is None:
            return None
        if isinstance(weights, Mapping):
            normalized = {}
            for key, value in weights.items():
                index = self._as_index(key, None)
                normalized[index] = self._as_weight(value, index)
            return ("map", tuple(sorted(normalized.items())))
        if isinstance(weights, Sequence) and not isinstance(
            weights, (str, bytes, bytearray)
        ):
            values = tuple(
                self._as_weight(value, index)
                for index, value in enumerate(weights)
            )
            return ("sequence", values)
        return ("scalar", self._as_weight(weights, None))

    def _as_weight(self, value, index):
        if isinstance(value, bool):
            raise PaletteError(
                "weight_range",
                f"weight for index {index} must be numeric",
                index=index,
                weight=value,
            )
        try:
            weight = float(value)
        except (TypeError, ValueError):
            raise PaletteError(
                "weight_range",
                f"weight for index {index} must be numeric, got {value!r}",
                index=index,
                weight=value,
            ) from None
        if not math.isfinite(weight) or weight < 0.0 or weight > 1.0:
            raise PaletteError(
                "weight_range",
                f"weight {value!r} for index {index} must be within [0, 1]",
                index=index,
                weight=value,
            )
        return weight

    def _weight_for(
        self,
        weight_input,
        source_index,
        target_index,
        offset,
        pixel_count,
        coordinate,
    ):
        if weight_input is None:
            return 0.0
        kind, value = weight_input
        if kind == "scalar":
            return value
        if kind == "map":
            weights = dict(value)
            if source_index in weights:
                return weights[source_index]
            if target_index in weights:
                return weights[target_index]
            return 0.0

        values = value
        if len(values) == pixel_count:
            return values[offset]
        if source_index < len(values):
            return values[source_index]
        raise PaletteError(
            "weight_range",
            "no transition weight for index "
            f"{source_index} at ({coordinate[0]}, {coordinate[1]})",
            coordinate=coordinate,
            index=source_index,
        )

    def _normalize_region(self, region, width, height, flat_length):
        if region is None:
            effective_height = min(
                height if height else math.ceil(flat_length / width),
                math.ceil(flat_length / width),
            )
            return (0, 0, width, effective_height)

        if isinstance(region, Mapping):
            try:
                x = region["x"]
                y = region["y"]
                region_width = region.get("width", region.get("w"))
                region_height = region.get("height", region.get("h"))
            except KeyError as exc:
                raise PaletteError(
                    "region_range",
                    f"region is missing {exc.args[0]!r}",
                ) from None
        elif isinstance(region, Sequence) and not isinstance(
            region, (str, bytes, bytearray)
        ):
            if len(region) != 4:
                raise PaletteError(
                    "region_range",
                    "region must be (x, y, width, height)",
                )
            x, y, region_width, region_height = region
        else:
            raise PaletteError(
                "region_range",
                f"region must be a 4-item sequence, got {type(region).__name__}",
            )

        try:
            x = operator.index(x)
            y = operator.index(y)
            region_width = operator.index(region_width)
            region_height = operator.index(region_height)
        except TypeError:
            raise PaletteError(
                "region_range",
                "region coordinates and sizes must be integers",
            ) from None
        if region_width < 0 or region_height < 0:
            raise PaletteError(
                "region_range",
                "region width and height must not be negative",
            )

        x0 = max(0, min(x, width))
        y0 = max(0, min(y, height))
        x1 = max(x0, min(x + region_width, width))
        y1 = max(y0, min(y + region_height, height))
        return (x0, y0, x1 - x0, y1 - y0)

    def _crop(self, source, width, crop):
        x, y, region_width, region_height = crop
        if region_width == 0 or region_height == 0:
            return []
        result = []
        for row in range(y, y + region_height):
            start = row * width + x
            end = start + region_width
            result.extend(source[start:min(end, len(source))])
        return result

    def _cache_key(
        self,
        source,
        atlas_width,
        atlas_height,
        crop,
        mode,
        mapping,
        weights,
        palette_version,
        palette_token,
    ):
        weight_token = repr(weights)
        mapping_token = tuple(sorted(mapping.items()))
        payload = repr(
            (
                self.atlas_version,
                palette_version,
                palette_token,
                mode,
                mapping_token,
                weight_token,
                tuple(source),
                atlas_width,
                atlas_height,
                crop,
            )
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return (
            f"atlas={self.atlas_version}",
            f"palette={palette_version}",
            f"weights={weight_token}",
            f"content={digest}",
        )

    def _copy_result(self, result):
        copied = dict(result)
        copied["pixels"] = list(result["pixels"])
        copied["indices"] = list(result["indices"])
        copied["warnings"] = list(result["warnings"])
        copied["image"] = {
            key: (list(value) if isinstance(value, list) else value)
            for key, value in result["image"].items()
        }
        return copied

    def _as_index(self, value, coordinate):
        if isinstance(value, bool):
            raise PaletteError(
                "index_range",
                f"index {value!r} at {self._coordinate_text(coordinate)} "
                "is not an integer index",
                coordinate=coordinate,
                index=value,
            )
        try:
            index = operator.index(value)
        except TypeError:
            raise PaletteError(
                "index_range",
                f"index {value!r} at {self._coordinate_text(coordinate)} "
                "is not an integer index",
                coordinate=coordinate,
                index=value,
            ) from None
        if index < 0 or index > 255:
            raise PaletteError(
                "index_range",
                f"index {index} at {self._coordinate_text(coordinate)} "
                "is outside the supported 0..255 range",
                coordinate=coordinate,
                index=index,
            )
        return index

    def _as_dimension(self, value, name):
        try:
            dimension = operator.index(value)
        except TypeError:
            raise PaletteError(
                "image_shape",
                f"{name} must be an integer, got {value!r}",
            ) from None
        if dimension < 0:
            raise PaletteError(
                "image_shape",
                f"{name} must not be negative",
            )
        return dimension

    def _palette_error(
        self,
        index,
        coordinate,
        palette_length,
        *,
        source_index=None,
    ):
        detail = (
            f"palette index {index} at {self._coordinate_text(coordinate)} "
            f"is outside palette of length {palette_length}"
        )
        if source_index is not None:
            detail += f" (mapped from index {source_index})"
        return PaletteError(
            "palette_range",
            detail,
            coordinate=coordinate,
            index=index,
            palette_length=palette_length,
        )

    @staticmethod
    def _coordinate_text(coordinate):
        if coordinate is None:
            return "(unknown)"
        return f"({coordinate[0]}, {coordinate[1]})"

    @staticmethod
    def _components(color):
        channels = tuple(color)
        if len(channels) == 1:
            return (channels[0], channels[0], channels[0]), 255, False
        if len(channels) == 2:
            return (channels[0], channels[0], channels[0]), channels[1], True
        if len(channels) == 3:
            return channels, 255, False
        return channels[:3], channels[3], True

    @classmethod
    def _blend(cls, source_color, target_color, weight):
        if source_color == target_color:
            return source_color

        source_rgb, source_alpha, source_has_alpha = cls._components(source_color)
        target_rgb, target_alpha, target_has_alpha = cls._components(target_color)
        source_fraction = source_alpha / 255.0
        target_fraction = target_alpha / 255.0
        inverse = 1.0 - weight

        out_alpha_fraction = (
            source_fraction * inverse + target_fraction * weight
        )
        if out_alpha_fraction <= 0.0:
            rgb = (0, 0, 0)
        else:
            rgb = tuple(
                round(
                    (
                        source_rgb[channel] * source_fraction * inverse
                        + target_rgb[channel] * target_fraction * weight
                    )
                    / out_alpha_fraction
                )
                for channel in range(3)
            )
        rgb = tuple(max(0, min(255, value)) for value in rgb)

        if source_has_alpha or target_has_alpha:
            alpha = max(0, min(255, round(out_alpha_fraction * 255.0)))
            return rgb + (alpha,)
        return rgb
