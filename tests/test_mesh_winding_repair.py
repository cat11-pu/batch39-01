import copy

import pytest

import mesh_winding_repair as mw


def vert(x, y, z, nx=0.0, ny=0.0, nz=1.0, u=0.0, v=0.0):
    return {"pos": (x, y, z), "normal": (nx, ny, nz), "uv": (u, v)}


def mesh():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(0, 0, 1)]
    indices = [(0, 1, 2), (0, 2, 3), (0, 1, 3)]
    return vertices, indices


def repair(vertices=None, indices=None, **over):
    if vertices is None:
        vertices, indices = mesh()
    return mw.MeshWindingRepair().repair(vertices, indices, **over)


def test_inconsistent_winding_is_flipped():
    result = repair()
    assert result["flipped"] >= 1


def test_zero_area_triangles_are_removed():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(2, 0, 0)]
    result = repair(vertices, [(0, 1, 2), (0, 1, 1)])
    assert 1 in result["removed"]


def test_duplicate_vertices_are_welded():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(0, 0, 0)]
    result = repair(vertices, [(0, 1, 2), (3, 1, 2)])
    assert result["welded"] >= 1


def test_out_of_range_indices_are_removed():
    result = repair(indices=[(0, 1, 99)])
    assert result["removed"]


def test_uv_seam_vertices_are_not_welded():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(0, 0, 0, u=1.0)]
    result = repair(vertices, [(0, 1, 2), (3, 1, 2)])
    assert result["welded"] == 0


def test_material_groups_keep_their_order():
    groups = [["a"], ["b"]]
    result = repair(groups=groups)
    assert result["groups"] == groups


def test_empty_mesh_returns_empty_stats():
    result = repair([], [])
    assert result["indices"] == []
    assert result["stats"]["triangles"] == 0


def test_non_manifold_edges_are_listed_not_flipped():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(0, 0, 1)]
    result = repair(vertices, [(0, 1, 2), (0, 1, 3), (0, 1, 2)])
    assert result["non_manifold"]


def test_outlier_vertices_do_not_crash_bounds():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(1e9, 1e9, 1e9)]
    result = repair(vertices, [(0, 1, 2)])
    assert result["stats"]["triangles"] == 1


def test_normals_stay_in_same_direction():
    result = repair()
    for normal in result["normals"]:
        assert normal[2] >= 0


def test_sixteen_bit_index_overflow_is_reported():
    vertices = [vert(i, 0, 0) for i in range(70000)]
    with pytest.raises(ValueError):
        mw.MeshWindingRepair().repair(vertices, [(0, 1, 69999)], index_bits=16)


def test_stats_report_before_and_after():
    result = repair()
    assert "before" in result["stats"] and "after" in result["stats"]


def test_input_arrays_are_not_mutated():
    vertices, indices = mesh()
    before_v = copy.deepcopy(vertices)
    before_i = copy.deepcopy(indices)
    repair(vertices, indices)
    assert vertices == before_v
    assert indices == before_i


def test_repair_is_repeatable():
    vertices, indices = mesh()
    a = mw.MeshWindingRepair().repair(vertices, indices)
    b = mw.MeshWindingRepair().repair(vertices, indices)
    assert a == b


def test_questionable_edges_are_returned():
    vertices = [vert(0, 0, 0), vert(1, 0, 0), vert(0, 1, 0), vert(0, 0, 1)]
    result = repair(vertices, [(0, 1, 2), (0, 3, 1), (1, 3, 2)])
    assert isinstance(result["questionable"], list)
