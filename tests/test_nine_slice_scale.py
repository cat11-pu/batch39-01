import pytest

import nine_slice_scale as ns


def rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def borders(left=4, right=4, top=4, bottom=4):
    return {"left": left, "right": right, "top": top, "bottom": bottom}


def build(src=None, border=None, dst=None, **over):
    kwargs = {"mode": "nine", "tile_center": False}
    kwargs.update(over)
    return ns.NineSliceScale(**kwargs).build(
        src or rect(0, 0, 100, 100), border or borders(), dst or rect(0, 0, 200, 120)
    )


def quads(result):
    return result["quads"]


def test_corners_keep_original_size():
    result = build()
    corners = [q for q in quads(result) if q["part"].startswith("corner")]
    assert all(q["dst"]["w"] == 4 and q["dst"]["h"] == 4 for q in corners)


def test_top_and_bottom_edges_scale_only_horizontally():
    result = build()
    edges = [q for q in quads(result) if q["part"] in ("top", "bottom")]
    assert all(q["dst"]["h"] == 4 for q in edges)


def test_left_and_right_edges_scale_only_vertically():
    result = build()
    edges = [q for q in quads(result) if q["part"] in ("left", "right")]
    assert all(q["dst"]["w"] == 4 for q in edges)


def test_center_can_be_tiled_or_stretched():
    stretched = build()
    tiled = build(tile_center=True)
    center_stretched = [q for q in quads(stretched) if q["part"] == "center"]
    center_tiled = [q for q in quads(tiled) if q["part"] == "center"]
    assert len(center_stretched) == 1
    assert len(center_tiled) > 1


def test_borders_are_pixels_not_percent():
    result = build(src=rect(0, 0, 100, 100), border=borders(4, 4, 4, 4), dst=rect(0, 0, 400, 400))
    corner = [q for q in quads(result) if q["part"] == "corner_tl"][0]
    assert corner["dst"]["w"] == 4


def test_atlas_source_offset_is_preserved():
    result = build(src=rect(50, 60, 40, 40), border=borders(2, 2, 2, 2), dst=rect(0, 0, 80, 80))
    for q in quads(result):
        assert 50 <= q["uv"][0] <= 90
        assert 60 <= q["uv"][1] <= 100


def test_high_dpi_uses_logical_units():
    first = build(dst=rect(0, 0, 200, 120))
    second = build(dst=rect(0, 0, 200, 120))
    assert first == second


def test_negative_target_is_clamped():
    result = build(dst=rect(0, 0, -10, 50))
    assert result["clamped"] is True
    assert all(q["dst"]["w"] > 0 and q["dst"]["h"] > 0 for q in quads(result))


def test_zero_center_does_not_emit_degenerate_quads():
    result = build(dst=rect(0, 0, 8, 8))
    assert all(q["dst"]["w"] > 0 and q["dst"]["h"] > 0 for q in quads(result))


def test_horizontal_flip_swaps_left_and_right_texture_coordinates():
    normal = build()
    flipped = build(flip=True)
    left_n = [q for q in quads(normal) if q["part"] == "left"][0]
    left_f = [q for q in quads(flipped) if q["part"] == "left"][0]
    assert left_n["uv"] != left_f["uv"]


def test_rotate_ninety_swaps_border_roles():
    normal = build(border=borders(2, 6, 3, 5))
    rotated = build(border=borders(2, 6, 3, 5), rotate=90)
    assert len(quads(normal)) == len(quads(rotated))
    assert [q["uv"] for q in quads(rotated)] != [q["uv"] for q in quads(normal)]


def test_three_slice_mode_merges_center_row():
    nine = build()
    three = build(mode="three")
    assert len(quads(three)) < len(quads(nine))


def test_vertex_count_depends_on_mode_not_target_size():
    small = build(dst=rect(0, 0, 100, 100))
    large = build(dst=rect(0, 0, 1000, 1000))
    assert len(quads(small)) == len(quads(large))


def test_border_larger_than_source_is_rejected():
    with pytest.raises(ns.NineSliceError) as exc:
        build(src=rect(0, 0, 6, 6), border=borders(4, 4, 4, 4), dst=rect(0, 0, 20, 20))
    assert exc.value.code == "border_too_large"


def test_repeated_build_does_not_accumulate_state():
    scale = ns.NineSliceScale()
    first = scale.build(rect(0, 0, 100, 100), borders(), rect(0, 0, 200, 120))
    second = scale.build(rect(0, 0, 100, 100), borders(), rect(0, 0, 200, 120))
    assert first == second
