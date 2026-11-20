import iso_depth_sort as iso


def obj(obj_id, col=1.0, row=1.0, w=1, h=1, layer=0, kind="unit", shadow=False):
    return {
        "id": obj_id,
        "col": col,
        "row": row,
        "w": w,
        "h": h,
        "layer": layer,
        "kind": kind,
        "shadow": shadow,
    }


def scene(items):
    s = iso.IsoDepthSort()
    for item in items:
        s.add(item)
    return s


def test_footprint_uses_bottom_anchor():
    s = scene([obj("big", col=1, row=1, w=2, h=3), obj("small", col=3, row=2)])
    assert s.order().index("small") > s.order().index("big")


def test_fractional_movement_does_not_jump_layers():
    s = scene([obj("a", col=1.5, row=1.5), obj("b", col=1.6, row=1.5)])
    assert s.order().index("b") >= s.order().index("a")


def test_tall_object_uses_foot_anchor():
    s = scene([obj("tower", col=2, row=1, h=3), obj("unit", col=2, row=1.5)])
    assert s.order().index("unit") > s.order().index("tower")


def test_shadow_sorts_before_its_owner():
    s = scene([obj("body", col=1, row=1), obj("shadow", col=1, row=1, shadow=True)])
    order = s.order()
    assert order.index("shadow") < order.index("body")


def test_layer_number_has_priority_over_row_and_column():
    s = scene([obj("ground", col=99, row=99, layer=0), obj("bridge", col=0, row=0, layer=1)])
    assert s.order().index("bridge") > s.order().index("ground")


def test_negative_coordinates_sort_in_the_same_direction():
    s = scene([obj("a", col=-2, row=-2), obj("b", col=-1, row=-1)])
    assert s.order().index("b") > s.order().index("a")


def test_ties_are_broken_by_id_not_insertion_order():
    a = scene([obj("z", col=1, row=1), obj("a", col=1, row=1)]).order()
    b = scene([obj("a", col=1, row=1), obj("z", col=1, row=1)]).order()
    assert a == b
    assert a == ["a", "z"]


def test_repeated_order_calls_are_identical():
    s = scene([obj("a"), obj("b"), obj("c")])
    assert s.order() == s.order()


def test_removed_object_does_not_remain():
    s = scene([obj("a"), obj("b")])
    s.remove("a")
    assert s.order() == ["b"]


def test_decorations_do_not_participate_in_occlusion():
    s = scene([obj("floor", col=1, row=1, kind="decor"), obj("unit", col=1, row=1.2)])
    assert "floor" not in s.occlusion("unit")


def test_occlusion_query_returns_objects_in_front():
    s = scene([obj("front", col=1, row=1.5), obj("back", col=1, row=1.0)])
    assert s.occlusion("back") == ["front"]


def test_large_scene_returns_every_object():
    items = [obj("u-%d" % i, col=i % 100, row=i // 100) for i in range(2000)]
    assert len(scene(items).order()) == 2000


def test_snapshot_is_stable():
    s = scene([obj("a"), obj("b")])
    assert s.order() == s.order()


def test_overlapping_objects_order_is_deterministic():
    items = [obj("a", col=1, row=1, w=2, h=2), obj("b", col=2, row=2, w=2, h=2)]
    assert scene(items).order() == scene(list(reversed(items))).order()


def test_shadow_removal_does_not_affect_body():
    s = scene([obj("body"), obj("shadow", shadow=True)])
    s.remove("shadow")
    assert s.order() == ["body"]
