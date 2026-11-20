import pytest

import blend_shape_morph as bm


def vertex(x=0.0, y=0.0, z=0.0):
    return {"pos": (x, y, z), "normal": (0.0, 0.0, 1.0), "tangent": (1.0, 0.0, 0.0)}


def base():
    return [vertex(), vertex(1, 0, 0), vertex(0, 1, 0)]


def target(name="smile", indices=None, delta=(0.1, 0.0, 0.0), normal=(0.0, 0.0, 0.1), tangent=(0.0, 0.0, 0.0)):
    return {"name": name, "indices": indices or [0], "delta_pos": [delta] * len(indices or [0]), "delta_normal": [normal] * len(indices or [0]), "delta_tangent": [tangent] * len(indices or [0])}


def morph(targets=None, **over):
    kwargs = {"budget": 8}
    kwargs.update(over)
    return bm.BlendShapeMorph(base(), targets or [target()], **kwargs)


def test_weights_are_normalized_before_apply():
    result = morph().apply({"smile": 2.0, "frown": 2.0})
    assert abs(sum(result["weights"].values()) - 1.0) < 1e-6


def test_negative_weights_are_preserved():
    result = morph().apply({"smile": -0.5})
    assert result["weights"]["smile"] == -0.5


def test_sparse_target_keeps_other_vertices_at_base():
    result = morph().apply({"smile": 1.0})
    assert result["vertices"][1]["pos"] == (1.0, 0.0, 0.0)


def test_normals_are_recomputed_and_renormalized():
    result = morph().apply({"smile": 1.0})
    assert abs(sum(v * v for v in result["vertices"][0]["normal"]) - 1.0) < 1e-6


def test_out_of_range_index_is_rejected():
    with pytest.raises(bm.MorphError):
        morph([target(indices=[99])]).apply({"smile": 1.0})


def test_weights_are_accumulated_in_double_precision():
    result = morph().apply({"smile": 0.1})
    assert abs(result["vertices"][0]["pos"][0] - 0.01) < 1e-9


def test_result_is_clamped_to_bounding_box():
    result = morph().apply({"smile": 1.0}, bbox=((-0.01, -0.01, -0.01), (0.01, 0.01, 0.01)))
    assert result["clamped"] is True


def test_switching_targets_clears_old_weight():
    m = morph()
    m.apply({"smile": 1.0})
    result = m.apply({})
    assert result["weights"] == {}


def test_target_budget_batches_without_changing_result():
    targets = [target("t%d" % i, indices=[i % 3]) for i in range(10)]
    result = morph(targets, budget=4).apply({"t0": 0.1, "t5": 0.2})
    assert result["batches"] > 1


def test_repeated_apply_is_consistent():
    m = morph()
    first = m.apply({"smile": 0.4})
    second = m.apply({"smile": 0.4})
    assert first["vertices"] == second["vertices"]


def test_additive_mode_sums_deltas():
    result = morph().apply({"smile": 1.0}, mode="additive")
    assert result["vertices"][0]["pos"][0] == pytest.approx(0.1)


def test_relative_mode_interpolates_from_base():
    result = morph().apply({"smile": 0.5}, mode="relative")
    assert result["vertices"][0]["pos"][0] == pytest.approx(0.05)


def test_tangents_are_transformed():
    result = morph().apply({"smile": 1.0})
    assert result["vertices"][0]["tangent"] != (1.0, 0.0, 0.0) or result["tangent_updated"] is True


def test_reset_restores_base_mesh():
    m = morph()
    m.apply({"smile": 1.0})
    assert m.reset()["vertices"][0]["pos"] == (0.0, 0.0, 0.0)


def test_duplicate_indices_are_rejected():
    with pytest.raises(bm.MorphError):
        morph([target(indices=[0, 0])])
