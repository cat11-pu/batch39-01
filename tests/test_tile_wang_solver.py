import tile_wang_solver as tw


def tile(id, top, right, bottom, left, weight=1):
    return {"id": id, "top": top, "right": right, "bottom": bottom, "left": left, "weight": weight}


TILES = [
    tile("grass", "g", "g", "g", "g", 5),
    tile("sand", "s", "s", "s", "s", 3),
    tile("edge", "g", "s", "s", "g", 1),
]


def solver(seed=0, forbid_same=False, tiles=None):
    return tw.TileWangSolver(tiles or TILES, seed=seed, forbid_same=forbid_same)


def test_adjacent_edge_colors_match():
    result = solver().solve(4, 4)
    grid = result["grid"]
    for row in grid:
        for index in range(len(row) - 1):
            a = next(t for t in TILES if t["id"] == row[index])
            b = next(t for t in TILES if t["id"] == row[index + 1])
            assert a["right"] == b["left"]


def test_border_colors_are_pinned():
    border = {"top": "s", "bottom": "s", "left": "s", "right": "s"}
    result = solver(tiles=[tile("sea", "s", "s", "s", "s")]).solve(3, 3, border=border)
    assert all(cell == "sea" for row in result["grid"] for cell in row)


def test_same_seed_produces_same_grid():
    assert solver(seed=7).solve(5, 5)["grid"] == solver(seed=7).solve(5, 5)["grid"]


def test_conflict_is_reported_not_raised():
    result = solver(tiles=[tile("a", "a", "a", "a", "b")]).solve(2, 2)
    assert result["conflict"] is not None
    assert result["grid"] is None


def test_weighted_sampling_is_not_always_the_heaviest():
    tiles = [tile("heavy", "a", "a", "a", "a", 100), tile("light", "a", "a", "a", "a", 1)]
    grids = [solver(seed=seed, tiles=tiles).solve(2, 2)["grid"] for seed in range(20)]
    assert any("light" in row for grid in grids for row in grid)


def test_one_by_one_and_large_map_share_the_same_rules():
    assert solver().solve(1, 1)["grid"][0][0] in {t["id"] for t in TILES}
    assert len(solver().solve(5, 5)["grid"]) == 5


def test_corner_tile_checks_two_border_edges():
    border = {"top": "s", "left": "s"}
    result = solver(tiles=[tile("sea", "s", "g", "g", "s")]).solve(2, 2, border=border)
    assert result["grid"][0][0] == "sea"


def test_forbid_same_rejects_repeated_neighbor():
    result = solver(tiles=[tile("only", "a", "a", "a", "a")], forbid_same=True).solve(2, 2)
    assert result["conflict"] is not None


def test_holes_are_skipped_and_neighbors_rechecked():
    result = solver().solve(3, 3, holes={(1, 1)})
    assert result["grid"][1][1] is None


def test_single_candidate_is_accepted():
    result = solver(tiles=[tile("only", "a", "a", "a", "a")]).solve(2, 2)
    assert result["grid"] == [["only", "only"], ["only", "only"]]


def test_zero_weight_tile_is_never_selected():
    tiles = [tile("zero", "a", "a", "a", "a", 0), tile("one", "a", "a", "a", "a", 1)]
    result = solver(seed=1, tiles=tiles).solve(3, 3)
    assert all(cell == "one" for row in result["grid"] for cell in row)


def test_conflict_reports_coordinates_and_directions():
    result = solver(tiles=[tile("a", "a", "a", "a", "b")]).solve(2, 2)
    assert "x" in result["conflict"] and "y" in result["conflict"]
    assert result["conflict"]["directions"]


def test_backtrack_count_is_reported():
    result = solver().solve(3, 3)
    assert isinstance(result["backtracks"], int)


def test_result_and_report_are_separate():
    result = solver().solve(3, 3)
    assert "grid" in result
    assert "conflict" in result
    assert "backtracks" in result


def test_hole_does_not_receive_a_tile():
    result = solver().solve(2, 2, holes={(0, 0)})
    assert result["grid"][0][0] is None
