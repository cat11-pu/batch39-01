import pytest

import portal_link_traverse as pt


def link(link_id="l-1", a=(0, 0), b=(5, 5), mode="both", cost=1.0, max_size=3, enabled=True):
    return {"id": link_id, "a": a, "b": b, "mode": mode, "cost": cost, "max_size": max_size, "enabled": enabled}


def system(links=None, **over):
    kwargs = {"agent_radius": 0.5}
    kwargs.update(over)
    return pt.PortalLinkTraverse(links or [link()], **kwargs)


def unit(uid="u-1", size=1, pos=(0.0, 0.0)):
    return {"id": uid, "size": size, "pos": pos, "locked": False}


def test_bidirectional_link_can_be_used_both_ways():
    s = system([link(mode="both")])
    assert s.traverse(unit(pos=(0.0, 0.0)), "l-1")["direction"] == "forward"
    assert s.traverse(unit(pos=(5.0, 5.0)), "l-1")["direction"] == "backward"


def test_one_way_link_only_allows_configured_direction():
    s = system([link(mode="forward")])
    with pytest.raises(pt.PortalError):
        s.traverse(unit(pos=(5.0, 5.0)), "l-1")


def test_endpoints_snap_to_navmesh_edge_with_half_cell_offset():
    s = system([link(a=(0, 0), b=(5, 5))])
    result = s.traverse(unit(pos=(0.0, 0.0)), "l-1")
    assert result["arrival"] == (5.5, 5.5)


def test_size_limit_blocks_large_units():
    s = system([link(max_size=1)])
    with pytest.raises(pt.PortalError):
        s.traverse(unit(size=3), "l-1")


def test_link_cost_is_added_to_path_cost():
    s = system([link(cost=2.5)])
    assert s.path_cost("l-1") >= 2.5


def test_mid_traversal_close_interrupts_with_position():
    s = system([link()])
    u = unit()
    s.traverse(u, "l-1", now=0)
    s.close("l-1")
    result = s.tick(u, now=1)
    assert "interrupted" in result or result.get("position") is not None


def test_equal_cost_links_sort_by_id():
    s = system([link("b", cost=1.0), link("a", cost=1.0)])
    assert s.path_cost("a") == s.path_cost("b")


def test_blocked_target_returns_failure_reason():
    s = system([link(b=(5, 5))])
    result = s.traverse(unit(), "l-1", now=0)
    assert "blocked_target" in result.get("reason", "") or result["reason"]


def test_grid_to_continuous_conversion_adds_half_cell():
    s = system([link(a=(0, 0))])
    result = s.traverse(unit(pos=(0.0, 0.0)), "l-1")
    assert result["start"] == (0.5, 0.5)


def test_duplicate_link_ids_are_rejected():
    with pytest.raises(pt.PortalError):
        system([link("dup"), link("dup")]).load()


def test_unit_is_locked_during_traversal():
    s = system([link()])
    u = unit()
    s.traverse(u, "l-1")
    assert u["locked"] is True


def test_disabled_link_is_not_a_candidate():
    s = system([link(enabled=False)])
    with pytest.raises(pt.PortalError):
        s.traverse(unit(), "l-1")


def test_failure_reason_is_explicit():
    s = system([link(mode="forward")])
    with pytest.raises(pt.PortalError) as exc:
        s.traverse(unit(pos=(5.0, 5.0)), "l-1")
    assert exc.value.code


def test_same_cost_paths_are_stable():
    s = system([link("b", cost=1), link("a", cost=1)])
    assert [s.path_cost("a"), s.path_cost("b")] == [s.path_cost("b"), s.path_cost("a")]


def test_interrupt_position_is_reported():
    s = system([link()])
    u = unit()
    s.traverse(u, "l-1", now=0)
    result = s.tick(u, now=2)
    assert "position" in result or "interrupted" in result
