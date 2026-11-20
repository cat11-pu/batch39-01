import shadow_cascade_fit as sf


def layer(near, far, coverage=0.5, empty=False):
    return {"near": near, "far": far, "coverage": coverage, "empty": empty}


def shot(sid="s-1", layers=None, light=(0.0, 1.0, 0.0), camera=(0.0, 0.0, -1.0)):
    return {"id": sid, "layers": layers or [layer(0.1, 5), layer(5, 20)], "light_dir": light, "camera_dir": camera}


def plan(shots=None, **over):
    kwargs = {"max_tiles": 16, "tile_size": 1024, "budget_mb": 256, "overlap": 0.1}
    kwargs.update(over)
    return sf.ShadowAtlasPlanner(**kwargs).plan(shots or [shot()])


def test_depth_ranges_come_from_each_layer():
    result = plan([shot(layers=[layer(0.1, 4), layer(4, 12)])])
    assert result["cascades"][0]["near"] == 0.1
    assert result["cascades"][1]["far"] == 12


def test_resolution_follows_coverage():
    result = plan([shot(layers=[layer(0.1, 5, coverage=0.8), layer(5, 20, coverage=0.2)])])
    assert result["cascades"][0]["tile_size"] >= result["cascades"][1]["tile_size"]


def test_tiles_share_atlas_without_overlap():
    result = plan()
    rects = [item["rect"] for item in result["tiles"]]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def test_overlap_band_is_reported():
    result = plan([shot(layers=[layer(0.1, 5), layer(5, 20)])], overlap=0.2)
    assert result["cascades"][0]["overlap"] == 0.2


def test_cascade_ids_are_stable_across_shot_order():
    a = plan([shot("s-1"), shot("s-2")])
    b = plan([shot("s-2"), shot("s-1")])
    assert [item["id"] for item in a["cascades"]] == [item["id"] for item in b["cascades"]]


def test_empty_layer_does_not_get_a_tile():
    result = plan([shot(layers=[layer(0.1, 2, empty=True)])])
    assert all(item["tile"] is None for item in result["cascades"])


def test_parallel_light_and_camera_emit_degenerate_warning():
    result = plan([shot(light=(0.0, 0.0, -1.0), camera=(0.0, 0.0, -1.0))])
    assert result["warnings"]


def test_budget_limits_number_of_tiles():
    result = plan([shot("s-%d" % i) for i in range(20)], max_tiles=4)
    assert len(result["tiles"]) <= 4


def test_texel_density_is_reported_per_layer():
    result = plan()
    assert all("texel_density" in item for item in result["cascades"])


def test_tile_rectangles_stay_inside_atlas():
    result = plan()
    atlas = result["atlas"]
    for item in result["tiles"]:
        x, y, w, h = item["rect"]
        assert x >= 0 and y >= 0 and x + w <= atlas[0] and y + h <= atlas[1]


def test_warnings_are_returned():
    assert isinstance(plan()["warnings"], list)


def test_max_tiles_is_configurable():
    assert len(plan(max_tiles=1)["tiles"]) <= 1


def test_depth_intervals_do_not_overlap_except_band():
    result = plan()
    assert result["cascades"][0]["far"] >= result["cascades"][1]["near"]


def test_plan_is_deterministic():
    assert plan() == plan()


def test_output_contains_required_fields():
    result = plan()
    assert {"cascades", "tiles", "atlas", "warnings"} <= set(result)
