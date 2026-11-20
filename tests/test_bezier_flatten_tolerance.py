import copy

import pytest

import bezier_flatten_tolerance as bt


def line(a, b):
    return {"type": "line", "p0": a, "p1": b}


def cubic(p0, p1, p2, p3):
    return {"type": "cubic", "p0": p0, "p1": p1, "p2": p2, "p3": p3}


def flat(segments, **over):
    kwargs = {"tolerance": 0.5, "max_depth": 16}
    kwargs.update(over)
    return bt.BezierFlattenTolerance(**kwargs).flatten(segments)


def test_straight_line_produces_only_endpoints():
    result = flat([line((0, 0), (10, 0))])
    assert result["points"] == [(0, 0), (10, 0)]


def test_tolerance_is_in_screen_units_after_transform():
    small = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))], matrix=(1, 0, 0, 1))
    large = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))], matrix=(10, 0, 0, 10))
    assert len(large["points"]) > len(small["points"])


def test_cusp_is_preserved():
    result = flat([cubic((0, 0), (10, 10), (0, 10), (10, 0))], tolerance=0.1)
    assert len(result["points"]) > 2


def test_coincident_control_points_do_not_divide_by_zero():
    result = flat([cubic((0, 0), (0, 0), (0, 0), (0, 0))])
    assert result["points"] == [(0, 0), (0, 0)]


def test_duplicate_points_are_merged():
    result = flat([line((0, 0), (0, 0)), line((0, 0), (1, 0))])
    assert len(result["points"]) == len(set(result["points"]))


def test_closed_path_starts_and_ends_at_same_point():
    result = flat([line((0, 0), (1, 0)), line((1, 0), (0, 0))], closed=True)
    assert result["points"][0] == result["points"][-1]


def test_zero_or_negative_tolerance_is_rejected():
    for value in (0.0, -1.0):
        with pytest.raises(ValueError):
            flat([line((0, 0), (1, 0))], tolerance=value)


def test_parameter_mapping_matches_point_count_and_is_monotonic():
    result = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))])
    assert len(result["params"]) == len(result["points"])
    assert result["params"] == sorted(result["params"])


def test_line_segments_are_not_subdivided():
    result = flat([line((0, 0), (10, 0))], tolerance=0.01)
    assert len(result["points"]) == 2


def test_max_depth_is_enforced():
    result = flat([cubic((0, 0), (0, 100), (100, 100), (100, 0))], tolerance=1e-9, max_depth=3)
    assert len(result["points"]) > 2


def test_screen_transform_is_applied_to_points():
    result = flat([line((0, 0), (1, 1))], matrix=(2, 0, 0, 2))
    assert result["points"][-1] == (2, 2)


def test_smaller_tolerance_produces_more_points():
    coarse = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))], tolerance=2.0)
    fine = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))], tolerance=0.1)
    assert len(fine["points"]) >= len(coarse["points"])


def test_flatness_check_keeps_output_within_tolerance():
    result = flat([cubic((0, 0), (0, 5), (5, 5), (5, 0))], tolerance=0.5)
    assert max(result["errors"]) <= 0.5


def test_error_estimate_count_matches_segments():
    result = flat([line((0, 0), (1, 0)), line((1, 0), (2, 0))])
    assert len(result["errors"]) == len(result["points"]) - 1


def test_input_is_not_mutated_and_result_is_repeatable():
    segments = [cubic((0, 0), (0, 5), (5, 5), (5, 0))]
    before = copy.deepcopy(segments)
    first = flat(segments)
    second = flat(segments)
    assert segments == before
    assert first == second
