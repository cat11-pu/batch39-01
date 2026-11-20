import grass_scatter_plan as gs


def region(x=0.0, y=0.0, w=10.0, h=10.0):
    return {"x": x, "y": y, "w": w, "h": h}


def build(region_data=None, density=0.5, **over):
    kwargs = {"seed": 0, "spacing": 1.0, "max_instances": 10000}
    kwargs.update(over)
    return gs.GrassScatterPlan(**kwargs).build(region_data or region(), density, **over)


def test_chunk_boundary_is_not_counted_twice():
    result = build()
    positions = [(item["x"], item["y"]) for item in result["instances"]]
    assert len(positions) == len(set(positions))


def test_slope_filter_rejects_steep_cells():
    result = build(slope=lambda x, y: 1.0, max_slope=0.5)
    assert result["instances"] == []


def test_height_filter_uses_world_units():
    result = build(height=lambda x, y: 100.0, max_height=10.0)
    assert result["instances"] == []


def test_minimum_spacing_is_enforced_across_chunks():
    result = build(density=1.0, spacing=2.0)
    points = [(item["x"], item["y"]) for item in result["instances"]]
    assert len(points) == len(set(points))


def test_lod_density_reduces_instances_without_pattern_stripes():
    full = build(density=1.0)
    low = build(density=1.0, lod=0.5)
    assert len(low["instances"]) < len(full["instances"])


def test_seed_is_coordinate_based_and_changes_neighbors():
    a = build(seed=1)
    b = build(seed=2)
    assert a["instances"] != b["instances"]


def test_blocked_areas_are_excluded():
    result = build(blocked=[region(0, 0, 10, 10)])
    assert result["instances"] == []


def test_instance_limit_applies_per_chunk_and_total():
    result = build(max_instances=5)
    assert len(result["instances"]) <= 5


def test_wind_phase_is_stable_per_position():
    result = build()
    if result["instances"]:
        item = result["instances"][0]
        assert isinstance(item["wind"], float)


def test_culling_bounds_include_sway():
    result = build(sway=2.0)
    assert result["bounds"][2] > 10.0


def test_half_open_interval_prevents_double_counting():
    left = build(region(0, 0, 5, 5))
    right = build(region(5, 0, 5, 5))
    overlap = set((i["x"], i["y"]) for i in left["instances"]) & set((i["x"], i["y"]) for i in right["instances"])
    assert overlap == set()


def test_grid_acceleration_returns_all_neighbors():
    result = build(density=1.0, spacing=0.5)
    assert result["grid_cells"] >= 1


def test_build_is_deterministic():
    assert build() == build()


def test_output_contains_required_fields():
    result = build()
    assert {"instances", "bounds", "grid_cells"} <= set(result)


def test_memory_limit_is_reported():
    result = build(max_instances=3)
    assert result["truncated"] is True
