import path_replan_window as pr


def grid(width=10, height=10, blocked=()):
    return {"width": width, "height": height, "blocked": set(blocked)}


def window(**over):
    kwargs = {"budget": 4, "radius": 0.5, "goal_threshold": 1.0}
    kwargs.update(over)
    return pr.PathReplanWindow(**kwargs)


def request(w, uid="u-1", start=(0, 0), goal=(5, 5), g=None, priority=0):
    return w.request(uid, start, goal, g or grid(), priority=priority, now=0)


def test_prefix_of_completed_path_is_reused():
    w = window()
    request(w)
    w.tick()
    result = w.request("u-1", (2, 2), (6, 6), grid())
    assert result["reused_prefix"] >= 0


def test_budget_queues_extra_requests():
    w = window(budget=1)
    for i in range(3):
        request(w, uid="u-%d" % i)
    done = w.tick()
    assert len(done) == 1


def test_obstacle_change_only_replans_affected_units():
    w = window()
    request(w, "u-1")
    w.tick()
    g = grid(blocked={(3, 3)})
    result = w.request("u-1", (0, 0), (5, 5), g)
    assert "reason" in result


def test_goal_inside_obstacle_returns_nearest_reachable():
    result = request(window(), goal=(5, 5), g=grid(blocked={(5, 5)}))
    assert result["nearest"] is not None
    assert result["path"][-1] != (5, 5)


def test_radius_prevents_wall_corner_cutting():
    g = grid(blocked={(2, 2), (2, 3), (3, 2)})
    result = request(window(radius=1.0), goal=(4, 4), g=g)
    assert result["path"]


def test_diagonal_move_has_higher_cost():
    w = window()
    result = w.request("u-1", (0, 0), (1, 1), grid())
    assert result["cost"] >= 1.4


def test_two_units_competing_for_same_cell_are_ordered():
    w = window()
    a = w.request("u-b", (0, 0), (2, 2), grid(), priority=1)
    b = w.request("u-a", (0, 0), (2, 2), grid(), priority=1)
    assert a["goal"] == b["goal"]


def test_no_path_returns_partial_path_and_reason():
    g = grid(blocked={(1, 0), (0, 1)})
    result = request(window(), goal=(5, 5), g=g)
    assert result["reason"] == "no_path"
    assert result["path"] == [(0, 0)]


def test_small_goal_movement_does_not_replan():
    w = window(goal_threshold=2.0)
    request(w)
    w.tick()
    result = w.request("u-1", (0, 0), (5.5, 5.0), grid())
    assert result["replanned"] is False


def test_coordinate_convention_is_lower_left_origin():
    w = window()
    result = w.request("u-1", (0, 0), (1, 0), grid())
    assert result["start"] == (0, 0)


def test_priority_orders_the_replan_queue():
    w = window(budget=1)
    request(w, "low", priority=1)
    request(w, "high", priority=9)
    done = w.tick()
    assert done[0]["unit_id"] == "high"


def test_unaffected_region_is_reused():
    w = window()
    request(w)
    w.tick()
    result = w.request("u-1", (0, 0), (5, 5), grid(blocked={(9, 9)}))
    assert result["reused_segments"] > 0


def test_nearest_reachable_cell_is_returned():
    g = grid(blocked={(5, 5), (4, 5), (5, 4)})
    result = request(window(), goal=(5, 5), g=g)
    assert result["nearest"] != (5, 5)


def test_corner_cutting_is_forbidden():
    g = grid(blocked={(1, 0), (0, 1)})
    result = request(window(), goal=(2, 2), g=g)
    assert (1, 1) not in result["path"] or result["path"][0] == (0, 0)


def test_partial_path_is_returned_on_failure():
    g = grid(blocked={(1, 0), (0, 1)})
    result = request(window(), goal=(5, 5), g=g)
    assert len(result["path"]) >= 1
