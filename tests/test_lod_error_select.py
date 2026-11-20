import lod_error_select as lod


def model(lods=None, forced=None, radius=1.0, triangles=None):
    return {
        "id": "m-1",
        "center": (0.0, 0.0, 0.0),
        "radius": radius,
        "lods": lods or [
            {"level": 0, "geo_err": 0.0, "triangles": 1000},
            {"level": 1, "geo_err": 0.05, "triangles": 400},
            {"level": 2, "geo_err": 0.2, "triangles": 100},
        ],
        "forced": forced,
        "triangles": triangles,
    }


def camera(pos=(0.0, 0.0, 10.0), fov=60.0, height=1080, forward=(0.0, 0.0, -1.0)):
    return {"pos": pos, "fov": fov, "height": height, "forward": forward}


def choose(m=None, c=None, **over):
    kwargs = {"max_px": 2.0, "hysteresis": 0.1}
    kwargs.update(over)
    return lod.LodErrorSelect(**kwargs).select(m or model(), c or camera())


def test_distance_alone_does_not_choose_the_level():
    near = choose(model(radius=0.01))
    far = choose(model(radius=10.0))
    assert near["lod"] != far["lod"] or near["err_px"] != far["err_px"]


def test_resolution_changes_projected_error():
    low = choose(c=camera(height=720))
    high = choose(c=camera(height=2160))
    assert high["err_px"] > low["err_px"]


def test_field_of_view_changes_projected_error():
    wide = choose(c=camera(fov=90))
    narrow = choose(c=camera(fov=30))
    assert narrow["err_px"] > wide["err_px"]


def test_model_behind_camera_is_culled():
    result = choose(c=camera(pos=(0.0, 0.0, -10.0)))
    assert result["culled"] is True


def test_hysteresis_prevents_flicker_at_boundary():
    selector = lod.LodErrorSelect(max_px=2.0, hysteresis=0.1)
    first = selector.select(model(), camera())
    second = selector.select(model(), camera(pos=(0.0, 0.0, 10.01)))
    assert second["lod"] == first["lod"]


def test_crossfade_weight_is_reported():
    result = choose()
    assert 0.0 <= result["weight"] <= 1.0


def test_forced_level_wins_over_distance():
    result = choose(model(forced=2))
    assert result["lod"] == 2


def test_zero_distance_does_not_divide_by_zero():
    result = choose(c=camera(pos=(0.0, 0.0, 0.0)))
    assert result["lod"] is not None


def test_far_distance_uses_last_level():
    result = choose(c=camera(pos=(0.0, 0.0, 1e6)))
    assert result["lod"] == 2


def test_only_visible_models_are_processed():
    selector = lod.LodErrorSelect()
    results = selector.select_many([model(), model()], camera())
    assert all(item["culled"] is False for item in results)


def test_screen_error_formula_is_exposed():
    result = choose()
    assert "err_px" in result


def test_equal_error_prefers_fewer_triangles():
    m = model(lods=[{"level": 0, "geo_err": 0.1, "triangles": 100}, {"level": 1, "geo_err": 0.1, "triangles": 50}])
    assert choose(m=m)["lod"] == 1


def test_hysteresis_buffer_is_configurable():
    a = choose(hysteresis=0.0)
    b = choose(hysteresis=0.5)
    assert a["lod"] == b["lod"]


def test_crossfade_weight_is_zero_when_fully_switched():
    result = choose(model(forced=0))
    assert result["weight"] == 0.0


def test_output_is_stable_for_same_input():
    m = model()
    c = camera()
    assert choose(m=m, c=c) == choose(m=m, c=c)
