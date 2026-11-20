import pytest

import sprite_outline_mesh as so


def mask(rows):
    height = len(rows)
    width = len(rows[0])
    return [value for row in rows for value in row], width, height


def build(rows, **over):
    alpha, width, height = mask(rows)
    kwargs = {"threshold": 0.5, "tolerance": 0.75, "max_vertices": 4096, "max_components": 64}
    kwargs.update(over)
    return so.SpriteOutlineMesh(**kwargs).build(alpha, width, height)


def test_diagonal_pixels_are_connected():
    result = build([[1, 0], [0, 1]])
    assert len(result["components"]) == 1


def test_semi_transparent_edge_uses_configurable_threshold():
    high = build([[0.6, 0.4]], threshold=0.5)
    low = build([[0.6, 0.4]], threshold=0.7)
    assert len(high["components"]) == 1
    assert low["components"] == []


def test_hole_gets_its_own_inner_loop():
    result = build([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    component = result["components"][0]
    assert len(component["holes"]) == 1
    assert result["holes"] == 1


def test_collinear_points_are_simplified():
    result = build([[1, 1, 1]])
    assert result["vertices"] <= 4


def test_vertex_limit_is_enforced():
    rows = [[1] * 40 for _ in range(40)]
    with pytest.raises(so.OutlineError) as exc:
        build(rows, max_vertices=8)
    assert exc.value.code == "too_many_vertices"


def test_expanded_concave_shape_does_not_go_negative():
    rows = [
        [1, 1, 0, 0],
        [1, 1, 0, 0],
        [0, 0, 1, 1],
        [0, 0, 1, 1],
    ]
    result = build(rows, expand=2)
    for component in result["components"]:
        assert component["area"] >= 0


def test_atlas_region_limits_sampling():
    rows = [
        [0, 0, 0, 0, 0, 0],
        [0, 1, 1, 0, 0, 0],
        [0, 1, 1, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
    ]
    alpha, width, height = mask(rows)
    result = so.SpriteOutlineMesh().build(alpha, width, height, region=(1, 1, 2, 2))
    xs = [point[0] for component in result["components"] for loop in [component["outer"]] for point in loop]
    assert min(xs) >= 1 and max(xs) <= 2


def test_output_unit_is_source_pixels():
    result = build([[1, 1]])
    assert result["unit"] == "source_pixel"


def test_two_blobs_are_grouped_as_two_components():
    result = build([[1, 0, 1]])
    assert len(result["components"]) == 2


def test_traversal_start_does_not_change_result():
    rows = [[1, 1, 1], [1, 1, 0], [1, 1, 1]]
    assert build(rows) == build(rows)


def test_tolerance_reduces_vertex_count():
    rows = [[1] * 30 + [0] * 5]
    loose = build(rows, tolerance=4.0)
    tight = build(rows, tolerance=0.1)
    assert loose["vertices"] <= tight["vertices"]


def test_inner_loop_winding_is_opposite_to_outer():
    result = build([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    component = result["components"][0]
    assert component["outer_area"] > 0
    assert component["holes"][0]["area"] < 0


def test_component_area_is_never_negative():
    result = build([[1, 1, 0], [1, 0, 1], [0, 1, 1]])
    assert all(component["area"] >= 0 for component in result["components"])


def test_component_limit_is_enforced():
    with pytest.raises(so.OutlineError) as exc:
        build([[1, 0, 1, 0, 1]], max_components=2)
    assert exc.value.code == "too_many_components"


def test_empty_mask_returns_empty_result():
    alpha, width, height = mask([[0, 0], [0, 0]])
    result = so.SpriteOutlineMesh().build(alpha, width, height)
    assert result["components"] == []
    assert result["vertices"] == 0
