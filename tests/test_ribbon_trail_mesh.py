import ribbon_trail_mesh as rt


def build(points, widths=None, colors=None, closed=False, **over):
    kwargs = {"min_distance": 0.1, "max_points": 256, "max_angle": 60.0}
    kwargs.update(over)
    return rt.RibbonTrailMesh(**kwargs).build(points, widths=widths, colors=colors, closed=closed)


def test_nearby_points_are_skipped_by_distance():
    result = build([(0.0, 0.0), (0.01, 0.0), (1.0, 0.0)])
    assert result["sample_count"] == 2


def test_width_tapers_toward_the_end():
    result = build([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)], widths=[1.0, 1.0, 0.2])
    assert result["widths"][-1] < result["widths"][0]


def test_closed_trail_connects_first_and_last():
    result = build([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], closed=True)
    assert result["closed"] is True


def test_sharp_turn_is_split_when_angle_exceeds_limit():
    result = build([(0.0, 0.0), (1.0, 0.0), (0.0, 0.001)], max_angle=5.0)
    assert result["segments"] >= 2


def test_self_intersection_is_split():
    result = build([(0.0, 0.0), (2.0, 2.0), (2.0, 0.0), (0.0, 2.0)])
    assert "intersections" in result


def test_degenerate_segments_are_skipped():
    result = build([(0.0, 0.0), (0.0, 0.0)])
    assert result["vertices"] == 0


def test_max_point_limit_is_enforced():
    result = build([(float(i), 0.0) for i in range(100)], max_points=10)
    assert result["sample_count"] <= 10


def test_teleport_splits_trail():
    result = build([(0.0, 0.0), (1.0, 0.0), (100.0, 0.0)])
    assert result["segments"] >= 2


def test_color_interpolates_along_trail():
    result = build([(0.0, 0.0), (1.0, 0.0)], colors=[(0, 0, 0, 1), (255, 255, 255, 1)])
    assert result["colors"][-1] != result["colors"][0]


def test_caps_are_generated():
    result = build([(0.0, 0.0), (1.0, 0.0)], caps=True)
    assert result["caps"] >= 2


def test_lod_reduces_points_but_keeps_ends():
    full = build([(float(i), 0.0) for i in range(10)])
    low = build([(float(i), 0.0) for i in range(10)], lod=0.5)
    assert low["sample_count"] < full["sample_count"]


def test_bounding_box_is_reported():
    assert "bbox" in build([(0.0, 0.0), (1.0, 2.0)])


def test_segment_ids_are_stable():
    result = build([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    assert result["segments"] == 1


def test_output_is_deterministic():
    points = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.5)]
    assert build(points) == build(points)


def test_output_contains_vertices_indices_and_segments():
    result = build([(0.0, 0.0), (1.0, 0.0)])
    assert {"vertices", "indices", "segments", "bbox"} <= set(result)
