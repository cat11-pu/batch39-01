import decal_projection as dp


def decal(did="d-1", pos=(0.0, 0.0, 0.0), normal=(0.0, 1.0, 0.0), size=1.0, priority=0, created=0):
    return {"id": did, "pos": pos, "normal": normal, "size": size, "priority": priority, "created": created}


def patch(pid="p-1", normal=(0.0, 1.0, 0.0), uv=(0.0, 0.0, 1.0, 1.0)):
    return {"id": pid, "normal": normal, "uv": uv, "triangles": [((0, 0), (1, 0), (0, 1))]}


def plan(decals=None, patches=None, **over):
    kwargs = {"max_angle": 60.0, "padding": 4, "max_tasks": 64}
    kwargs.update(over)
    return dp.DecalBakePlanner(**kwargs).plan(decals or [decal()], patches or [patch()])


def test_slope_uses_patch_normal_not_flat_plane():
    result = plan(patches=[patch(normal=(0.0, 0.7, 0.7))])
    assert result["tasks"][0]["normal"] == (0.0, 0.7, 0.7)


def test_back_facing_patch_is_rejected():
    result = plan(decals=[decal(normal=(0.0, -1.0, 0.0))], patches=[patch()])
    assert result["tasks"] == []


def test_triangle_boundary_is_clipped():
    result = plan()
    assert "clip" in result["tasks"][0] or result["tasks"][0]["area"] <= 1.0


def test_seam_padding_is_reserved():
    result = plan(padding=8)
    assert result["tasks"][0]["padding"] == 8


def test_overlapping_decals_sort_stably():
    result = plan(decals=[decal("b", created=2), decal("a", created=1)])
    assert [item["id"] for item in result["tasks"]] == ["a", "b"]


def test_alpha_blend_weight_is_reported():
    assert "blend" in plan()["tasks"][0]


def test_density_mismatch_triggers_resample():
    result = plan(decals=[decal(size=100)], patches=[patch()])
    assert result["tasks"][0].get("resampled") is True


def test_cross_patch_uv_offset_is_applied():
    result = plan(patches=[patch(uv=(0.5, 0.5, 1.0, 1.0))])
    assert result["tasks"][0]["uv"] != (0.0, 0.0, 1.0, 1.0)


def test_angle_fade_is_reported():
    assert "fade" in plan()["tasks"][0]


def test_out_of_bounds_write_is_rejected():
    result = plan(patches=[patch(uv=(0.9, 0.9, 1.0, 1.0))], padding=8)
    assert result["warnings"]


def test_priority_orders_tasks():
    result = plan(decals=[decal("a", priority=1), decal("b", priority=9)])
    assert result["tasks"][0]["id"] == "b"


def test_task_fields_are_complete():
    task = plan()["tasks"][0]
    assert {"id", "rect", "uv", "blend", "fade"} <= set(task)


def test_result_is_reproducible():
    assert plan() == plan()


def test_warnings_are_returned():
    assert isinstance(plan()["warnings"], list)


def test_input_is_not_mutated():
    decals = [decal()]
    patches = [patch()]
    plan(decals, patches)
    assert decals[0]["size"] == 1.0
    assert patches[0]["normal"] == (0.0, 1.0, 0.0)
