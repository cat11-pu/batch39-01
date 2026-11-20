import math

import visibility_fan as vf


def fan(**over):
    kwargs = {"radius": 100, "angle": 360}
    kwargs.update(over)
    return vf.VisibilityFan(**kwargs)


def wall(a, b, owner="w-1"):
    return {"a": a, "b": b, "owner": owner}


def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    for i in range(len(polygon) - 1):
        x1, y1 = polygon[i]
        x2, y2 = polygon[i + 1]
        if (y1 > y) != (y2 > y):
            at = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < at:
                inside = not inside
    return inside


def test_corner_seam_does_not_leak_light():
    origin = (10.0, 10.0)
    walls = [wall((20, 0), (20, 20)), wall((20, 20), (0, 20))]
    result = fan().compute(origin, walls)
    assert not point_in_polygon((30, 30), result["polygon"])


def test_thin_wall_blocks_ray():
    origin = (5.0, 5.0)
    walls = [wall((10, 0), (10, 10))]
    result = fan().compute(origin, walls)
    assert not point_in_polygon((15, 5), result["polygon"])


def test_overlapping_walls_are_deduplicated():
    walls = [wall((10, 0), (10, 10)), wall((10, 0), (10, 10))]
    result = fan().compute((5.0, 5.0), walls)
    assert len(result["polygon"]) == len(set(result["polygon"]))


def test_origin_inside_wall_returns_empty_area():
    walls = [wall((0, 0), (10, 10), "box")]
    result = fan().compute((5.0, 5.0), walls, blockers={"box"})
    assert result["polygon"] == []


def test_full_circle_closes_polygon():
    result = fan(angle=360).compute((50.0, 50.0), [])
    assert result["polygon"][0] == result["polygon"][-1]


def test_attenuation_is_reported_per_vertex():
    result = fan().compute((0.0, 0.0), [])
    assert len(result["attenuation"]) == len(result["polygon"])


def test_box_faces_are_grouped_by_owner():
    walls = [wall((10, 0), (10, 10), "box"), wall((10, 0), (0, 0), "box")]
    result = fan().compute((5.0, 5.0), walls, blockers={"box"})
    assert result["occluders"] == 1


def test_tiny_origin_shift_keeps_vertex_count():
    walls = [wall((10, 0), (10, 10))]
    a = fan().compute((5.0, 5.0), walls)
    b = fan().compute((5.01, 5.0), walls)
    assert len(a["polygon"]) == len(b["polygon"])


def test_many_walls_are_reused_between_calls():
    walls = [wall((20, i * 0.1), (20, i * 0.1 + 0.05)) for i in range(5000)]
    f = fan()
    first = f.compute((10.0, 10.0), walls)
    second = f.compute((10.0, 10.0), walls)
    assert first == second


def test_collinear_vertices_are_removed():
    result = fan().compute((0.0, 0.0), [])
    points = result["polygon"]
    assert len(points) == len(set(points))


def test_duplicate_endpoints_are_merged():
    walls = [wall((10, 0), (10, 10)), wall((10, 10), (20, 10))]
    result = fan().compute((5.0, 5.0), walls)
    assert len(result["polygon"]) == len(set(result["polygon"]))


def test_cone_boundary_rays_are_added():
    result = fan(angle=90).compute((0.0, 0.0), [])
    angles = [math.degrees(math.atan2(y, x)) for x, y in result["polygon"]]
    assert max(angles) - min(angles) <= 90.1


def test_radius_clips_vertices():
    result = fan(radius=10).compute((0.0, 0.0), [])
    for x, y in result["polygon"]:
        assert math.hypot(x, y) <= 10.001


def test_blockers_are_deduplicated_by_id():
    walls = [wall((10, 0), (10, 5), "a"), wall((10, 5), (10, 10), "a")]
    result = fan().compute((0.0, 5.0), walls, blockers={"a"})
    assert result["occluders"] == 1


def test_result_is_deterministic():
    walls = [wall((10, 0), (10, 10)), wall((20, 0), (20, 10))]
    assert fan().compute((5.0, 5.0), walls) == fan().compute((5.0, 5.0), walls)
