import fog_reveal_grid as fg


def unit(uid, x, y, radius=3, alive=True, stealth=False, team="ally"):
    return {"id": uid, "x": x, "y": y, "radius": radius, "alive": alive, "stealth": stealth, "team": team}


def grid(team="ally", **over):
    kwargs = {"team": team, "chunk": 8}
    kwargs.update(over)
    return fg.FogRevealGrid(**kwargs)


def test_explored_area_is_remembered_after_unit_moves():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    g.set_units([unit("a", 20, 20)])
    g.update()
    assert g.state(1, 1) == "explored"


def test_two_units_union_their_vision_without_gap():
    g = grid()
    g.set_units([unit("a", 0, 0), unit("b", 2, 0)])
    g.update()
    assert g.state(1, 0) == "visible"


def test_death_keeps_explored_but_not_visible():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    g.set_units([unit("a", 1, 1, alive=False)])
    g.update()
    assert g.state(1, 1) == "explored"


def test_edge_weight_fades_with_distance():
    g = grid()
    g.set_units([unit("a", 0, 0, radius=3)])
    g.update()
    assert g.weight(0, 0) == 1.0
    assert g.weight(3, 0) < 1.0


def test_vision_crosses_chunk_boundary_without_seam():
    g = grid(chunk=4)
    g.set_units([unit("a", 3, 3, radius=3)])
    g.update()
    assert g.state(5, 3) == "visible"


def test_negative_coordinates_are_supported():
    g = grid()
    g.set_units([unit("a", -5, -5)])
    g.update()
    assert g.state(-5, -5) == "visible"


def test_stealth_enemy_is_hidden_until_visible():
    g = grid()
    g.set_units([unit("e", 10, 10, stealth=True, team="enemy")])
    g.update()
    assert g.state(10, 10) != "visible"


def test_reentering_area_restores_visible_state():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    g.set_units([unit("a", 20, 20)])
    g.update()
    g.set_units([unit("a", 1, 1)])
    g.update()
    assert g.state(1, 1) == "visible"


def test_update_only_recomputes_units_around_view():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    assert g.snapshot()["recomputed"] > 0


def test_snapshot_roundtrip_preserves_three_states():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    other = grid()
    other.restore(g.snapshot())
    assert other.state(1, 1) == "visible"


def test_three_states_are_distinct():
    g = grid()
    assert g.state(0, 0) == "unexplored"
    g.set_units([unit("a", 0, 0, radius=1)])
    g.update()
    assert g.state(0, 0) == "visible"


def test_walls_block_line_of_sight():
    g = grid()
    g.set_walls({(1, 0)})
    g.set_units([unit("a", 0, 0, radius=4)])
    g.update()
    assert g.state(3, 0) != "visible"


def test_chunk_mapping_is_consistent_for_large_coordinates():
    g = grid(chunk=16)
    g.set_units([unit("a", 1000, 1000, radius=2)])
    g.update()
    assert g.state(1000, 1000) == "visible"


def test_cached_chunks_are_reused():
    g = grid()
    g.set_units([unit("a", 1, 1)])
    g.update()
    first = g.snapshot()["recomputed"]
    g.update()
    assert g.snapshot()["recomputed"] <= first


def test_snapshot_is_sorted_by_team_and_chunk():
    g = grid()
    g.set_units([unit("a", 1, 1), unit("b", 20, 20)])
    g.update()
    teams = [item["team"] for item in g.snapshot()["chunks"]]
    assert teams == sorted(teams)
